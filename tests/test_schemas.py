"""Focused contract tests with synthetic identifiers and no private telemetry."""

import json
import unittest
from datetime import datetime, timezone
from hashlib import sha256

from pydantic import ValidationError

from egis_soc.schemas import (
    ClaimEvidencePair,
    EvaluationClaimEvidencePair,
    EvaluationGoldRecord,
    EvidenceEvent,
    EvidenceProvenance,
    GoldFact,
    IncidentBundle,
)


def provenance(**changes):
    values = {
        "source": "synthetic-log",
        "timestamp_utc": datetime(2026, 10, 12, tzinfo=timezone.utc),
        "raw_message": "synthetic event",
        "raw_message_ref": "snapshot:synthetic/E001",
        "sha256": sha256(b"synthetic event").hexdigest(),
        "acquisition_method": "test-fixture",
    }
    return EvidenceProvenance(**(values | changes))


def fact(**changes):
    values = {
        "fact_id": "F001",
        "statement": "A synthetic event was recorded",
        "criticality": "high",
        "support_status": "supported",
        "evidence_ids": ["E001"],
        "observability": "observed",
        "annotation_source": "human_reviewed",
    }
    return GoldFact(**(values | changes))


def bundle(**changes):
    values = {
        "incident_id": "INC-001",
        "tenant_id": "TENANT-A",
        "environment_id": "ENV-A",
        "source_dataset": "synthetic",
        "scenario_family": "test",
        "alert_ids": ["ALT-001"],
        "evidence_ids": ["E001"],
    }
    return IncidentBundle(**(values | changes))


def evaluation_gold(**changes):
    values = {
        "incident_id": "INC-001",
        "tenant_id": "TENANT-A",
        "evidence_ids": ["E001"],
        "gold_facts": [fact()],
    }
    return EvaluationGoldRecord(**(values | changes))


def pair(**changes):
    values = {
        "pair_id": "P001",
        "incident_id": "INC-001",
        "tenant_id": "TENANT-A",
        "claim": "A synthetic event was recorded",
        "evidence_ids": ["E001"],
        "claim_type": "observed_event",
        "label": "supported",
        "annotation_source": "human_reviewed",
        "claim_source": "generated_draft",
    }
    return ClaimEvidencePair(**(values | changes))


