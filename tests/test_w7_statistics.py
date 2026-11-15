"""Synthetic-only W7 metric, bootstrap, calibration and gate tests."""

import hashlib
import unittest
from dataclasses import dataclass

from egis_soc.development.matched_evaluation import ArmAttempt, MatchedRow
from egis_soc.w7.agreement import InitialJudgment, score_agreement
from egis_soc.w7.bootstrap import bootstrap_intervals, rq1_endpoints, rq2_endpoints, rq3_endpoints
from egis_soc.w7.count_cache import (cache_pairs, cache_summaries, cached_rq1_endpoints,
                                      cached_rq2_endpoints, cached_rq3_endpoints)
from egis_soc.w7.calibration import (Scenario, exact_binomial_bounds, population_truth,
                                     rq3_population_truth, run_smoke, synthetic_pair_generator,
                                     synthetic_rq3_generator, synthetic_summary_generator)
from egis_soc.w7.metrics import (PairUnit, RepairDiagnostics, SummaryClaim, SummaryFact, SummaryIncident,
                                 rq1_differences, rq3_drops, score_pairs, score_summaries)
from egis_soc.w7.readiness import GATES, check_readiness


def pair(name, gold, v2, v3, *, cluster="C1", environment="SYN_A", failure=None):
    def attempt(prediction, tag=None):
        return ArmAttempt(prediction, tag is not None, tag or "SYNTHETIC",
                          tag)
    return PairUnit(MatchedRow(name, f"SYN-I-{cluster}", gold,
                               hashlib.sha256(name.encode()).hexdigest(),
                               attempt(v2), attempt(v3, failure)), cluster, environment)


def summary(name="SYN-I", cluster="C1", *, s2_status="VALID", s3_status="VALID"):
    facts = (SummaryFact("F1", "synthetic:e1", True, False, s3_status == "VALID"),
             SummaryFact("F2", "synthetic:e2", True, s2_status == "VALID",
                         s3_status == "VALID"))
    supported = SummaryClaim("C1", "A login occurred", "supported", (True,), (True,), True)
    unsupported = SummaryClaim("C2", "An unsupported impact occurred", "insufficient",
                               unsupported_s2_predecessor=False)
    return SummaryIncident(name, cluster, "a" * 64, "a" * 64, s2_status, s3_status,
                           facts, (supported,) if s2_status == "VALID" else (),
                           (supported, unsupported) if s3_status == "VALID" else (),
                           7 if s2_status == "VALID" else None,
                           12 if s3_status == "VALID" else None)


