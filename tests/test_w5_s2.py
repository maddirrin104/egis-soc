"""W5-04 reviewed synthetic S2 and one common fork, without gold or S3 facts."""

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import DevelopmentV2
from egis_soc.integrity import canonical_bytes
from egis_soc.summarization.atomization import (
    create_claim_archive, extract_generated_candidates,
)
from egis_soc.summarization.generation import GenerationConfig, generate_and_archive
from egis_soc.summarization.s1 import create_s1_archive, render_s1
from egis_soc.summarization.s2 import (
    ReviewBatch, ReviewedCandidate, ReviewedRevision, create_s2_archive,
    read_common_fork, run_s2, verify_s2_archive,
)
from test_w5_atomization import context, generated
from test_w5_contract import CLAIM, RecordingBackend
from test_w5_generation import FakeBackend


def prepared(text, source=None, *, decision="atomic_factual",
             cited_support="supported", relevance=("relevant",)):
    source = source or context()
    draft = extract_generated_candidates(source, generated(text, source)).draft
    s1 = render_s1(source, draft)
    review = ReviewBatch(
        draft.sha256, hashlib.sha256(canonical_bytes(s1.to_record())).hexdigest(),
        tuple(ReviewedCandidate(claim.claim_id, claim.text,
                                "authored-synthetic-review", "One synthetic event",
                                decision, relevance, cited_support)
              for claim in draft.claims))
    return source, draft, s1, review


def verifier(backend=None):
    return SyntheticV3Verifier(DevelopmentV2(backend or RecordingBackend()))