class SchemaTests(unittest.TestCase):
    def test_source_plan_shapes_and_utc_serialization(self):
        event = EvidenceEvent(
            evidence_id="E001", incident_id="INC-001", tenant_id="TENANT-A",
            normalized_fields={"event_code": 4624}, provenance=provenance(),
        )
        incident = bundle()
        gold = evaluation_gold()
        gold.check_scope(incident)
        incident.check_scope(event)
        incident.check_scope(pair())
        self.assertEqual(gold.gold_facts[0].support_status, "supported")
        self.assertEqual(event.provenance.timestamp_utc.utcoffset().total_seconds(), 0)
        self.assertEqual(EvidenceEvent.model_validate_json(event.model_dump_json()), event)

    def test_missing_evidence_is_insufficient_not_contradicted(self):
        incident = bundle()
        incident.check_scope(pair(label="insufficient", evidence_ids=[]))
        incident.check_scope(pair(label="contradicted"))
        self.assertEqual(pair(label="contradicted").label, "contradicted")
        with self.assertRaises(ValidationError):
            pair(label="contradicted", evidence_ids=[])
        with self.assertRaises(ValidationError):
            pair(label="unknown")

    def test_rejects_cross_incident_and_cross_tenant_references(self):
        incident = bundle()
        for invalid in (
            pair(incident_id="INC-002"),
            pair(tenant_id="TENANT-B"),
            pair(evidence_ids=["E002"]),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    incident.check_scope(invalid)
        event = EvidenceEvent(
            evidence_id="E001", incident_id="INC-001", tenant_id="TENANT-B",
            normalized_fields={}, provenance=provenance(),
        )
        with self.assertRaises(ValueError):
            incident.check_scope(event)

    def test_rejects_invalid_provenance_and_gold_references(self):
        with self.assertRaises(ValidationError):
            provenance(sha256="not-a-hash")
        with self.assertRaises(ValidationError):
            provenance(timestamp_utc=datetime(2026, 10, 12))
        with self.assertRaises(ValidationError):
            evaluation_gold(gold_facts=[fact(evidence_ids=["E002"])])
        with self.assertRaises(ValidationError):
            fact(annotation_source="generator")
        with self.assertRaises(ValidationError):
            evaluation_gold().gold_facts[0].annotation_source = "generator"
        with self.assertRaises(ValidationError):
            bundle(evidence_ids=["E001", "E001"])

    def test_inference_bundle_rejects_gold_and_evaluation_record_stays_separate(self):
        incident = bundle()
        gold = evaluation_gold()
        gold.check_scope(incident)
        self.assertNotIn("gold_facts", incident.model_dump())
        self.assertNotIn("gold_facts", incident.model_dump_json())
        self.assertEqual(gold.incident_id, incident.incident_id)
        self.assertEqual(gold.evidence_ids, incident.evidence_ids)
        with self.assertRaises(ValidationError):
            bundle(gold_facts=[fact()])
        with self.assertRaises(ValidationError):
            IncidentBundle.model_validate(gold.model_dump())
        for invalid in (
            evaluation_gold(incident_id="INC-002"),
            evaluation_gold(tenant_id="TENANT-B"),
            evaluation_gold(evidence_ids=["E002"], gold_facts=[]),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    invalid.check_scope(incident)

    def test_evaluation_gold_pair_requires_human_label_provenance_for_all_classes(self):
        for label in ("supported", "contradicted", "insufficient"):
            with self.subTest(label=label):
                candidate = pair(label=label, annotation_source="generator")
                self.assertEqual(candidate.claim_source, "generated_draft")
                with self.assertRaises(ValidationError):
                    EvaluationClaimEvidencePair.model_validate(
                        candidate.model_dump() | {"annotation_record_id": "REVIEW-001"}
                    )
                gold_pair = EvaluationClaimEvidencePair.model_validate(
                    candidate.model_dump() | {
                        "annotation_source": "human_reviewed",
                        "annotation_record_id": "REVIEW-001",
                    }
                )
                self.assertEqual(gold_pair.claim_source, "generated_draft")
                self.assertEqual(gold_pair.annotation_source, "human_reviewed")
                with self.assertRaises(ValidationError):
                    gold_pair.annotation_source = "generator"
        with self.assertRaises(ValidationError):
            EvaluationClaimEvidencePair.model_validate(pair().model_dump())
        with self.assertRaises(ValidationError):
            EvaluationClaimEvidencePair.model_validate(
                pair().model_dump() | {"annotation_record_id": " "}
            )

    def test_raw_snapshot_reference_required_and_provenance_frozen(self):
        snapshot = provenance()
        self.assertEqual(snapshot.raw_message_ref, "snapshot:synthetic/E001")
        self.assertEqual(snapshot.sha256, sha256(b"synthetic event").hexdigest())
        for bad_ref in ("", " ", "snapshot:synthetic/ E001", "snapshot:synthetic/E001\n"):
            with self.subTest(bad_ref=bad_ref):
                with self.assertRaises(ValidationError):
                    provenance(raw_message_ref=bad_ref)
        missing_ref = snapshot.model_dump()
        del missing_ref["raw_message_ref"]
        with self.assertRaises(ValidationError):
            EvidenceProvenance.model_validate(missing_ref)
        for required_field in ("source", "timestamp_utc", "raw_message", "sha256", "acquisition_method"):
            with self.subTest(required_field=required_field):
                incomplete = snapshot.model_dump()
                del incomplete[required_field]
                with self.assertRaises(ValidationError):
                    EvidenceProvenance.model_validate(incomplete)
        with self.assertRaises(ValidationError):
            snapshot.raw_message_ref = "snapshot:synthetic/E002"
        with self.assertRaises(ValidationError):
            snapshot.sha256 = "b" * 64
        event = EvidenceEvent(
            evidence_id="E001", incident_id="INC-001", tenant_id="TENANT-A",
            normalized_fields={}, provenance=snapshot,
        )
        with self.assertRaises(ValidationError):
            event.provenance = provenance(raw_message_ref="snapshot:synthetic/E002")

    def test_incident_and_pair_references_cannot_expand_after_validation(self):
        source_ids = ["E001"]
        incident = bundle(evidence_ids=source_ids)
        source_ids.append("E002")
        self.assertEqual(incident.evidence_ids, ("E001",))
        self.assertEqual(incident.alert_ids, ("ALT-001",))
        with self.assertRaises(AttributeError):
            incident.evidence_ids.append("E002")
        with self.assertRaises(ValidationError):
            incident.evidence_ids = ("E001", "E002")
        with self.assertRaises(ValueError):
            incident.model_copy(update={"evidence_ids": ("E001", "E002")})
        with self.assertRaises(AttributeError):
            incident.alert_ids.append("ALT-002")

        valid = pair()
        incident.check_scope(valid)
        self.assertEqual(valid.evidence_ids, ("E001",))
        with self.assertRaises(AttributeError):
            valid.evidence_ids.append("E002")
        with self.assertRaises(ValidationError):
            valid.evidence_ids = ("E002",)
        with self.assertRaises(ValueError):
            valid.model_copy(update={"evidence_ids": ("E002",)})
        with self.assertRaises(ValueError):
            incident.check_scope(pair(evidence_ids=["E002"]))

    def test_nested_evaluation_references_cannot_mutate_after_validation(self):
        gold = evaluation_gold()
        gold.check_scope(bundle())
        self.assertEqual(gold.evidence_ids, ("E001",))
        self.assertEqual(gold.gold_facts[0].evidence_ids, ("E001",))
        with self.assertRaises(AttributeError):
            gold.evidence_ids.append("E002")
        with self.assertRaises(AttributeError):
            gold.gold_facts.append(fact())
        with self.assertRaises(AttributeError):
            gold.gold_facts[0].evidence_ids.append("E002")
        with self.assertRaises(ValidationError):
            gold.gold_facts[0].evidence_ids = ("E001", "E002")
        with self.assertRaises(ValidationError):
            gold.evidence_ids = ("E001", "E002")
        with self.assertRaises(ValueError):
            gold.model_copy(update={"evidence_ids": ("E001", "E002")})
        with self.assertRaises(ValueError):
            gold.gold_facts[0].model_copy(update={"evidence_ids": ("E002",)})
        with self.assertRaises(ValidationError):
            evaluation_gold(gold_facts=[fact(evidence_ids=["E002"])])

    def test_reference_json_round_trip_keeps_arrays_and_scope(self):
        incident = IncidentBundle.model_validate_json(bundle().model_dump_json())
        gold = EvaluationGoldRecord.model_validate_json(evaluation_gold().model_dump_json())
        claim_pair = ClaimEvidencePair.model_validate_json(pair().model_dump_json())
        self.assertEqual(json.loads(incident.model_dump_json())["evidence_ids"], ["E001"])
        self.assertEqual(json.loads(gold.model_dump_json())["gold_facts"][0]["evidence_ids"], ["E001"])
        self.assertEqual(incident.evidence_ids, ("E001",))
        self.assertEqual(gold.gold_facts[0].evidence_ids, ("E001",))
        self.assertEqual(claim_pair.evidence_ids, ("E001",))
        gold.check_scope(incident)
        incident.check_scope(claim_pair)
        ordered = bundle(evidence_ids=["E002", "E001"])
        self.assertEqual(ordered.evidence_ids, ("E002", "E001"))
        self.assertEqual(json.loads(ordered.model_dump_json())["evidence_ids"], ["E002", "E001"])


if __name__ == "__main__":
    unittest.main()