class W7MetricTests(unittest.TestCase):
    def test_pooled_three_class_and_failure_population(self):
        units = (pair("S", "supported", "supported", "supported"),
                 pair("C", "contradicted", "supported", "contradicted"),
                 pair("I", "insufficient", "insufficient", "insufficient", failure="MISSING_OUTPUT"))
        report = score_pairs(units)
        self.assertAlmostEqual(report["arms"]["V2"]["macro_f1"], (2 / 3 + 0 + 1) / 3)
        self.assertEqual(report["arms"]["V2"]["supported_precision_metric"]["value"], .5)
        self.assertEqual(report["arms"]["V2"]["false_support_rate_metric"],
                         {"value": .5, "numerator": 1, "denominator": 2, "na_reason": None})
        self.assertEqual(report["arms"]["V3"]["failure_count"], 1)
        self.assertEqual(report["attempted_pairs"], 3)
        self.assertAlmostEqual(rq1_differences(units)["delta_macro_f1"], 1 - (2 / 3 + 1) / 3)

    def test_na_missing_classes_zero_predicted_s_and_rq3_separation(self):
        lone = (pair("P", "supported", "insufficient", "insufficient"),)
        score = score_pairs(lone)["arms"]["V3"]
        self.assertIsNone(score["macro_f1_metric"]["value"])
        self.assertEqual(score["macro_f1_metric"]["na_reason"], "ABSENT_CLASS")
        self.assertEqual(score["supported_precision_metric"]["na_reason"], "NO_PREDICTED_SUPPORTED")
        self.assertEqual(score["false_support_rate_metric"]["denominator"], 0)
        a = (pair("A1", "supported", "supported", "supported", cluster="A1"),
             pair("A2", "contradicted", "contradicted", "contradicted", cluster="A2"),
             pair("A3", "insufficient", "insufficient", "insufficient", cluster="A3"))
        b = (pair("B1", "supported", "insufficient", "supported", cluster="B1", environment="SYN_B"),
             pair("B2", "contradicted", "supported", "contradicted", cluster="B2", environment="SYN_B"),
             pair("B3", "insufficient", "insufficient", "insufficient", cluster="B3", environment="SYN_B"))
        outcome = rq3_drops(a, b)
        self.assertEqual(outcome["scope"], "SYNTHETIC_NOT_INDEPENDENT_OOD")
        self.assertGreater(outcome["advantages"]["macro_f1"], 0)
        self.assertEqual(outcome["b_fsr"]["V2"]["denominator"], 2)
        self.assertIn("SYN_UNSPECIFIED_FAMILY",
                      outcome["environments"]["B"]["per_source_family"])
        self.assertEqual(rq3_endpoints(a + b)["advantage_macro_f1"], outcome["advantages"]["macro_f1"])
        with self.assertRaisesRegex(ValueError, "cross_environment_lineage_overlap"):
            rq3_drops(a, (pair("B4", "supported", "supported", "supported",
                               cluster="A1", environment="SYN_B"),))

    def test_summary_pooled_rates_empty_failure_and_fork(self):
        result = score_summaries((summary(),))
        self.assertEqual(result["arms"]["S2"]["cfr"]["value"], .5)
        self.assertEqual(result["arms"]["S3"]["cfr"]["value"], 1.0)
        self.assertEqual(result["arms"]["S3"]["ucr"]["value"], .5)
        self.assertEqual(result["arms"]["S3"]["uncited_claim_count"], 1)
        self.assertEqual(result["arms"]["S3"]["introduced_unsupported_count"], 1)
        self.assertEqual(result["delta_cfr"], .5)
        self.assertEqual(result["delta_ucr"], .5)
        self.assertEqual(result["approved_methodological_ucr_margin"], .03)
        self.assertEqual(result["per_incident"]["SYN-I"]["arms"]["S2"]["cfr"]["value"], .5)
        empty = score_summaries((summary(s2_status="EMPTY"),))
        self.assertEqual(empty["arms"]["S2"]["cfr"]["value"], 0)
        self.assertEqual(empty["arms"]["S2"]["ucr"]["na_reason"], "NO_FACTUAL_CLAIMS")
        self.assertTrue(empty["blocking_empty_or_failed"])
        failed = score_summaries((summary(s3_status="FAILED"),))
        self.assertEqual(failed["arms"]["S3"]["failed_incidents"], 1)
        self.assertIsNone(failed["arms"]["S3"]["cfr"]["value"])
        with self.assertRaisesRegex(ValueError, "invalid_synthetic_summary_incident"):
            SummaryIncident("I", "C", "a" * 64, "b" * 64, "VALID", "VALID", (), (), ())

    def test_zero_gold_facts_pooled_vs_incident_and_predecessor_occurrences(self):
        no_facts = SummaryIncident("NO-FACTS", "C2", "a" * 64, "a" * 64,
                                   "VALID", "VALID", (), (), ())
        missing = score_summaries((no_facts,))
        self.assertEqual(missing["arms"]["S2"]["cfr"]["na_reason"],
                         "NO_ELIGIBLE_CRITICAL_FACTS")
        additional = SummaryIncident("SYN-I2", "C2", "a" * 64, "a" * 64,
                                     "VALID", "VALID",
                                     (SummaryFact("F3", "synthetic:e3", True, True, True),),
                                     (SummaryClaim("C3", "Supported event", "supported"),),
                                     (SummaryClaim("C3", "Supported event", "supported"),))
        pooled = score_summaries((summary(), additional))
        self.assertAlmostEqual(pooled["arms"]["S2"]["cfr"]["value"], 2 / 3)
        self.assertNotEqual(pooled["arms"]["S2"]["cfr"]["value"],
                            (pooled["per_incident"]["SYN-I"]["arms"]["S2"]["cfr"]["value"]
                             + pooled["per_incident"]["SYN-I2"]["arms"]["S2"]["cfr"]["value"]) / 2)
        previous = SummaryClaim("U0", "Same unsupported assertion", "insufficient")
        repeated = (SummaryClaim("U1", "Same unsupported assertion", "insufficient",
                                 unsupported_s2_predecessor=True),
                    SummaryClaim("U2", "Equivalent repeated assertion", "insufficient",
                                 unsupported_s2_predecessor=True))
        duplicate_case = SummaryIncident("SYN-DUP", "C3", "a" * 64, "a" * 64,
                                         "VALID", "VALID", (), (previous,), repeated)
        duplicate_score = score_summaries((duplicate_case,))
        self.assertEqual(duplicate_score["arms"]["S3"]["factual_claim_count"], 2)
        self.assertEqual(duplicate_score["arms"]["S3"]["unsupported_count"], 2)
        self.assertEqual(duplicate_score["arms"]["S3"]["introduced_unsupported_count"], 0)

    def test_source_family_breakdown_and_repair_diagnostics(self):
        first = pair("P1", "supported", "supported", "supported", cluster="A")
        second = PairUnit(pair("P2", "contradicted", "supported", "contradicted",
                               cluster="B").row, "B", "SYN_A", "SYN_FAMILY_B",
                          "SYN_COLLECTION_B")
        result = score_pairs((first, second))
        self.assertEqual(result["per_source_family"]["SYN_FAMILY_B"]["attempted_pairs"], 1)
        self.assertEqual(result["per_source_collection"]["SYN_COLLECTION_B"]["arms"]["V2"]
                         ["false_support_numerator"], 1)
        s = summary()
        from dataclasses import replace
        s = replace(s, s3_repair=RepairDiagnostics(1, 2, 1, 1, "SYNTHETIC_REVIEW"))
        report = score_summaries((s,))
        self.assertEqual(report["arms"]["S3"]["repair_diagnostics"]["verified_actions"], 1)
        self.assertEqual(report["per_incident"]["SYN-I"]["s3_repair"]["rounds"], 1)
        self.assertIsNone(score_summaries((summary(),))["arms"]["S3"]
                          ["repair_diagnostics"]["rounds"])


