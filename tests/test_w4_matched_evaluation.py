"""Synthetic matched scoring and failure-boundary tests for W4 preparation."""

import json
import unittest
from dataclasses import replace
from pathlib import Path

from egis_soc.development import DevelopmentV2, SyntheticV3Verifier, VerifierInput
from egis_soc.development.matched_evaluation import (
    ArmAttempt, MatchedRow, run_synthetic_matched, score_matched,
    synthetic_run_report,
)
from egis_soc.development.w4_diagnostic import validate_fixture

from test_w4_rules import FULL, request_for


class SequencedBackend:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def score(self, premise, hypothesis):
        self.calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def case(pair_id, body=FULL, *, claim=None):
    request = request_for(body, **({} if claim is None else {"claim": claim}))
    pair = replace(request.pair, pair_id=pair_id)
    return VerifierInput.from_synthetic_data(request.data, pair,
                                             citation_ids=request.citation_ids)


class MissingV3(SyntheticV3Verifier):
    def compare(self, request):
        v2, _ = super().compare(request)
        return v2, None


class ForeignV3(SyntheticV3Verifier):
    def __init__(self, nli, foreign):
        super().__init__(nli)
        self.foreign = foreign

    def compare(self, request):
        v2, v3 = super().compare(request)
        return v2, replace(v3, request=self.foreign)


