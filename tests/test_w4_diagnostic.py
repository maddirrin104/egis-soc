"""W4-03 synthetic matching, negative-case accounting and saved-result checks."""

import copy
import json
import unittest
from pathlib import Path

from egis_soc.development.w4_diagnostic import (
    run_fixture, validate_fixture, verify_result,
)
from egis_soc.development_v2 import DevelopmentV2


FIXTURE = Path(__file__).parent / "fixtures/w4_matched_synthetic_v1.json"


def fixture():
    return json.loads(FIXTURE.read_bytes())


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def score(self, premise, hypothesis):
        self.calls.append((premise, hypothesis))
        return (0.0, 5.0, 0.0), False


class W4DiagnosticTests(unittest.TestCase):
    def test_fixed_synthetic_population_and_one_matched_v2_call_per_case(self):
        source = fixture()
        prepared = validate_fixture(source)
        backend = RecordingBackend()
        result = run_fixture(source, v2_factory=lambda: DevelopmentV2(backend))
        verify_result(source, result)
        self.assertEqual(result["case_count"], 10)
        self.assertEqual(len(backend.calls), 10)
        self.assertEqual([row["case_id"] for row in result["cases"]],
                         [row["id"] for row in source["cases"]])
        self.assertEqual(result["summary"]["v2_v3_identical_score_count"], 10)
        self.assertEqual(result["cases"][2]["evidence_ids_ordered"],
                         ["W4-E03B", "W4-E03A"])
        self.assertEqual(backend.calls[2], (
            "\n---\n".join(item.text for item in prepared[2][0].evidence),
            prepared[2][0].pair.claim))
        self.assertEqual(prepared[0][0].pair.gold_status, "NOT_GOLD")
        self.assertNotIn("expected", prepared[0][0].data.events[0]["event_data"])
        self.assertEqual(result["real_pilot_metric"],
                         "NOT_RUN_NO_ACCEPTED_HUMAN_GOLD_PILOT")

    def test_negative_cases_and_citation_warning_are_recorded_separately(self):
        result = run_fixture(fixture(), v2_factory=lambda: DevelopmentV2(RecordingBackend()))
        by_id = {row["case_id"]: row for row in result["cases"]}
        self.assertEqual(by_id["W4-C02"]["arms"]["V0"]["prediction"], "contradicted")
        self.assertEqual(by_id["W4-C02"]["arms"]["V3"]["prediction"], "contradicted")
        self.assertEqual(by_id["W4-C04"]["arms"]["V0"]["prediction"], "insufficient")
        self.assertEqual(by_id["W4-C05"]["arms"]["V0"]["prediction"], "insufficient")
        self.assertEqual(by_id["W4-C06"]["arms"]["V0"]["prediction"], "supported")
        self.assertTrue(by_id["W4-C06"]["arms"]["V0"]["review_required"])
        self.assertEqual(by_id["W4-C06"]["arms"]["V0"]["rule_trace"][0]["reason"],
                         "IRRELEVANT_CITATION")
        self.assertEqual(by_id["W4-C08"]["arms"]["V0"]["prediction"], "insufficient")
        self.assertEqual(by_id["W4-C09"]["arms"]["V0"]["prediction"], "contradicted")
        self.assertGreater(result["summary"]["arms"]["V2"]["error_counts"].get(
            "INSUFFICIENT_AS_SUPPORTED", 0), 0)

    def test_fixture_rejects_weak_truth_scope_changes_and_gold_fields(self):
        source = fixture()
        variants = []
        for field, value in (("label_provenance", "AI_REVIEWED_DEV"),
                             ("partition", "test"), ("lineage_group", "PDS01_ALL")):
            changed = copy.deepcopy(source)
            changed[field] = value
            variants.append(changed)
        foreign = copy.deepcopy(source)
        foreign["cases"][0]["evidence_ids"] = ["W4-E02"]
        variants.append(foreign)
        duplicate = copy.deepcopy(source)
        duplicate["cases"][1]["id"] = "W4-C01"
        variants.append(duplicate)
        gold = copy.deepcopy(source)
        gold["cases"][0]["events"][0]["event_data"]["gold_label"] = "supported"
        variants.append(gold)
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_fixture(changed)

    def test_saved_case_metric_and_parity_tampering_fail(self):
        source = fixture()
        result = run_fixture(source, v2_factory=lambda: DevelopmentV2(RecordingBackend()))
        for mutation in (
            lambda row: row["cases"][0].update(expected="insufficient"),
            lambda row: row["cases"][2].update(evidence_ids_ordered=["W4-E03A", "W4-E03B"]),
            lambda row: row["cases"][0]["arms"]["V3"]["nli_scores"].update(
                entailment=0.1),
            lambda row: row["summary"]["arms"]["V3"].update(review_count=0),
            lambda row: row["cases"][1]["errors"].update(V0="FALSE_SUPPORTED"),
        ):
            tampered = copy.deepcopy(result)
            mutation(tampered)
            with self.assertRaises(ValueError):
                verify_result(source, tampered)


if __name__ == "__main__":
    unittest.main()