@dataclass(frozen=True)
class Tiny:
    lineage_component: str
    value: int


class W7BootstrapTests(unittest.TestCase):
    def test_complete_components_and_deterministic_seed(self):
        units = tuple(Tiny(f"C{i}", i % 2) for i in range(10) for _ in range(2))
        seen = []
        def evaluator(rows):
            counts = {c: sum(row.lineage_component == c for row in rows)
                      for c in {row.lineage_component for row in rows}}
            self.assertTrue(all(n % 2 == 0 for n in counts.values()))
            seen.append(len(rows))
            return {"x": sum(row.value for row in rows) / len(rows)}
        first = bootstrap_intervals(units, evaluator=evaluator, methods={"x": "two_sided"},
                                    repetitions=50, seed=8)
        second = bootstrap_intervals(units, evaluator=evaluator, methods={"x": "two_sided"},
                                     repetitions=50, seed=8)
        self.assertEqual(first, second)
        self.assertEqual(set(seen), {20})
        self.assertEqual(first["endpoints"]["x"]["status"], "EXPLORATORY_INTERVAL")
        self.assertEqual(first["cluster_counts"], {"single": 10})

    def test_invalid_replicates_and_cluster_minimum(self):
        units = tuple(Tiny(f"C{i}", i % 2) for i in range(10))
        result = bootstrap_intervals(units, evaluator=lambda rows: {"x": None},
                                     methods={"x": "lower"}, repetitions=20, seed=1)
        self.assertEqual(result["endpoints"]["x"]["na_reason"], "UNDEFINED_OBSERVED")
        self.assertEqual(result["endpoints"]["x"]["invalid_replicates"], 20)
        few = bootstrap_intervals(units[:9], evaluator=lambda rows: {"x": 0.5},
                                  methods={"x": "upper"}, repetitions=10)
        self.assertEqual(few["endpoints"]["x"]["na_reason"],
                         "FEWER_THAN_10_INDEPENDENT_COMPONENTS")
        rare = tuple(Tiny(f"C{i}", int(i == 0)) for i in range(10))
        unstable = bootstrap_intervals(
            rare, evaluator=lambda rows: {"x": (sum(row.value for row in rows) / len(rows)
                                               if any(row.value for row in rows) else None)},
            methods={"x": "two_sided"}, repetitions=100, seed=3)
        self.assertEqual(unstable["endpoints"]["x"]["na_reason"],
                         "INVALID_REPLICATES_AT_LEAST_5_PERCENT")
        with self.assertRaisesRegex(ValueError, "component_crosses_strata"):
            bootstrap_intervals((Tiny("C", 1), Tiny("C", 0)),
                                evaluator=lambda rows: {"x": 0.0}, methods={"x": "two_sided"},
                                stratum_of=lambda row: str(row.value))

    def test_rq1_and_rq2_adapters_keep_paired_counts(self):
        units = tuple(pair(f"P{i}", ("supported", "contradicted", "insufficient")[i % 3],
                           "supported", "insufficient", cluster=f"C{i}") for i in range(10))
        self.assertEqual(set(rq1_endpoints(units)),
                         {"delta_macro_f1", "delta_supported_precision", "fsr_reduction"})
        self.assertEqual(cached_rq1_endpoints(cache_pairs(units)), rq1_endpoints(units))
        summaries = tuple(summary(f"I{i}", f"C{i}") for i in range(10))
        self.assertEqual(rq2_endpoints(summaries)["delta_cfr"], .5)
        self.assertEqual(cached_rq2_endpoints(cache_summaries(summaries)), rq2_endpoints(summaries))
        result = bootstrap_intervals(summaries, evaluator=rq2_endpoints,
                                     methods={"delta_cfr": "lower", "delta_ucr": "upper"},
                                     repetitions=20, seed=4)
        self.assertEqual(result["endpoints"]["delta_cfr"]["status"], "EXPLORATORY_INTERVAL")