class W5S2Tests(unittest.TestCase):
    def test_review_gate_precedes_model_and_rejects_scope_drift(self):
        source, draft, s1, review = prepared(f"{CLAIM} [E1].")
        backend = RecordingBackend()
        with self.assertRaisesRegex(ValueError, "s2_fixed_input_mismatch"):
            run_s2(source, draft, s1, replace(review, draft_sha256="f" * 64),
                   verifier(backend))
        with self.assertRaisesRegex(ValueError, "s2_incomplete_or_reordered_review"):
            run_s2(source, draft, s1, replace(review, candidates=(
                replace(review.candidates[0], claim_id="OTHER"),)),
                   verifier(backend))
        with self.assertRaisesRegex(ValueError, "s2_review_claim_or_scope_mismatch"):
            run_s2(source, draft, s1, replace(review, candidates=(
                replace(review.candidates[0], original_text="forged"),)),
                   verifier(backend))
        self.assertEqual(backend.calls, [])
        with self.assertRaises(TypeError):
            run_s2(source, draft, s1, review, verifier(backend),
                   operational_fact_inventory={"gold_critical_facts": []})
        injected = review.to_record()
        injected["gold_critical_facts"] = [{"invented": True}]
        with self.assertRaisesRegex(ValueError, "invalid_s2_review_record"):
            ReviewBatch.from_record(injected)
        bad_citation = replace(review, candidates=(replace(
            review.candidates[0], citation_relevance=("irrelevant",)),))
        with self.assertRaisesRegex(ValueError, "s2_invalid_cited_support_review"):
            run_s2(source, draft, s1, bad_citation, verifier(backend))
        self.assertEqual(backend.calls, [])

    def test_supported_is_kept_only_with_reviewed_relevant_citations(self):
        source, draft, s1, review = prepared(f"{CLAIM} [E1].")
        backend = RecordingBackend()
        report = run_s2(source, draft, s1, review, verifier(backend))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(report["verification"][0]["prediction"], "supported")
        self.assertFalse(report["verification"][0]["review_required"])
        self.assertEqual(report["decisions"][0]["action"], "keep")
        self.assertEqual(report["final_claims"][0]["text"], CLAIM)
        self.assertEqual(len(report["verification"][0]["rule_trace"]), 4)
        self.assertEqual(report["verification"][0]["citation_checks"][0]["valid"], True)
        self.assertEqual(report["gold_status"], "NOT_GOLD")
        self.assertNotIn("operational_fact_inventory", report)
        weak = replace(review, candidates=(replace(
            review.candidates[0], cited_set_support="not_assessed",
            citation_relevance=("not_assessed",)),))
        blocked = run_s2(source, draft, s1, weak, verifier())
        self.assertEqual(blocked["verification"][0]["prediction"], "supported")
        self.assertEqual(blocked["decisions"][0]["action"], "abstain")
        self.assertEqual(blocked["final_claims"], [])

    def test_direct_refutation_removes_but_insufficient_abstains(self):
        wrong = CLAIM.replace("outcome=success", "outcome=failure")
        source, draft, s1, review = prepared(f"{wrong} [E1].")
        refuted = run_s2(source, draft, s1, review, verifier())
        self.assertEqual(refuted["verification"][0]["prediction"], "contradicted")
        self.assertEqual(refuted["decisions"][0]["action"], "remove")
        self.assertEqual(refuted["final_claims"], [])
        source, draft, s1, review = prepared("Exfiltration occurred [E1].")
        unresolved = run_s2(source, draft, s1, review, verifier())
        self.assertEqual(unresolved["verification"][0]["prediction"], "insufficient")
        self.assertEqual(unresolved["decisions"][0]["action"], "abstain")
        self.assertTrue(unresolved["decisions"][0]["review_required"])

    def test_reviewed_correction_creates_new_id_and_reverifies(self):
        wrong = CLAIM.replace("outcome=success", "outcome=failure")
        source, draft, s1, review = prepared(f"{wrong} [E1].")
        corrected = ReviewedRevision(
            draft.claims[0].claim_id, "correct", CLAIM, ("E1",),
            "authored-synthetic-review", "Same record has success",
            ("relevant",), "supported")
        report = run_s2(source, draft, s1,
                        replace(review, revisions=(corrected,)), verifier())
        self.assertEqual([item["prediction"] for item in report["verification"]],
                         ["contradicted", "supported"])
        self.assertEqual(report["decisions"][0]["action"], "correct")
        self.assertNotEqual(report["final_claims"][0]["claim_id"],
                            draft.claims[0].claim_id)
        self.assertEqual(report["final_claims"][0]["source_claim_id"],
                         draft.claims[0].claim_id)
        self.assertEqual(report["final_claims"][0]["text"], CLAIM)
        with self.assertRaisesRegex(ValueError, "s2_revision_not_reviewed_or_outside_scope"):
            run_s2(source, draft, s1, replace(review, revisions=(
                replace(corrected, citation_ids=("FOREIGN",)),)), verifier())

    def test_unreviewed_boundary_and_backend_failure_stay_visible(self):
        source, draft, s1, review = prepared(
            "Alice logged on and exfiltrated data [E1].",
            decision="requires_review")
        backend = RecordingBackend()
        report = run_s2(source, draft, s1, review, verifier(backend))
        self.assertEqual(report["verification"], [])
        self.assertEqual(report["decisions"][0]["reason"],
                         "ATOMICITY_OR_TYPE_REVIEW")
        self.assertEqual(backend.calls, [])
        source, draft, s1, review = prepared(f"{CLAIM} [E1].")
        failed = run_s2(source, draft, s1, review, verifier(
            RecordingBackend(RuntimeError("private backend detail"))))
        assessment = failed["verification"][0]
        self.assertEqual((assessment["prediction"], assessment["review_required"],
                          assessment["failure_tag"]),
                         ("insufficient", True, "VERIFIER_FAILURE"))
        self.assertEqual(failed["decisions"][0]["action"], "abstain")
        self.assertNotIn("private backend detail", str(failed))
        revision = ReviewedRevision(
            draft.claims[0].claim_id, "correct", CLAIM.replace("actor=alice", "actor=bob"),
            ("E1",), "authored-synthetic-review", "proposed correction",
            ("relevant",), "not_assessed")
        backend = RecordingBackend(RuntimeError("private backend detail"))
        stopped = run_s2(source, draft, s1,
                         replace(review, revisions=(revision,)), verifier(backend))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len(stopped["verification"]), 1)
        self.assertEqual(stopped["decisions"][0]["reason"], "VERIFIER_FAILURE")

    def test_archive_is_create_only_and_s2_s3_consume_same_verified_fork(self):
        source = context()
        config = GenerationConfig("synthetic-model", "a" * 64)
        backend_binding = {"kind": "synthetic_fake_backend"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft_path, claims_path, s1_path, s2_path = (
                root / name for name in ("w5_01", "w5_02", "w5_03", "w5_04"))
            generate_and_archive(source, config, FakeBackend(
                '{"draft_text":"Alice logged on [E1]."}'), draft_path)
            result = create_claim_archive(source, config, draft_path, claims_path)
            s1 = create_s1_archive(source, config, draft_path, claims_path, s1_path)
            claim = result.draft.claims[0]
            review = ReviewBatch(
                result.draft.sha256,
                hashlib.sha256(canonical_bytes(s1.to_record())).hexdigest(),
                (ReviewedCandidate(claim.claim_id, claim.text,
                                   "authored-synthetic-review", "single event",
                                   "atomic_factual", ("relevant",),
                                   "supported"),))
            report = create_s2_archive(
                source, config, draft_path, claims_path, s1_path, review,
                verifier(), backend_binding, s2_path)
            self.assertEqual(report, verify_s2_archive(
                source, config, draft_path, claims_path, s1_path, review,
                backend_binding, s2_path))
            s2_start = read_common_fork(
                source, config, draft_path, claims_path, s1_path, review,
                backend_binding, s2_path, arm="S2")
            s3_start = read_common_fork(
                source, config, draft_path, claims_path, s1_path, review,
                backend_binding, s2_path, arm="S3")
            self.assertEqual(s2_start, s3_start)
            self.assertIn(b'"operational_inventory_status":"NOT_ACCESSED_S2"',
                          s2_start)
            with self.assertRaises(FileExistsError):
                create_s2_archive(source, config, draft_path, claims_path,
                                  s1_path, review, verifier(), backend_binding,
                                  s2_path)
            with self.assertRaisesRegex(ValueError, "invalid_s2_fork_arm"):
                read_common_fork(source, config, draft_path, claims_path,
                                 s1_path, review, backend_binding, s2_path,
                                 arm="S1")
            fork = s2_path / "fork.json"
            fork.write_bytes(fork.read_bytes().replace(b"NOT_ACCESSED_S2",
                                                       b"USED_GOLD_FACTS"))
            with self.assertRaisesRegex(ValueError, "w5_04_archive_drift"):
                verify_s2_archive(source, config, draft_path, claims_path,
                                  s1_path, review, backend_binding, s2_path)


if __name__ == "__main__":
    unittest.main()
