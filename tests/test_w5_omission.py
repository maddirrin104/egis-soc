"""W5-05 source-only operational candidates and conservative S2 omission checks."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import DevelopmentV2
from egis_soc.integrity import canonical_bytes
from egis_soc.schemas import EvidenceEvent, EvaluationGoldRecord, GoldFact
from egis_soc.summarization.atomization import create_claim_archive
from egis_soc.summarization.contract import retrieve_synthetic_incident
from egis_soc.summarization.generation import GenerationConfig, generate_and_archive
from egis_soc.summarization.omission import (
    build_operational_inventory, check_operational_omissions,
    create_omission_archive, verify_omission_archive,
)
from egis_soc.summarization.s1 import create_s1_archive
from egis_soc.summarization.s2 import (
    ReviewBatch, ReviewedCandidate, create_s2_archive, run_s2,
)
from test_w5_atomization import context
from test_w5_contract import CLAIM, RecordingBackend, synthetic_incident
from test_w5_generation import FakeBackend
from test_w5_s2 import prepared, verifier


def fork_for(source, report):
    inventory = build_operational_inventory(source)
    return canonical_bytes({
        "incident_id": source.bundle.incident_id,
        "tenant_id": source.bundle.tenant_id,
        "retrieval_sha256": inventory["retrieval_sha256"],
        "s2_report_sha256": hashlib.sha256(canonical_bytes(report)).hexdigest(),
        "operational_inventory_status": "NOT_ACCESSED_S2",
    })


class W5OmissionTests(unittest.TestCase):
    def test_inventory_is_source_only_and_rejects_gold_shaped_inputs(self):
        source = context()
        inventory = build_operational_inventory(source)
        self.assertEqual(inventory["source_evidence_ids"], ["E1"])
        fact = inventory["facts"][0]
        self.assertEqual(fact["evidence_ids"], ["E1"])
        self.assertEqual(fact["observability"], "observable")
        self.assertEqual(fact["criticality"], "not_adjudicated")
        self.assertEqual(fact["support_status"], "source_recorded_not_adjudicated")
        self.assertEqual(fact["statement"], CLAIM)
        self.assertEqual(fact["provenance"]["raw_sha256"],
                         source.events[0].provenance.sha256)
        for forbidden in (GoldFact.model_construct(),
                          EvaluationGoldRecord.model_construct(),
                          {"gold_critical_facts": []}):
            with self.subTest(type=type(forbidden).__name__), self.assertRaises(TypeError):
                build_operational_inventory(forbidden)
        with self.assertRaises(TypeError):
            build_operational_inventory(source, generated_summary=CLAIM)
        bundle, events = synthetic_incident(fields={
            "record_ref": "R1", "event_type": "logon", "actor": "alice",
            "host": "WS01", "outcome": "success", "human_label": "supported"})
        with self.assertRaisesRegex(ValueError, "evaluation_field_in_inference_evidence"):
            retrieve_synthetic_incident(bundle, events, query="logon")

    def test_exact_supported_match_and_unparseable_or_conflicting_claims(self):
        source, draft, s1, review = prepared(f"{CLAIM} [E1].")
        report = run_s2(source, draft, s1, review, verifier())
        self.assertEqual(len(report["final_claims"]), 1)
        _, found = check_operational_omissions(source, report, fork_for(source, report))
        self.assertEqual(found["findings"][0]["outcome"], "covered")
        self.assertFalse(found["findings"][0]["review_required"])
        self.assertEqual(found["findings"][0]["match_trace"][0]["reason"],
                         "ALL_OBSERVED_ATTRIBUTES_MATCH")
        for text, expected in (
            ("Alice logged on successfully", "SEMANTIC_MATCH_REVIEW_REQUIRED"),
            (CLAIM.replace("outcome=success", "outcome=failure"),
             "S2_SOURCE_ATTRIBUTE_CONFLICT"),
        ):
            changed = copy.deepcopy(report)
            changed["final_claims"][0]["text"] = text
            _, screen = check_operational_omissions(source, changed,
                                                    fork_for(source, changed))
            self.assertEqual(screen["findings"][0]["outcome"], "unknown")
            self.assertEqual(screen["findings"][0]["reason"], expected)
        changed = copy.deepcopy(report)
        changed["final_claims"][0]["text"] = CLAIM.replace("record=R1", "record=R9")
        _, screen = check_operational_omissions(source, changed,
                                                fork_for(source, changed))
        self.assertEqual(screen["findings"][0]["outcome"],
                         "candidate_unmentioned")
        changed = copy.deepcopy(report)
        changed["final_claims"].append({
            **changed["final_claims"][0], "claim_id": "C-CONFLICT",
            "text": CLAIM.replace("outcome=success", "outcome=failure")})
        _, screen = check_operational_omissions(source, changed,
                                                fork_for(source, changed))
        self.assertEqual(screen["findings"][0]["outcome"], "unknown")
        self.assertEqual(screen["findings"][0]["reason"],
                         "S2_SOURCE_ATTRIBUTE_CONFLICT")
        with self.assertRaisesRegex(ValueError, "w5_05_s2_fork_mismatch"):
            check_operational_omissions(source, report, b'{}')

    def test_missing_conflicting_and_extra_source_fields_stay_unknown(self):
        bundle, events = synthetic_incident(fields={
            "record_ref": "R1", "event_type": "logon", "actor": "alice",
            "host": "WS01"})
        partial = retrieve_synthetic_incident(bundle, events, query="logon")
        fact = build_operational_inventory(partial)["facts"][0]
        self.assertIsNone(fact["statement"])
        self.assertIn("MISSING_OR_UNSUPPORTED_OUTCOME", fact["uncertainty"])
        empty_report = {"incident_id": partial.bundle.incident_id,
                        "tenant_id": partial.bundle.tenant_id,
                        "retrieved_evidence_ids": list(partial.evidence_ids),
                        "final_claims": []}
        _, screen = check_operational_omissions(
            partial, empty_report, fork_for(partial, empty_report))
        self.assertEqual(screen["findings"][0]["outcome"], "unknown")
        bundle, events = synthetic_incident(fields={
            "record_ref": "R1", "event_type": "logon", "actor": "alice",
            "host": "WS01", "outcome": "success",
            "generated_summary": "invented attack conclusion"})
        extra = retrieve_synthetic_incident(bundle, events, query="logon")
        fact = build_operational_inventory(extra)["facts"][0]
        self.assertIsNone(fact["statement"])
        self.assertIn("UNREVIEWED_SOURCE_FIELDS", fact["uncertainty"])
        source = context(two_events=True)
        second = EvidenceEvent.model_validate({
            **source.events[1].model_dump(mode="python"),
            "normalized_fields": {"record_ref": "R1", "event_type": "logon",
                                  "actor": "bob", "host": "WS02",
                                  "outcome": "failure"}})
        conflict = retrieve_synthetic_incident(
            source.bundle, (source.events[0], second), query="logon")
        facts = build_operational_inventory(conflict)["facts"]
        self.assertEqual(len(facts), 2)
        self.assertTrue(all(item["statement"] is None for item in facts))
        self.assertTrue(all("CONFLICTING_SOURCE_RECORD" in item["uncertainty"]
                            for item in facts))

    def test_empty_s2_is_reviewable_candidate_not_cfr_or_gold(self):
        source, draft, s1, review = prepared("Exfiltration occurred [E1].")
        report = run_s2(source, draft, s1, review, verifier())
        self.assertEqual(report["final_claims"], [])
        inventory, screen = check_operational_omissions(
            source, report, fork_for(source, report))
        self.assertEqual(len(inventory["facts"]), 1)
        self.assertEqual(screen["findings"][0]["outcome"], "candidate_unmentioned")
        self.assertEqual(screen["findings"][0]["match_trace"], [])
        self.assertTrue(screen["findings"][0]["review_required"])
        self.assertEqual(screen["cfr_status"], "NOT_SCORED")
        self.assertEqual(screen["gold_status"], "NOT_GOLD")

    def test_archive_is_create_only_parent_bound_and_tamper_detected(self):
        source = context()
        config = GenerationConfig("synthetic-model", "a" * 64)
        binding = {"kind": "synthetic_fake_backend"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft_path, claims_path, s1_path, s2_path, target = (
                root / name for name in ("w5_01", "w5_02", "w5_03",
                                       "w5_04", "w5_05"))
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
                              review, SyntheticV3Verifier(DevelopmentV2(
                                  RecordingBackend())), binding, s2_path)
            original_fork = (s2_path / "fork.json").read_bytes()
            screen = create_omission_archive(
                source, config, draft_path, claims_path, s1_path, review,
                binding, s2_path, target)
            self.assertEqual(screen, verify_omission_archive(
                source, config, draft_path, claims_path, s1_path, review,
                binding, s2_path, target))
            self.assertEqual((s2_path / "fork.json").read_bytes(), original_fork)
            self.assertEqual(screen["findings"][0]["outcome"],
                             "candidate_unmentioned")
            with self.assertRaises(FileExistsError):
                create_omission_archive(source, config, draft_path, claims_path,
                                        s1_path, review, binding, s2_path, target)
            omission = target / "omission.json"
            omission.write_bytes(omission.read_bytes().replace(
                b"candidate_unmentioned", b"covered"))
            with self.assertRaisesRegex(ValueError, "w5_05_archive_drift"):
                verify_omission_archive(source, config, draft_path, claims_path,
                                        s1_path, review, binding, s2_path, target)
            (s2_path / "fork.json").write_bytes(original_fork.replace(
                b"NOT_ACCESSED_S2", b"USED_OPERATIONAL_FACTS"))
            with self.assertRaisesRegex(ValueError, "w5_04_archive_drift"):
                verify_omission_archive(source, config, draft_path, claims_path,
                                        s1_path, review, binding, s2_path, target)


if __name__ == "__main__":
    unittest.main()
