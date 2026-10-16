"""Focused contract tests with synthetic identifiers and no private telemetry."""

import json
import re
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

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


def event(normalized_fields=None, **changes):
    values = {
        "evidence_id": "E001",
        "incident_id": "INC-001",
        "tenant_id": "TENANT-A",
        "normalized_fields": {} if normalized_fields is None else normalized_fields,
        "provenance": provenance(),
    }
    return EvidenceEvent(**(values | changes))


class SchemaTests(unittest.TestCase):
    def test_approved_annotation_guideline_examples(self):
        guideline = (
            Path(__file__).resolve().parents[1] / "docs" / "annotation-guidelines.md"
        ).read_text(encoding="utf-8")
        section = guideline.split("## 11. Synthetic worked examples using W1-03 contracts", 1)[1]
        section = section.split("## 12.", 1)[0]
        blocks = [json.loads(text) for text in re.findall(r"```json\s*(.*?)\s*```", section, re.S)]
        self.assertEqual(len(blocks), 6)

        incident = IncidentBundle.model_validate(blocks[0])
        events = [EvidenceEvent.model_validate(item) for item in blocks[1]]
        gold = EvaluationGoldRecord.model_validate(blocks[2])
        pairs = [EvaluationClaimEvidencePair.model_validate(item) for item in blocks[3]]
        foreign_event = EvidenceEvent.model_validate(blocks[4])
        foreign_pair = ClaimEvidencePair.model_validate(blocks[5])
        self.assertEqual((len(events), len(gold.gold_facts), len(pairs)), (3, 2, 5))
        gold.check_scope(incident)
        for item in (*events, *pairs):
            incident.check_scope(item)
        for item in (foreign_event, foreign_pair):
            with self.assertRaises(ValueError):
                incident.check_scope(item)
        for item in (*events, foreign_event):
            self.assertEqual(
                sha256(item.provenance.raw_message.encode("utf-8")).hexdigest(),
                item.provenance.sha256,
            )
            self.assertEqual(
                EvidenceEvent.model_validate_json(item.model_dump_json()).model_dump(mode="json"),
                item.model_dump(mode="json"),
            )

    def test_evidence_json_is_deeply_immutable_and_detached(self):
        source = {"outcome": "success", "nested": {"array": [1, {"flag": True}]}}
        snapshot = event(source)
        with self.assertRaises(ValidationError):
            snapshot.normalized_fields = {}
        with self.assertRaises(TypeError):
            snapshot.normalized_fields["outcome"] = "compromised"
        with self.assertRaises(TypeError):
            snapshot.normalized_fields["nested"]["array"] = []
        with self.assertRaises(AttributeError):
            snapshot.normalized_fields["nested"]["array"].append(2)
        with self.assertRaises(TypeError):
            snapshot.normalized_fields["nested"]["array"][1]["flag"] = False
        source["outcome"] = "compromised"
        source["nested"]["array"][1]["flag"] = False
        source["nested"]["array"].append(2)
        expected = {"outcome": "success", "nested": {"array": [1, {"flag": True}]}}
        self.assertEqual(snapshot.model_dump(mode="json")["normalized_fields"], expected)
        self.assertEqual(snapshot.model_copy(deep=True).model_dump(mode="json")["normalized_fields"], expected)

        dumped = snapshot.model_dump(mode="json")
        dumped["normalized_fields"]["nested"]["array"][1]["flag"] = False
        snapshot.model_dump()["normalized_fields"]["nested"]["array"].append(3)
        self.assertEqual(snapshot.model_dump(mode="json")["normalized_fields"], expected)
        self.assertEqual(json.loads(snapshot.model_dump_json())["normalized_fields"], expected)
        filtered = snapshot.model_dump(
            exclude={"normalized_fields": {"nested": {"array": True}}}
        )
        self.assertEqual(filtered["normalized_fields"], {"outcome": "success", "nested": {}})
        self.assertEqual(
            json.loads(snapshot.model_dump_json(exclude={"normalized_fields": {"outcome": True}}))[
                "normalized_fields"
            ],
            {"nested": {"array": [1, {"flag": True}]}},
        )
        with self.assertRaises(ValueError):
            snapshot.model_copy(update={"normalized_fields": {"outcome": "compromised"}})

    def test_evidence_accepts_nested_json_without_type_coercion(self):
        fields = {
            "boolean": True, "integer": 4624, "float": 1.25, "string": "ok", "null": None,
            "array": [False, 0, 0.0, "0", None, {"empty_array": [], "empty_object": {}}],
        }
        snapshot = event(fields)
        dumped = snapshot.model_dump(mode="json")["normalized_fields"]
        self.assertEqual(dumped, fields)
        self.assertIs(type(dumped["boolean"]), bool)
        self.assertIs(type(dumped["integer"]), int)
        self.assertIs(type(dumped["float"]), float)
        self.assertIs(type(dumped["array"][0]), bool)
        self.assertIs(type(dumped["array"][1]), int)
        self.assertIs(type(dumped["array"][2]), float)
        self.assertEqual(snapshot.model_dump_json(), snapshot.model_dump_json())
        self.assertEqual(
            EvidenceEvent.model_validate_json(snapshot.model_dump_json()).model_dump(mode="json"),
            snapshot.model_dump(mode="json"),
        )
        self.assertEqual(
            EvidenceEvent.model_validate(snapshot.model_dump(mode="json")).model_dump(mode="json"),
            snapshot.model_dump(mode="json"),
        )

    def test_evidence_rejects_nonfinite_numbers_at_every_depth(self):
        for invalid in (float("nan"), float("inf"), -float("inf")):
            for fields in ({"number": invalid}, {"nested": {"number": invalid}}, {"array": [0, {"number": invalid}]}):
                with self.subTest(fields=fields):
                    with self.assertRaises(ValidationError):
                        event(fields)
            with self.assertRaises(ValidationError):
                EvidenceEvent.model_validate_json(
                    event({"number": 0}).model_dump_json().replace('"number":0', f'"number":{invalid}')
                )

    def test_evidence_rejects_non_json_values_and_cycles(self):
        for invalid in ({1, 2}, b"abc", object(), (1, 2)):
            for fields in ({"value": invalid}, {"nested": [{"value": invalid}]}):
                with self.subTest(invalid=repr(invalid), fields=repr(fields)):
                    with self.assertRaises(ValidationError):
                        event(fields)
        with self.assertRaises(ValidationError):
            event({1: "non-string key"})
        with self.assertRaises(ValidationError):
            event(["not an object"])
        cycle = []
        cycle.append(cycle)
        with self.assertRaises(ValidationError):
            event({"cycle": cycle})

    def test_existing_evidence_and_reference_guards(self):
        for label in ("supported", "contradicted"):
            with self.subTest(label=label):
                with self.assertRaises(ValidationError):
                    pair(label=label, evidence_ids=[])
        with self.assertRaises(ValidationError):
            fact(evidence_ids=[])
        with self.assertRaises(ValidationError):
            pair(evidence_ids=["E001", "E001"])
        with self.assertRaises(ValidationError):
            evaluation_gold(evidence_ids=["E001", "E001"])
        with self.assertRaises(ValidationError):
            event(extra_field="unexpected")
        with self.assertRaises(ValidationError):
            provenance(extra_field="unexpected")
        with self.assertRaises(ValidationError):
            bundle(extra_field="unexpected")
        with self.assertRaises(ValueError):
            provenance().model_copy(update={"sha256": "invalid"})

    def test_timezone_offsets_normalize_to_utc(self):
        local = provenance(timestamp_utc="2026-10-12T17:00:00+07:00")
        self.assertEqual(local.timestamp_utc, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))
        self.assertEqual(local.model_dump(mode="json")["timestamp_utc"], "2026-10-12T10:00:00Z")
        with self.assertRaises(ValidationError):
            provenance(timestamp_utc="2026-10-12T10:00:00")

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
