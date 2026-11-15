"""W5-00 authored synthetic incident fixture and stage-boundary tests."""

import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from egis_soc.development_v2 import DevelopmentV2
from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, IncidentBundle
from egis_soc.summarization import (
    AtomicDraftClaim, RetrievedIncident, SyntheticDraft, retrieve_synthetic_incident,
    verify_synthetic_draft,
)


STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLAIM = (
    "record=R1; event=logon; actor=alice; host=WS01; "
    "time=2026-01-01T00:00:00+00:00; outcome=success"
)


def synthetic_incident(*, fields=None, incident_id="SYN-W5", tenant_id="SYN-T"):
    """Fully synthetic W1 fixture with an actual digest of its authored raw text."""
    raw = "synthetic record R1: alice logon success on WS01"
    provenance = EvidenceProvenance(
        source="synthetic:w5-fixture", timestamp_utc=STAMP, raw_message=raw,
        raw_message_ref="synthetic:w5:E1",
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        acquisition_method="authored_synthetic_fixture",
    )
    event = EvidenceEvent(
        evidence_id="E1", incident_id=incident_id, tenant_id=tenant_id,
        normalized_fields=fields or {
            "record_ref": "R1", "event_type": "logon", "actor": "alice",
            "host": "WS01", "outcome": "success",
        },
        provenance=provenance,
    )
    bundle = IncidentBundle(
        incident_id="SYN-W5", tenant_id="SYN-T",
        environment_id="SYNTHETIC", source_dataset="synthetic",
        scenario_family="authored_w5_fixture", alert_ids=("SYN-A1",),
        evidence_ids=("E1",),
    )
    return bundle, (event,)


def authored_draft(*, evidence_ids=("E1",), citation_ids=("E1",),
                   incident_id="SYN-W5", tenant_id="SYN-T"):
    claim = AtomicDraftClaim("C1", CLAIM, 0, len(CLAIM), evidence_ids,
                             citation_ids)
    return SyntheticDraft("D1", incident_id, tenant_id, CLAIM,
                          ("E1",), (claim,))


class RecordingBackend:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def score(self, premise, hypothesis):
        self.calls.append((premise, hypothesis))
        if self.failure is not None:
            raise self.failure
        return (0.0, 5.0, 0.0), False


