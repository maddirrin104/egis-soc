"""W5-06 synthetic controlled S3 repair and archived-fork regressions."""

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import DevelopmentV2
from egis_soc.integrity import canonical_bytes
from egis_soc.schemas import EvidenceEvent, IncidentBundle
from egis_soc.summarization.atomization import create_claim_archive
from egis_soc.summarization.contract import retrieve_synthetic_incident
from egis_soc.summarization.generation import GenerationConfig, generate_and_archive
from egis_soc.summarization.omission import (
    check_operational_omissions, create_omission_archive,
)
from egis_soc.summarization.s1 import create_s1_archive
from egis_soc.summarization.s2 import (
    ReviewBatch, ReviewedCandidate, create_s2_archive, run_s2,
)
from egis_soc.summarization.s3 import (
    RepairAction, RepairPlan, RepairRound, create_s3_archive,
    run_s3, verify_s3_archive,
)
from test_w5_atomization import context
from test_w5_contract import CLAIM, RecordingBackend
from test_w5_generation import FakeBackend
from test_w5_omission import fork_for
from test_w5_s2 import prepared, verifier


def inputs(text="Exfiltration occurred [E1].", source=None,
           relevance=("relevant",)):
    source, draft, s1, review = prepared(text, source=source,
                                        relevance=relevance)
    s2 = run_s2(source, draft, s1, review, verifier())
    fork = fork_for(source, s2)
    inventory, omission = check_operational_omissions(source, s2, fork)
    return source, s2, fork, inventory, omission


def plan_for(fork, omission, rounds=()):
    return RepairPlan(
        hashlib.sha256(fork).hexdigest(),
        hashlib.sha256(canonical_bytes(omission)).hexdigest(),
        "authored-synthetic-engineering-review",
        "Synthetic engineering proposal, not gold or analyst approval",
        rounds)


def add(fact):
    return RepairAction(
        "add", None, fact["fact_id"], fact["statement"],
        tuple(fact["evidence_ids"]), "authored-synthetic-review",
        "Observed source record only", ("relevant",), "supported")


def three_event_context():
    source = context(two_events=True)
    raw = "synthetic record R3: charlie logon success on WS03"
    third = EvidenceEvent.model_validate({
        **source.events[1].model_dump(mode="python"),
        "evidence_id": "E3",
        "normalized_fields": {"record_ref": "R3", "event_type": "logon",
                              "actor": "charlie", "host": "WS03",
                              "outcome": "success"},
        "provenance": {**source.events[1].provenance.model_dump(mode="python"),
                       "raw_message": raw,
                       "raw_message_ref": "synthetic:w5:E3",
                       "sha256": hashlib.sha256(raw.encode()).hexdigest()},
    })
    bundle = IncidentBundle.model_validate({
        **source.bundle.model_dump(mode="python"),
        "evidence_ids": ["E1", "E2", "E3"]})
    return retrieve_synthetic_incident(bundle, (*source.events, third),
                                       query="logon")


class NeutralBackend:
    def __init__(self):
        self.calls = 0

    def score(self, premise, hypothesis):
        self.calls += 1
        return (0.0, 0.0, 5.0), False


class TokenBackend(RecordingBackend):
    def tokenizer(self, premise, hypothesis, *, truncation):
        return {"input_ids": [1] * (len(premise.split()) +
                                     len(hypothesis.split()))}


