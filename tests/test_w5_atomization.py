"""W5-02 generated-draft claim/citation candidate boundaries, synthetic only."""

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, IncidentBundle
from egis_soc.development_v2 import DevelopmentV2
from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.summarization.atomization import (
    AtomizationFailure, create_claim_archive, extract_generated_candidates,
    verify_claim_archive,
)
from egis_soc.summarization.contract import (
    retrieve_synthetic_incident, verify_synthetic_draft,
)
from egis_soc.summarization.generation import (
    GeneratedDraft, GenerationConfig, generate_and_archive,
)
from test_w5_contract import RecordingBackend, synthetic_incident
from test_w5_generation import FakeBackend


DIGEST = "a" * 64


def context(*, two_events=False):
    bundle, events = synthetic_incident()
    if two_events:
        raw = "synthetic record R2: bob logon failure on WS02"
        second = EvidenceEvent(
            evidence_id="E2", incident_id=bundle.incident_id,
            tenant_id=bundle.tenant_id,
            normalized_fields={"record_ref": "R2", "event_type": "logon",
                               "actor": "bob", "host": "WS02",
                               "outcome": "failure"},
            provenance=EvidenceProvenance(
                source="synthetic:w5-fixture", raw_message=raw,
                raw_message_ref="synthetic:w5:E2",
                sha256=hashlib.sha256(raw.encode()).hexdigest(),
                timestamp_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
                acquisition_method="authored_synthetic_fixture"))
        events = (*events, second)
        bundle = IncidentBundle.model_validate({
            **bundle.model_dump(), "evidence_ids": ["E1", "E2"]})
    return retrieve_synthetic_incident(bundle, events, query="logon")


def generated(text, source):
    return GeneratedDraft(
        "W5D1-SYN", source.bundle.incident_id, source.bundle.tenant_id,
        text, source.evidence_ids, "a" * 64, "b" * 64, "c" * 64,
        "synthetic-model", DIGEST)


class W5AtomizationTests(unittest.TestCase):
    def test_unreviewed_generated_claims_cannot_enter_w5_00_verifier(self):
        source = context()
        result = extract_generated_candidates(
            source, generated("Alice logged on [E1].", source))
        backend = RecordingBackend()
        with self.assertRaisesRegex(ValueError,
                                    "generated_claims_require_atomization_review"):
            verify_synthetic_draft(
                source, result.draft,
                SyntheticV3Verifier(DevelopmentV2(backend)))
        self.assertEqual(backend.calls, [])

    def test_saved_style_sentence_keeps_exact_span_and_citation_marker(self):
        source = context()
        text = "Actor alice logged on to host WS01 with a successful outcome [E1]."
        result = extract_generated_candidates(source, generated(text, source))
        self.assertEqual(result.status,
                         "SYNTHETIC_CANDIDATES_NOT_GOLD_NOT_VERIFIED")
        self.assertEqual(result.review_count, 1)
        claim = result.draft.claims[0]
        self.assertEqual(claim.text,
                         "Actor alice logged on to host WS01 with a successful outcome")
        self.assertEqual(text[claim.span_start:claim.span_end], claim.text)
        self.assertEqual(claim.citation_ids, ("E1",))
        self.assertEqual(text[slice(*claim.citation_marker_spans[0])], "[E1]")
        self.assertEqual(claim.evidence_ids, ("E1",))
        self.assertIn("AUTO_SEGMENTATION_UNVERIFIED", claim.review_reasons)
        self.assertEqual(result.draft.source_kind,
                         "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD")

    def test_multi_evidence_modal_and_uncertainty_claims_stay_reviewable(self):
        source = context(two_events=True)
        text = ("Alice may have logged on [E1, E2]. "
                "The evidence does not establish exfiltration.")
        result = extract_generated_candidates(source, generated(text, source))
        self.assertEqual(len(result.draft.claims), 2)
        first, second = result.draft.claims
        self.assertEqual(first.evidence_ids, source.evidence_ids)
        self.assertEqual(first.citation_ids, ("E1", "E2"))
        self.assertIn("MODALITY_REVIEW", first.review_reasons)
        self.assertEqual(second.citation_ids, ())
        self.assertIn("UNCITED_FACTUAL_CANDIDATE", second.review_reasons)
        self.assertIn("CLAIM_TYPE_REVIEW", second.review_reasons)
        self.assertIn("NEGATION_REVIEW", second.review_reasons)
        self.assertEqual(second.claim_type, "factual_candidate")
        self.assertNotEqual(first.claim_id, second.claim_id)
        self.assertEqual(result.draft.sha256,
                         extract_generated_candidates(source, generated(text, source))
                         .draft.sha256)

    def test_compound_and_semantically_unsupported_text_are_not_auto_judged(self):
        source = context()
        text = ("Alice logged on and Bob ran a tool [E1]. "
                "Record R1 reports failure [E1]. "
                "Exfiltration occurred [E1].")
        result = extract_generated_candidates(source, generated(text, source))
        self.assertEqual(len(result.draft.claims), 3)
        self.assertIn("COMPOUND_BOUNDARY_REVIEW",
                      result.draft.claims[0].review_reasons)
        self.assertTrue(all(claim.claim_type == "factual_candidate"
                            for claim in result.draft.claims))
        self.assertFalse(hasattr(result.draft.claims[1], "prediction"))
        self.assertFalse(hasattr(result.draft.claims[2], "gold_label"))

    def test_foreign_duplicate_inline_and_malformed_citations_fail_closed(self):
        source = context()
        cases = (
            ("Alice logged on [FOREIGN].", "CITATION_OUTSIDE_FIXED_EVIDENCE"),
            ("Alice logged on [E1, E1].", "DUPLICATE_CITATION_ID"),
            ("Alice [E1] logged on.", "CITATION_POSITION_UNRESOLVED"),
            ("Alice logged on [E1", "UNBALANCED_CITATION_MARKER"),
            ("Alice logged on [E1, ].", "MALFORMED_CITATION_ID"),
        )
        for text, reason in cases:
            with self.subTest(text=text), self.assertRaisesRegex(
                    AtomizationFailure, reason):
                extract_generated_candidates(source, generated(text, source))
        with self.assertRaisesRegex(AtomizationFailure,
                                    "GENERATED_DRAFT_SCOPE_MISMATCH"):
            extract_generated_candidates(
                source, replace(generated("Alice [E1].", source),
                                tenant_id="OTHER"))

    def test_create_only_archive_rebinds_w5_01_and_rejects_drift(self):
        source = context()
        config = GenerationConfig("synthetic-model", DIGEST)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "w5_01"
            second = root / "w5_02"
            generate_and_archive(source, config, FakeBackend(
                '{"draft_text":"Alice logged on [E1]."}'), first)
            result = create_claim_archive(source, config, first, second)
            checked = verify_claim_archive(source, config, first, second)
            self.assertEqual(result, checked)
            self.assertEqual(result.review_count, 1)
            with self.assertRaises(FileExistsError):
                create_claim_archive(source, config, first, second)
            with self.assertRaises(ValueError):
                verify_claim_archive(source, GenerationConfig(
                    "synthetic-model", DIGEST, seed=32), first, second)
            claims_path = second / "claims.json"
            claims_path.write_bytes(claims_path.read_bytes().replace(b"Alice", b"Bob__"))
            with self.assertRaises(ValueError):
                verify_claim_archive(source, config, first, second)


if __name__ == "__main__":
    unittest.main()