class W5ContractTests(unittest.TestCase):
    def test_retrieval_to_authored_draft_v3_and_structured_output(self):
        bundle, events = synthetic_incident()
        context = retrieve_synthetic_incident(bundle, events, query="logon")
        self.assertEqual(context.evidence_ids, ("E1",))
        self.assertEqual(context.hits[0].provenance["raw_sha256"],
                         events[0].provenance.sha256)
        draft = authored_draft()
        frozen_hash = draft.sha256
        backend = RecordingBackend()
        report = verify_synthetic_draft(
            context, draft, SyntheticV3Verifier(DevelopmentV2(backend)))
        self.assertEqual(report.status, "SYNTHETIC_DRAFT_VERIFICATION_NOT_FINAL")
        self.assertEqual(report.draft_sha256, frozen_hash)
        self.assertEqual(report.retrieved_evidence_ids, ("E1",))
        self.assertEqual((report.claims[0].prediction,
                          report.claims[0].review_required), ("supported", False))
        self.assertEqual(len(report.claims[0].rule_trace), 4)
        self.assertEqual(report.claims[0].verifier_output.arm, "V3")
        self.assertEqual(report.claims[0].citation_checks[0].evidence_id, "E1")
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(backend.calls[0][1], CLAIM)
        self.assertNotIn("gold", backend.calls[0][0].casefold())

    def test_invalid_claim_ids_spans_and_references_fail_before_model(self):
        with self.assertRaises(ValueError):
            AtomicDraftClaim("C1", CLAIM, 0, len(CLAIM), ())
        with self.assertRaises(ValueError):
            SyntheticDraft("D1", "SYN-W5", "SYN-T", CLAIM, ("E1",),
                           (AtomicDraftClaim("C1", CLAIM, 1, len(CLAIM), ("E1",)),))
        bundle, events = synthetic_incident()
        context = retrieve_synthetic_incident(bundle, events, query="logon")
        backend = RecordingBackend()
        verifier = SyntheticV3Verifier(DevelopmentV2(backend))
        for draft in (authored_draft(evidence_ids=("FOREIGN",)),
                      authored_draft(citation_ids=("FOREIGN",)),
                      authored_draft(incident_id="OTHER")):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                verify_synthetic_draft(context, draft, verifier)
        self.assertEqual(backend.calls, [])

    def test_cross_incident_and_missing_retrieval_fail_closed(self):
        bundle, events = synthetic_incident(incident_id="OTHER")
        with self.assertRaises(ValueError):
            retrieve_synthetic_incident(bundle, events, query="logon")
        bundle, events = synthetic_incident(tenant_id="OTHER")
        with self.assertRaises(ValueError):
            retrieve_synthetic_incident(bundle, events, query="logon")
        bundle, events = synthetic_incident()
        with self.assertRaisesRegex(ValueError, "no_retrieved_evidence"):
            retrieve_synthetic_incident(bundle, events, query="missingkeyword")

    def test_retrieval_passage_and_w3_view_cannot_drift_from_w1_evidence(self):
        bundle, events = synthetic_incident()
        context = retrieve_synthetic_incident(bundle, events, query="logon")
        with self.assertRaises(ValueError):
            RetrievedIncident(context.bundle, context.data, context.events,
                              context.query,
                              (replace(context.hits[0], passage="forged"),))
        altered = dict(context.data.events[0])
        altered["event_data"] = dict(altered["event_data"], outcome="failure")
        with self.assertRaises(ValueError):
            RetrievedIncident(context.bundle,
                              replace(context.data, events=(altered,)),
                              context.events, context.query, context.hits)

    def test_gold_and_verifier_fields_cannot_enter_inference_input(self):
        for fields in (
            {"event_type": "logon", "gold_label": "supported"},
            {"event_type": "logon", "nested": {"human_label": "supported"}},
            {"event_type": "logon", "annotation_source": "AI_REVIEWED_DEV"},
            {"event_type": "logon", "verifier_output": "supported"},
        ):
            with self.subTest(fields=fields):
                bundle, events = synthetic_incident(fields=fields)
                with self.assertRaisesRegex(ValueError,
                                            "evaluation_field_in_inference_evidence"):
                    retrieve_synthetic_incident(bundle, events, query="logon")
        bundle, events = synthetic_incident()
        with self.assertRaises(ValueError):
            retrieve_synthetic_incident(events[0], events, query="logon")

    def test_no_citation_routes_review_and_backend_error_is_explicit(self):
        bundle, events = synthetic_incident()
        context = retrieve_synthetic_incident(bundle, events, query="logon")
        no_citation = verify_synthetic_draft(
            context, authored_draft(citation_ids=()),
            SyntheticV3Verifier(DevelopmentV2(RecordingBackend())))
        self.assertEqual(no_citation.claims[0].prediction, "supported")
        self.assertTrue(no_citation.claims[0].review_required)
        self.assertEqual(no_citation.claims[0].rule_trace[0].reason, "NO_CITATION")
        failed = verify_synthetic_draft(
            context, authored_draft(), SyntheticV3Verifier(
                DevelopmentV2(RecordingBackend(RuntimeError("private detail")))))
        self.assertEqual((failed.claims[0].prediction,
                          failed.claims[0].review_required,
                          failed.claims[0].failure_tag),
                         ("insufficient", True, "VERIFIER_FAILURE"))
        self.assertIsNone(failed.claims[0].verifier_output)
        self.assertNotIn("private detail", str(failed))


if __name__ == "__main__":
    unittest.main()