class W5S3Tests(unittest.TestCase):
    def test_zero_round_preserves_s2_and_routes_unreviewed_candidate(self):
        source, s2, fork, inventory, omission = inputs()
        plan = plan_for(fork, omission)
        before = canonical_bytes(s2)
        result = run_s3(source, s2, fork, inventory, omission, plan)
        self.assertEqual(canonical_bytes(s2), before)
        self.assertEqual(result["final_claims"], [])
        self.assertEqual(result["executed_rounds"], 0)
        self.assertEqual(result["stop_reason"], "NO_REPAIR_PROPOSAL")
        self.assertEqual(result["s3_only_cost"]["v3_calls"], 0)
        self.assertEqual(result["s3_only_cost"]["nli_input_tokens"], 0)
        self.assertEqual(len(result["review_queue"]), 2)
        self.assertEqual({item["reason"] for item in result["review_queue"]},
                         {"S2_ORIGINAL_REQUIRES_REVIEW",
                          "OPERATIONAL_CANDIDATE_NOT_GOLD_OR_ADJUDICATED"})
        self.assertEqual(result["gold_status"], "NOT_GOLD")
        self.assertEqual(result["cfr_status"], "NOT_SCORED")

    def test_addition_requires_fresh_v3_and_preserves_source_lineage(self):
        source, s2, fork, inventory, omission = inputs()
        fact = inventory["facts"][0]
        plan = plan_for(fork, omission, (RepairRound((add(fact),)),))
        backend = RecordingBackend()
        result = run_s3(source, s2, fork, inventory, omission, plan,
                        verifier(backend))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["executed_rounds"], 1)
        self.assertEqual(result["stop_reason"], "NO_ACTIONABLE_OMISSION")
        self.assertEqual(result["s3_only_cost"]["v3_calls"], 1)
        self.assertEqual(result["s3_only_cost"]["nli_token_status"],
                         "NOT_MEASURED")
        self.assertEqual(result["s3_only_cost"]["generation_calls"], 0)
        self.assertGreaterEqual(result["s3_only_cost"]["v3_latency_ns"], 0)
        self.assertEqual(result["verifications"][0]["assessment"]["prediction"],
                         "supported")
        self.assertEqual(result["history"][0]["result"],
                         "reverified_supported")
        self.assertIsNone(result["history"][0]["before_claim_id"])
        final = result["final_claims"][0]
        self.assertEqual(final["source_fact_id"], fact["fact_id"])
        self.assertEqual(final["citation_ids"], fact["evidence_ids"])
        self.assertEqual(final["text"], fact["statement"])
        self.assertEqual(final["origin"], "S3_REVERIFIED_REPAIR")
        measured = run_s3(source, s2, fork, inventory, omission, plan,
                          verifier(TokenBackend()))
        self.assertEqual(measured["s3_only_cost"]["nli_token_status"],
                         "MEASURED")
        self.assertGreater(measured["s3_only_cost"]["nli_input_tokens"], 0)

    def test_two_round_cap_and_distinct_source_candidates(self):
        source, s2, fork, inventory, omission = inputs(
            source=three_event_context())
        self.assertEqual(len(inventory["facts"]), 3)
        rounds = tuple(RepairRound((add(fact),)) for fact in
                       inventory["facts"][:2])
        plan = plan_for(fork, omission, rounds)
        backend = RecordingBackend()
        result = run_s3(source, s2, fork, inventory, omission, plan,
                        verifier(backend))
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result["executed_rounds"], 2)
        self.assertEqual(result["stop_reason"], "ROUND_CAP_REACHED")
        self.assertEqual(len(result["final_claims"]), 2)
        with self.assertRaisesRegex(ValueError, "invalid_s3_repair_plan"):
            plan_for(fork, omission, (*rounds, rounds[0]))

    def test_fabricated_escalation_foreign_scope_and_stale_parent_fail_before_model(self):
        source, s2, fork, inventory, omission = inputs()
        fact = inventory["facts"][0]
        valid = add(fact)
        backend = RecordingBackend()
        invalid = (
            replace(valid, proposed_text="Alice compromised the host"),
            replace(valid, fact_id="FOREIGN-FACT"),
            replace(valid, citation_ids=("FOREIGN-EVIDENCE",)),
        )
        for proposal in invalid:
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                run_s3(source, s2, fork, inventory, omission,
                       plan_for(fork, omission,
                                (RepairRound((proposal,)),)), verifier(backend))
        with self.assertRaisesRegex(ValueError, "s3_parent_or_inventory_mismatch"):
            run_s3(source, s2, fork, inventory, omission,
                   replace(plan_for(fork, omission), fork_sha256="f" * 64))
        with self.assertRaises(ValueError):
            run_s3(source, s2, fork, {**inventory, "gold_critical_facts": []},
                   omission, plan_for(fork, omission))
        self.assertEqual(backend.calls, [])
        covered_source, covered_s2, covered_fork, covered_inventory, covered_omission = (
            inputs(f"{CLAIM} [E1]."))
        covered_fact = covered_inventory["facts"][0]
        with self.assertRaisesRegex(ValueError,
                                    "s3_unsupported_or_out_of_scope_proposal"):
            run_s3(covered_source, covered_s2, covered_fork,
                   covered_inventory, covered_omission,
                   plan_for(covered_fork, covered_omission,
                            (RepairRound((add(covered_fact),)),)),
                   verifier(backend))
        self.assertEqual(backend.calls, [])
        injected = plan_for(fork, omission).to_record()
        injected["gold_critical_facts"] = []
        with self.assertRaisesRegex(ValueError, "invalid_s3_plan_record"):
            RepairPlan.from_record(injected)

    def test_insufficient_and_backend_failure_stop_without_promotion(self):
        source, s2, fork, inventory, omission = inputs()
        fact = inventory["facts"][0]
        plan = plan_for(fork, omission, (RepairRound((add(fact),)),))
        neutral = NeutralBackend()
        insufficient = run_s3(source, s2, fork, inventory, omission, plan,
                              verifier(neutral))
        self.assertEqual(neutral.calls, 1)
        self.assertEqual(insufficient["stop_reason"], "REPAIR_NOT_SUPPORTED")
        self.assertEqual(insufficient["final_claims"], [])
        self.assertEqual(insufficient["verifications"][0]["assessment"]["prediction"],
                         "insufficient")
        failed = run_s3(source, s2, fork, inventory, omission, plan,
                        verifier(RecordingBackend(RuntimeError(
                            "private backend detail"))))
        self.assertEqual(failed["stop_reason"], "VERIFIER_FAILURE")
        self.assertEqual(failed["final_claims"], [])
        self.assertNotIn("private backend detail", str(failed))

    def test_remove_rewrite_qualify_and_explicit_abstain(self):
        source, s2, fork, inventory, omission = inputs(
            f"{CLAIM} [E1].", source=context(two_events=True))
        self.assertEqual(len(s2["final_claims"]), 1)
        initial = s2["final_claims"][0]
        remove = RepairAction("remove", initial["claim_id"], None, None, (),
                              "authored-synthetic-review", "Remove for review")
        removed = run_s3(source, s2, fork, inventory, omission,
                         plan_for(fork, omission, (RepairRound((remove,)),)))
        self.assertEqual(removed["final_claims"], [])
        self.assertEqual(removed["s3_only_cost"]["v3_calls"], 0)
        self.assertIn("S3_REMOVED_PREVIOUS_SOURCE_COVERAGE",
                      {item["reason"] for item in removed["review_queue"]})
        invalid_rewrite = RepairAction(
            "rewrite", initial["claim_id"], inventory["facts"][1]["fact_id"],
            inventory["facts"][1]["statement"], ("E2",),
            "authored-synthetic-review", "Unrelated event",
            ("relevant",), "supported")
        with self.assertRaisesRegex(ValueError,
                                    "s3_rewrite_requires_abstained_s2_claim"):
            run_s3(source, s2, fork, inventory, omission,
                   plan_for(fork, omission,
                            (RepairRound((invalid_rewrite,)),)),
                   verifier())
        source, s2, fork, inventory, omission = inputs(
            "Actor alice logged on to host WS01 with a successful outcome "
            "[E1,E2].", source=context(two_events=True),
            relevance=("relevant", "relevant"))
        self.assertEqual(s2["final_claims"], [])
        abstained = s2["verification"][0]
        first = inventory["facts"][0]
        for action_name in ("rewrite", "qualify"):
            action = RepairAction(
                action_name, abstained["claim_id"], first["fact_id"],
                first["statement"], tuple(first["evidence_ids"]),
                "authored-synthetic-review", "Restore observed logon atom",
                ("relevant",), "supported")
            backend = RecordingBackend()
            changed = run_s3(source, s2, fork, inventory, omission,
                             plan_for(fork, omission,
                                      (RepairRound((action,)),)), verifier(backend))
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(changed["history"][0]["before_claim_id"],
                             abstained["claim_id"])
            self.assertEqual(changed["history"][0]["before_citation_ids"],
                             ["E1", "E2"])
            self.assertEqual(changed["history"][0]["after_citation_ids"],
                             first["evidence_ids"])
            self.assertNotEqual(changed["final_claims"][0]["claim_id"],
                                abstained["claim_id"])
        abstain = RepairAction("abstain", None, first["fact_id"], None, (),
                               "authored-synthetic-review", "Needs analyst")
        stopped = run_s3(source, s2, fork, inventory, omission,
                         plan_for(fork, omission,
                                  (RepairRound((abstain,)),)))
        self.assertEqual(stopped["stop_reason"], "EXPLICIT_ABSTAIN")
        self.assertEqual(stopped["final_claims"], [])

    def test_create_only_archive_replays_and_rejects_parent_or_output_drift(self):
        source = context()
        config = GenerationConfig("synthetic-model", "a" * 64)
        binding = {"kind": "synthetic_fake_backend"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft_path, claims_path, s1_path, s2_path, omission_path, target = (
                root / name for name in ("w5_01", "w5_02", "w5_03", "w5_04",
                                       "w5_05", "w5_06"))
            generate_and_archive(source, config, FakeBackend(
                '{"draft_text":"Alice logged on [E1]."}'), draft_path)
            result = create_claim_archive(source, config, draft_path, claims_path)
            s1 = create_s1_archive(source, config, draft_path, claims_path, s1_path)
            claim = result.draft.claims[0]
            review = ReviewBatch(
                result.draft.sha256,
                hashlib.sha256(canonical_bytes(s1.to_record())).hexdigest(),
                (ReviewedCandidate(claim.claim_id, claim.text,
                                   "authored-synthetic-review", "one event",
                                   "atomic_factual", ("relevant",),
                                   "supported"),))
            create_s2_archive(source, config, draft_path, claims_path, s1_path,
                              review, verifier(), binding, s2_path)
            create_omission_archive(source, config, draft_path, claims_path,
                                    s1_path, review, binding, s2_path,
                                    omission_path)
            fork_raw = (s2_path / "fork.json").read_bytes()
            omission = json.loads((omission_path / "omission.json").read_bytes())
            inventory = json.loads((omission_path / "inventory.json").read_bytes())
            plan = plan_for(fork_raw, omission, (RepairRound((
                add(inventory["facts"][0]),)),))
            saved = create_s3_archive(
                source, config, draft_path, claims_path, s1_path, review,
                binding, s2_path, omission_path, plan, verifier(), target)
            self.assertEqual(saved, verify_s3_archive(
                source, config, draft_path, claims_path, s1_path, review,
                binding, s2_path, omission_path, plan, target))
            self.assertEqual((s2_path / "fork.json").read_bytes(), fork_raw)
            self.assertEqual(saved["history"][0]["result"],
                             "reverified_supported")
            with self.assertRaises(FileExistsError):
                create_s3_archive(source, config, draft_path, claims_path,
                                  s1_path, review, binding, s2_path,
                                  omission_path, plan, verifier(), target)
            output = target / "s3_report.json"
            output.write_bytes(output.read_bytes().replace(
                b"reverified_supported", b"rejected_after_v3"))
            with self.assertRaisesRegex(ValueError, "invalid_w5_06_archive_record"):
                verify_s3_archive(source, config, draft_path, claims_path,
                                  s1_path, review, binding, s2_path,
                                  omission_path, plan, target)
            (s2_path / "fork.json").write_bytes(fork_raw.replace(
                b"NOT_ACCESSED_S2", b"USED_GOLD_FACTS"))
            with self.assertRaisesRegex(ValueError, "w5_04_archive_drift"):
                verify_s3_archive(source, config, draft_path, claims_path,
                                  s1_path, review, binding, s2_path,
                                  omission_path, plan, target)


if __name__ == "__main__":
    unittest.main()