class W7CalibrationTests(unittest.TestCase):
    def test_exact_bounds_and_smoke_budget(self):
        self.assertAlmostEqual(exact_binomial_bounds(0, 10)["upper"], 1 - .05**(.1))
        self.assertAlmostEqual(exact_binomial_bounds(10, 10)["lower"], .05**(.1))
        gen = synthetic_pair_generator(clusters=10, pairs_per_cluster=5,
                                       prevalence=(.5, .25, .25), v2_error=.3, v3_error=.2)
        truth = population_truth(prevalence=(.5, .25, .25), v2_error=.3, v3_error=.2)
        scenario = Scenario("synthetic_smoke", "RQ1", truth,
                            {name: "two_sided" for name in truth}, "TRUE_H1",
                            {"clusters": 10, "pairs_per_cluster": 5})
        with self.assertRaisesRegex(ValueError, "invalid_calibration_scenario"):
            Scenario("missing_endpoint", "RQ1", {"delta_macro_f1": 0.1},
                     {"delta_macro_f1": "two_sided"}, "TRUE_H1", {})
        run = run_smoke(scenario, generator=gen, evaluator=rq1_endpoints,
                        outer=2, inner=12, seed=9)
        self.assertEqual(run["calibration_gate"], "NOT_RUN_NO_SCENARIO_LOCK")
        self.assertEqual(run["official_work_estimate"]["count_reaggregations_per_scenario"],
                         10_000_000)
        self.assertEqual(len(run["records"]), 2)
        partial = run_smoke(scenario, generator=gen, evaluator=rq1_endpoints,
                            outer=2, inner=12, seed=9, stop_after=1)
        self.assertEqual(partial["status"], "PARTIAL_ENGINEERING_SMOKE")
        resumed = run_smoke(scenario, generator=gen, evaluator=rq1_endpoints,
                            outer=2, inner=12, seed=9, resume_from=partial)
        self.assertEqual(resumed["records"], run["records"])
        with self.assertRaisesRegex(ValueError, "resume_plan_or_seed_mismatch"):
            run_smoke(scenario, generator=gen, evaluator=rq1_endpoints,
                      outer=2, inner=12, seed=10, resume_from=partial)
        failed = run_smoke(scenario, generator=lambda _: (_ for _ in ()).throw(RuntimeError("secret")),
                           evaluator=rq1_endpoints, outer=1, inner=12, seed=3)
        self.assertEqual(failed["endpoint_summary"]["delta_macro_f1"]["undefined_count"], 1)
        self.assertIn("ENGINEERING_EXCEPTION_RuntimeError",
                      failed["records"][0]["undefined"].values())
        self.assertNotIn("secret", str(failed))
        with self.assertRaisesRegex(ValueError, "smoke_budget_only"):
            run_smoke(scenario, generator=gen, evaluator=rq1_endpoints,
                      outer=1_000, inner=10_000)

    def test_rq2_rq3_synthetic_generators_and_separate_strata(self):
        gen2 = synthetic_summary_generator(clusters=10, incidents_per_cluster=1,
                                           facts_per_incident=3, claims_per_incident=3,
                                           cfr_s2=.4, cfr_s3=.6, ucr_s2=.1, ucr_s3=.12,
                                           cluster_dependence=.1)
        truth2 = {"delta_cfr": .2, "delta_ucr": .02}
        scenario2 = Scenario("rq2_smoke", "RQ2", truth2,
                             {"delta_cfr": "lower", "delta_ucr": "upper"},
                             "TRUE_H1", {"synthetic": True})
        run2 = run_smoke(scenario2, generator=gen2, evaluator=rq2_endpoints,
                         outer=1, inner=12, seed=2)
        self.assertEqual(run2["calibration_gate"], "NOT_RUN_NO_SCENARIO_LOCK")
        self.assertEqual(run2["records"][0]["index"], 0)
        gen3 = synthetic_rq3_generator(clusters_a=10, clusters_b=10,
                                       pairs_per_cluster=5,
                                       prevalence_a=(.5, .25, .25),
                                       prevalence_b=(.4, .3, .3),
                                       errors_a=(.2, .1), errors_b=(.35, .15))
        truth3 = rq3_population_truth(prevalence_a=(.5, .25, .25),
                                      prevalence_b=(.4, .3, .3),
                                      errors_a=(.2, .1), errors_b=(.35, .15))
        self.assertGreater(truth3["advantage_macro_f1"], 0)
        self.assertEqual(cached_rq3_endpoints(cache_pairs(gen3(5))), rq3_endpoints(gen3(5)))
        scenario3 = Scenario("rq3_smoke", "RQ3", truth3,
                             {name: "two_sided" for name in truth3},
                             "TRUE_H1", {"synthetic": True})
        run3 = run_smoke(scenario3, generator=gen3, evaluator=rq3_endpoints,
                         outer=1, inner=12, seed=3,
                         stratum_of=lambda unit: unit.environment)
        self.assertEqual(run3["records"][0]["undefined"], {})


