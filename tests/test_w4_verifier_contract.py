"""W4-00 boundary checks using only the authored W3 synthetic fixture."""

import json
import unittest
from dataclasses import replace
from pathlib import Path

from egis_soc.development import (
    DevelopmentData, DevelopmentV2, NLIPair, OrderedEvidence, RuleTrace,
    VerifierInput, VerifierOutput, run_v2,
)
from egis_soc.development_retrieval import _passage
from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION


FIXTURE = Path(__file__).parent / "fixtures" / "w3_development_benchmark_v1.json"


def synthetic_input():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    section = fixture["evaluation"]
    events = tuple({
        "evidence_id": row["id"], "incident_id": section["incident_id"],
        "tenant_id": "SYNTHETIC", "source_ref": f"synthetic:{row['id']}",
        "timestamp_utc": "2026-01-01T00:00:00+00:00",
        "event_data": {"message": row["message"]},
    } for row in section["events"])
    data = DevelopmentData(section["incident_id"], "SYNTHETIC", "train",
                           "SYNTHETIC", "synthetic", None, events)
    pair_row = section["pairs"][0]
    pair = NLIPair(pair_row["id"], data.incident_id, data.tenant_id,
                   pair_row["claim"], tuple(pair_row["evidence_ids"]))
    return data, pair


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def score(self, premise, hypothesis):
        self.calls.append((premise, hypothesis))
        return (0.0, 3.0, 1.0), False


class W4VerifierContractTests(unittest.TestCase):
    def test_ordered_fixed_text_citations_and_unchanged_v2_pair(self):
        data, pair = synthetic_input()
        pair = replace(pair, evidence_ids=("EV-E2", "EV-E1"))
        request = VerifierInput.from_synthetic_data(
            data, pair, citation_ids=("EV-E1", "EV-UNKNOWN"))
        self.assertEqual(tuple(item.evidence_id for item in request.evidence), pair.evidence_ids)
        self.assertEqual(tuple(item.text for item in request.evidence),
                         tuple(_passage(data.resolve(item, incident_id=data.incident_id,
                                                     tenant_id=data.tenant_id))
                               for item in pair.evidence_ids))
        self.assertEqual(tuple(item.valid for item in request.citation_checks), (True, False))
        backend = RecordingBackend()
        result = run_v2(request, DevelopmentV2(backend))
        self.assertEqual(backend.calls, [("\n---\n".join(item.text for item in request.evidence),
                                         pair.claim)])
        self.assertEqual((result.arm, result.prediction, result.review_required),
                         ("V2", "supported", True))
        self.assertEqual((result.model_id, result.model_revision), (MODEL_ID, MODEL_REVISION))
        self.assertEqual(result.rule_trace, ())
        self.assertEqual(result.status, "SYNTHETIC_DEVELOPMENT_NOT_GOLD")

    def test_rejects_foreign_missing_duplicate_and_modified_evidence(self):
        data, pair = synthetic_input()
        for bad in (
            replace(pair, incident_id="FOREIGN"),
            replace(pair, tenant_id="FOREIGN"),
            replace(pair, evidence_ids=()),
            replace(pair, evidence_ids=("",)),
            replace(pair, evidence_ids=("EV-E1", "EV-E1")),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                VerifierInput.from_synthetic_data(data, bad)
        with self.assertRaises(KeyError):
            VerifierInput.from_synthetic_data(data, replace(pair, evidence_ids=("FOREIGN-ID",)))
        request = VerifierInput.from_synthetic_data(data, pair)
        with self.assertRaises(ValueError):
            replace(request, evidence=(replace(request.evidence[0], text="changed"),))
        with self.assertRaises(ValueError):
            replace(request, evidence=(replace(request.evidence[0], tenant_id="FOREIGN"),))
        for cited in (("",), ("EV-E1", "EV-E1")):
            with self.assertRaises(ValueError):
                VerifierInput.from_synthetic_data(data, pair, citation_ids=cited)
        foreign_event = dict(data.events[0], incident_id="FOREIGN")
        with self.assertRaises(ValueError):
            VerifierInput.from_synthetic_data(replace(data, events=(foreign_event,)), pair)

    def test_rejects_gold_bearing_inputs_and_unauthorized_partitions(self):
        data, pair = synthetic_input()
        for partition in ("validation", "test", "OOD", "train_designated_grouped"):
            with self.subTest(partition=partition), self.assertRaises(ValueError):
                VerifierInput.from_synthetic_data(replace(data, partition=partition), pair)
        with self.assertRaises(ValueError):
            VerifierInput.from_synthetic_data(data, replace(pair, gold_status="GOLD"))
        with self.assertRaises(ValueError):
            VerifierInput.from_synthetic_data(replace(data, source_dataset="PDS-01"), pair)
        for field in ("expected", "gold_label", "human_label"):
            event = dict(data.events[0])
            event["event_data"] = dict(event["event_data"], **{field: "supported"})
            with self.subTest(field=field), self.assertRaises(ValueError):
                VerifierInput.from_synthetic_data(replace(data, events=(event, *data.events[1:])), pair)

    def test_mutable_caller_event_cannot_change_fixed_v2_premise(self):
        data, pair = synthetic_input()
        request = VerifierInput.from_synthetic_data(data, pair)
        original_text = request.evidence[0].text
        data.events[0]["event_data"]["message"] = "changed after snapshot"
        backend = RecordingBackend()
        result = run_v2(request, DevelopmentV2(backend))
        self.assertEqual(result.prediction, "supported")
        self.assertEqual(backend.calls[0][0], original_text)
        self.assertNotIn("changed after snapshot", backend.calls[0][0])
        with self.assertRaises(TypeError):
            request.data.events[0]["event_data"]["message"] = "another change"

    def test_output_requires_three_labels_citation_warning_and_bounded_rule_trace(self):
        data, pair = synthetic_input()
        request = VerifierInput.from_synthetic_data(data, pair, citation_ids=("MISSING",))
        base = dict(request=request, arm="V0", prediction="insufficient",
                    review_required=True, decision_reason="NO_SUPPORT",
                    rule_trace=(RuleTrace("citation", "insufficient", (), "UNRESOLVED"),),
                    citation_checks=request.citation_checks)
        result = VerifierOutput(**base)
        self.assertFalse(result.citation_checks[0].valid)
        for update in (
            {"prediction": "needs_review"},
            {"review_required": False},
            {"citation_checks": ()},
            {"rule_trace": ()},
            {"rule_trace": (RuleTrace("r", "pass", ("OTHER",), "BAD_SCOPE"),)},
            {"nli_scores": {"entailment": 1.0}},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                VerifierOutput(**dict(base, **update))
        with self.assertRaises(ValueError):
            VerifierOutput(**dict(base, arm="V3", model_id="wrong",
                                  model_revision=MODEL_REVISION,
                                  nli_scores={"entailment": 1.0,
                                              "contradiction": 0.0, "neutral": 0.0}))
        with self.assertRaises(ValueError):
            VerifierOutput(**dict(base, rule_trace=(base["rule_trace"][0],
                                                     base["rule_trace"][0])))
        with self.assertRaises(ValueError):
            VerifierOutput(**dict(base, arm="V2", rule_trace=(),
                                  model_id=MODEL_ID, model_revision=MODEL_REVISION,
                                  nli_scores={"entailment": 1.0,
                                              "contradiction": 0.0, "neutral": 0.0}))


if __name__ == "__main__":
    unittest.main()
