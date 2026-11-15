"""Synthetic S1 rendering and citation-diagnostic boundaries."""

import unittest
import tempfile
from dataclasses import replace
from pathlib import Path

from egis_soc.summarization import (
    CitationAudit, S1Report, create_s1_archive, render_s1, verify_s1_archive,
)
from egis_soc.summarization.atomization import (
    create_claim_archive, extract_generated_candidates,
)
from egis_soc.summarization.contract import AtomicDraftClaim, SyntheticDraft
from egis_soc.summarization.generation import GenerationConfig, generate_and_archive
from test_w5_atomization import context, generated
from test_w5_generation import FakeBackend


class W5S1Tests(unittest.TestCase):
    def test_create_only_archive_replays_exact_sources_and_detects_drift(self):
        source = context()
        config = GenerationConfig("synthetic-model", "a" * 64)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft_path, claims_path, s1_path = (root / name for name in
                                                ("w5_01", "w5_02", "w5_03"))
            generate_and_archive(source, config, FakeBackend(
                '{"draft_text":"Alice logged on [E1]."}'), draft_path)
            create_claim_archive(source, config, draft_path, claims_path)
            report = create_s1_archive(source, config, draft_path, claims_path,
                                       s1_path)
            self.assertEqual(verify_s1_archive(source, config, draft_path,
                                               claims_path, s1_path), report)
            with self.assertRaises(FileExistsError):
                create_s1_archive(source, config, draft_path, claims_path,
                                  s1_path)
            saved = s1_path / "report.json"
            saved.write_bytes(saved.read_bytes().replace(b"Alice", b"Bob__"))
            with self.assertRaisesRegex(ValueError, "w5_03_s1_archive_drift"):
                verify_s1_archive(source, config, draft_path, claims_path,
                                  s1_path)

    def test_saved_style_s1_round_trip_preserves_text_provenance_and_pending_checks(self):
        source = context()
        result = extract_generated_candidates(source, generated(
            "Actor alice logged on to host WS01 with a successful outcome [E1].",
            source))
        claim_id = result.draft.claims[0].claim_id
        report = render_s1(source, result.draft,
                           sections={claim_id: "observed_behaviors"})
        self.assertEqual(report.original_draft_text, result.draft.text)
        self.assertEqual(report.incident_overview, result.draft.text)
        self.assertEqual(report.draft_sha256, result.draft.sha256)
        self.assertEqual(report.observed_behaviors, (claim_id,))
        self.assertEqual(report.confirmed_outcomes, ())
        self.assertEqual(report.verification_status, "NOT_RUN_S1")
        self.assertEqual(report.analyst_notes, ())
        self.assertEqual(report.evidence[0].raw_sha256,
                         source.events[0].provenance.sha256)
        self.assertEqual(report.evidence[0].raw_message,
                         source.events[0].provenance.raw_message)
        citation = report.claims[0].citations[0]
        self.assertTrue(citation.valid_in_scope)
        self.assertEqual(citation.relevance, "not_assessed")
        self.assertEqual(report.claims[0].cited_set_support, "not_assessed")
        self.assertIn("CITED_SUPPORT_NOT_ASSESSED", report.claims[0].review_reasons)
        self.assertEqual(S1Report.from_record(report.to_record()), report)
        damaged = report.to_record()
        damaged["claims"][0]["text"] = "invented"
        with self.assertRaisesRegex(ValueError, "invalid_s1_record"):
            S1Report.from_record(damaged)

    def test_extra_citation_relevance_and_cited_set_support_are_separate(self):
        source = context(two_events=True)
        result = extract_generated_candidates(source, generated(
            "Alice logged on to WS01 [E1, E2].", source))
        claim = result.draft.claims[0]
        audited = render_s1(source, result.draft, citation_audits=(
            CitationAudit(claim.claim_id, "synthetic-reviewer", "E2 is unrelated",
                          ("relevant", "irrelevant"), "insufficient"),))
        item = audited.claims[0]
        self.assertEqual(tuple(c.valid_in_scope for c in item.citations),
                         (True, True))
        self.assertEqual(tuple(c.relevance for c in item.citations),
                         ("relevant", "irrelevant"))
        self.assertEqual(item.cited_set_support, "insufficient")
        self.assertIn("IRRELEVANT_CITATION", item.review_reasons)
        self.assertIn("CITED_SET_NOT_SUPPORTED", item.review_reasons)
        self.assertEqual(item.claim_type, "factual_candidate")
        self.assertEqual(audited.verification_status, "NOT_RUN_S1")
        with self.assertRaisesRegex(ValueError, "invalid_s1_supported_citation_audit"):
            render_s1(source, result.draft, citation_audits=(
                CitationAudit(claim.claim_id, "synthetic-reviewer", "unsupported",
                              ("relevant", "irrelevant"), "supported"),))

    def test_missing_and_invalid_citations_remain_visible(self):
        source = context()
        uncited = extract_generated_candidates(source, generated(
            "Alice logged on.", source)).draft
        report = render_s1(source, uncited)
        self.assertEqual(report.claims[0].citations, ())
        self.assertIn("MISSING_CITATION", report.claims[0].review_reasons)
        text = "Alice logged on [FOREIGN]."
        claim_text = "Alice logged on"
        claim = AtomicDraftClaim(
            "C-FOREIGN", claim_text, 0, len(claim_text), source.evidence_ids,
            ("FOREIGN",), citation_marker_spans=((len(claim_text) + 1,
                                                   len(text) - 1),))
        draft = SyntheticDraft("D-FOREIGN", source.bundle.incident_id,
                               source.bundle.tenant_id, text, source.evidence_ids,
                               (claim,), generator_id="synthetic-model",
                               source_kind="SYNTHETIC_LOCAL_GENERATED_NOT_GOLD")
        invalid = render_s1(source, draft)
        self.assertFalse(invalid.claims[0].citations[0].valid_in_scope)
        self.assertIsNone(invalid.claims[0].citations[0].evidence_ref)
        self.assertIn("INVALID_CITATION", invalid.claims[0].review_reasons)
        self.assertEqual(invalid.evidence[0].evidence_id, "E1")
        with self.assertRaisesRegex(ValueError, "invalid_s1_supported_citation_audit"):
            render_s1(source, draft, citation_audits=(
                CitationAudit("C-FOREIGN", "synthetic-reviewer", "wrong scope",
                              ("relevant",), "supported"),))

    def test_asserted_outcome_with_insufficient_cited_evidence_is_not_promoted(self):
        source = context()
        draft = extract_generated_candidates(source, generated(
            "Exfiltration occurred [E1].", source)).draft
        claim_id = draft.claims[0].claim_id
        report = render_s1(
            source, draft, sections={claim_id: "confirmed_outcomes"},
            citation_audits=(CitationAudit(
                claim_id, "synthetic-reviewer", "Login record does not prove exfiltration",
                ("irrelevant",), "insufficient"),))
        self.assertEqual(report.confirmed_outcomes, (claim_id,))
        self.assertEqual(report.claims[0].text, "Exfiltration occurred")
        self.assertEqual(report.claims[0].cited_set_support, "insufficient")
        self.assertIn("CITED_SET_NOT_SUPPORTED",
                      report.claims[0].review_reasons)
        self.assertEqual(report.status, "S1_DRAFT_NOT_VERIFIED_NOT_GOLD")

    def test_scope_marker_audit_and_section_fail_closed(self):
        source = context()
        draft = extract_generated_candidates(source, generated(
            "Alice logged on [E1].", source)).draft
        claim = draft.claims[0]
        with self.assertRaisesRegex(ValueError, "s1_scope_or_source_mismatch"):
            render_s1(source, replace(draft, tenant_id="OTHER"))
        with self.assertRaisesRegex(ValueError, "s1_claim_evidence_set_mismatch"):
            render_s1(source, replace(draft, claims=(
                replace(claim, evidence_ids=("FOREIGN",)),)))
        with self.assertRaisesRegex(ValueError, "s1_citation_marker_mismatch"):
            render_s1(source, replace(draft, claims=(
                replace(claim, citation_ids=("OTHER",)),)))
        with self.assertRaisesRegex(ValueError, "invalid_s1_section_assignment"):
            render_s1(source, draft, sections={"unknown": "timeline"})
        with self.assertRaisesRegex(ValueError, "invalid_s1_citation_audit_set"):
            render_s1(source, draft, citation_audits=(
                CitationAudit("unknown", "synthetic-reviewer", "reason",
                              ("relevant",), "supported"),))


if __name__ == "__main__":
    unittest.main()