class W7AgreementGateTests(unittest.TestCase):
    def test_initial_agreement_and_consensus_rejection(self):
        labels1 = ("supported", "contradicted", "insufficient")
        labels2 = ("supported", "insufficient", "insufficient")
        left = tuple(InitialJudgment(f"U{i}", "I", "SYN_A", "A1", label,
                                     "synthetic:audit:a") for i, label in enumerate(labels1))
        right = tuple(InitialJudgment(f"U{i}", "I", "SYN_A", "A2", label,
                                      "synthetic:audit:b") for i, label in enumerate(labels2))
        result = score_agreement(left, right, unresolved_unit_ids=frozenset({"U1"}))
        self.assertEqual(result["raw_agreement"], 2 / 3)
        self.assertEqual(result["disagreement_count"], 1)
        self.assertEqual(result["unresolved_adjudications"], 1)
        self.assertEqual(result["cross_tabulation"]["contradicted"]["insufficient"], 1)
        self.assertIsNotNone(result["cohens_kappa"]["value"])
        with self.assertRaisesRegex(ValueError, "initial_independent_judgment_required"):
            InitialJudgment("U", "I", "A", "A1", "supported", "r", "ADJUDICATED")
        with self.assertRaisesRegex(ValueError, "invalid_independent_annotation_alignment"):
            score_agreement(left, left)

    def test_readiness_refs_cannot_authorize_access(self):
        blank = check_readiness()
        self.assertEqual(blank["status"], "PENDING")
        self.assertEqual(len(blank["checks"]), len(GATES))
        all_pass = {name: {"status": "PASS", "reason": "synthetic_assertion",
                           "evidence_ref": f"synthetic:{name}"} for name in GATES}
        self.assertFalse(check_readiness(all_pass)["heldout_execution_authorized"])
        all_pass["pretest_ci_calibration"] = {"status": "FAIL", "reason": "not_complete",
                                              "evidence_ref": "synthetic:failure"}
        self.assertEqual(check_readiness(all_pass)["status"], "BLOCKED")
        with self.assertRaisesRegex(ValueError, "sealed_content"):
            check_readiness({"labels": {"status": "PASS"}})


if __name__ == "__main__":
    unittest.main()