class W4MatchedEvaluationTests(unittest.TestCase):
    def test_existing_authored_fixture_runs_through_matched_interface(self):
        path = Path(__file__).parent / "fixtures/w4_matched_synthetic_v1.json"
        prepared = validate_fixture(json.loads(path.read_bytes()))
        backend = SequencedBackend([((0.0, 5.0, 0.0), False)] * len(prepared))
        report = synthetic_run_report(
            prepared, SyntheticV3Verifier(DevelopmentV2(backend)))
        self.assertEqual(report["evaluation"]["case_count"], 10)
        self.assertEqual(backend.calls, 10)
        self.assertEqual(report["evaluation"]["pair_ids"],
                         [request.pair.pair_id for request, _ in prepared])
        self.assertEqual(report["evaluation"]["gold_provenance"],
                         "SYNTHETIC_KNOWN_ANSWER")

    def test_fixed_pairs_share_one_nli_call_and_report_protocol_denominators(self):
        backend = SequencedBackend([((0.0, 5.0, 0.0), False)] * 3)
        verifier = SyntheticV3Verifier(DevelopmentV2(backend))
        cases = ((case("S"), "supported"),
                 (case("C", dict(FULL, outcome="failure")), "contradicted"),
                 (case("I", dict(FULL, outcome="failure", actor="bob")),
                  "insufficient"))
        rows = run_synthetic_matched(cases, verifier)
        report = score_matched(rows)
        self.assertEqual(backend.calls, 3)
        self.assertEqual([row.pair_id for row in rows], ["S", "C", "I"])
        self.assertEqual(len({row.input_sha256 for row in rows}), 3)
        self.assertEqual(report["case_count"], 3)
        self.assertEqual(report["arms"]["V3"]["confusion_matrix"]
                         ["contradicted"]["contradicted"], 1)
        self.assertEqual(report["arms"]["V2"]["false_support_numerator"], 2)
        self.assertEqual(report["arms"]["V2"]["false_support_denominator_proposed"], 2)
        self.assertEqual(report["arms"]["V2"]["false_support_rate_proposed"], 1.0)
        self.assertEqual(report["rule_coverage"]["entity"]["denominator"], 3)
        self.assertEqual(report["rule_coverage"]["entity"]["contradiction_trigger_count"], 1)
        self.assertIsNone(report["rule_coverage"]["entity"]["false_trigger_count"])
        self.assertFalse(report["confirmatory_eligible"])
        self.assertEqual(set(report["input_sha256_by_pair"]), {"S", "C", "I"})
        self.assertEqual(report["per_incident"]["SYN-W4"]["attempted_pairs"], 3)
        self.assertEqual(report["case_diagnostics"][1]["arms"]["V3"]["prediction"],
                         "contradicted")
        self.assertEqual(len(report["case_diagnostics"][1]["v3_rule_trace"]), 4)
        metadata = synthetic_run_report(
            ((case("META"), "supported"),),
            SyntheticV3Verifier(DevelopmentV2(SequencedBackend([
                ((0.0, 5.0, 0.0), False)]))))
        self.assertEqual(metadata["policy_calibration_status"],
                         "SYNTHETIC_PREDECLARED_UNCALIBRATED")
        self.assertEqual(metadata["real_pilot_metric"],
                         "NOT_RUN_NO_ACCEPTED_HUMAN_GOLD_PILOT")

    def test_zero_denominators_are_na_instead_of_favorable_values(self):
        attempt = ArmAttempt("insufficient", True, "RULES_UNRESOLVED")
        row = MatchedRow("P", "SYN-I", "supported", "0" * 64,
                         attempt, attempt)
        report = score_matched((row,))
        for arm in ("V2", "V3"):
            metrics = report["arms"][arm]
            self.assertIsNone(metrics["macro_f1"])
            self.assertIsNone(metrics["supported_precision"])
            self.assertIsNone(metrics["false_support_rate_proposed"])
            self.assertEqual(metrics["supported_recall"], 0.0)
            self.assertEqual(metrics["supported_precision_denominator"], 0)
            self.assertEqual(metrics["false_support_denominator_proposed"], 0)

    def test_timeout_and_backend_error_keep_both_arms_in_population(self):
        backend = SequencedBackend([TimeoutError("private detail"),
                                    RuntimeError("private detail")])
        cases = ((case("T"), "supported"), (case("E"), "contradicted"))
        rows = run_synthetic_matched(cases, SyntheticV3Verifier(DevelopmentV2(backend)))
        report = score_matched(rows)
        self.assertEqual(backend.calls, 2)
        self.assertEqual(report["case_count"], 2)
        for arm in ("V2", "V3"):
            self.assertEqual(report["arms"][arm]["failure_tags"],
                             {"INFERENCE_ERROR": 1, "TIMEOUT": 1})
            self.assertEqual(report["arms"][arm]["review_rate"], 1.0)
            self.assertEqual(report["arms"][arm]["failure_rate"], 1.0)
        self.assertTrue(all(row.v2.prediction == row.v3.prediction == "insufficient"
                            for row in rows))
        self.assertNotIn("private detail", str(report))

    def test_missing_arm_falls_back_without_discarding_matched_pair(self):
        backend = SequencedBackend([((0.0, 5.0, 0.0), False)])
        rows = run_synthetic_matched(((case("P"), "supported"),),
                                     MissingV3(DevelopmentV2(backend)))
        self.assertEqual(rows[0].v2.prediction, "supported")
        self.assertEqual((rows[0].v3.prediction, rows[0].v3.review_required,
                          rows[0].v3.failure_tag),
                         ("insufficient", True, "MISSING_OUTPUT"))
        self.assertEqual(score_matched(rows)["arms"]["V3"]["failure_count"], 1)
        self.assertEqual(score_matched(rows)["case_diagnostics"][0]["arms"]["V3"]
                         ["failure_tag"], "MISSING_OUTPUT")

    def test_scope_mismatch_weak_truth_and_invalid_fallback_fail_closed(self):
        first, second = case("A"), case("B")
        backend = SequencedBackend([((0.0, 5.0, 0.0), False)])
        with self.assertRaises(ValueError):
            run_synthetic_matched(((first, "supported"),),
                                  ForeignV3(DevelopmentV2(backend), second))
        with self.assertRaises(ValueError):
            run_synthetic_matched(((first, "supported"), (first, "supported")),
                                  SyntheticV3Verifier(DevelopmentV2(SequencedBackend([]))))
        with self.assertRaises(ValueError):
            MatchedRow("P", "SYN-I", "supported", "0" * 64,
                       ArmAttempt("supported", False, "OK"),
                       ArmAttempt("supported", False, "OK"),
                       gold_provenance="AI_REVIEWED_DEV")
        with self.assertRaises(ValueError):
            ArmAttempt("supported", False, "TIMEOUT", failure_tag="TIMEOUT")


if __name__ == "__main__":
    unittest.main()
