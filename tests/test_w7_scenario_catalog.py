"""Adverse synthetic count scenarios without held-out examples."""

import unittest

from egis_soc.w7.bootstrap import bootstrap_intervals
from egis_soc.w7.calibration import Scenario, population_truth, run_smoke
from egis_soc.w7.count_cache import (cached_rq1_endpoints, cached_rq2_endpoints,
                                      cached_rq3_endpoints)
from egis_soc.w7.scenario_catalog import (
    PairCountDesign, SummaryCountDesign, generate_pair_counts,
    generate_rq3_counts, generate_summary_counts, pair_population_truth,
    rq3_population_truth, summary_population_truth,
)


def pair_design(environment="SYN_A", *, sizes=(1, 1, 2, 2, 3, 3, 5, 5, 8, 10),
                dependence=.1):
    families = tuple("SYN_F0" if i % 2 == 0 else "SYN_F1" for i in range(len(sizes)))
    return PairCountDesign(environment, sizes, families,
                           {"SYN_F0": (.5, .25, .25), "SYN_F1": (.2, .4, .4)},
                           {"SYN_F0": (.25, .15), "SYN_F1": (.4, .3)},
                           dependence)


class W7ScenarioCatalogTests(unittest.TestCase):
    def test_sparse_unequal_family_heterogeneity_and_known_truth(self):
        design = pair_design()
        sample = generate_pair_counts(design, 7)
        self.assertEqual(len(sample), 10)
        self.assertEqual([sum(item.v2) for item in sample], list(design.cluster_sizes))
        self.assertEqual({item.source_family for item in sample}, {"SYN_F0", "SYN_F1"})
        self.assertEqual(sample, generate_pair_counts(design, 7))
        self.assertNotEqual(sample, generate_pair_counts(design, 8))
        truth = pair_population_truth(design)
        self.assertTrue(all(value is not None for value in truth.values()))
        sparse = PairCountDesign("SYN_A", (4,) * 10, ("SYN_F0",) * 10,
                                 {"SYN_F0": (.02, .49, .49)},
                                 {"SYN_F0": (.3, .2)})
        self.assertIsNotNone(pair_population_truth(sparse)["delta_macro_f1"])
        result = bootstrap_intervals(sample, evaluator=cached_rq1_endpoints,
                                     methods={name: "two_sided" for name in truth},
                                     repetitions=20, seed=2)
        self.assertEqual(result["cluster_counts"], {"single": 10})
        self.assertFalse(result["confirmatory_eligible"])

    def test_joint_boundary_and_composite_null_smoke(self):
        design = PairCountDesign("SYN_A", (5,) * 10, ("SYN_F0",) * 10,
                                 {"SYN_F0": (.5, .25, .25)},
                                 {"SYN_F0": (.25, .25)})
        truth = pair_population_truth(design)
        self.assertTrue(all(abs(value) < 1e-12 for value in truth.values()))
        scenario = Scenario("joint_boundary_candidate", "RQ1", truth,
                            {name: "two_sided" for name in truth},
                            "COMPOSITE_NULL", {"synthetic": True})
        smoke = run_smoke(scenario, generator=lambda seed: generate_pair_counts(design, seed),
                          evaluator=cached_rq1_endpoints, outer=1, inner=10, seed=5)
        self.assertEqual(smoke["calibration_gate"], "NOT_RUN_NO_SCENARIO_LOCK")
        self.assertIsNotNone(smoke["type_i_upper_exact"])

    def test_rq2_unequal_family_rates_and_rq3_separation(self):
        design = SummaryCountDesign((1, 2, 1, 2, 1, 2, 1, 2, 1, 2),
                                     tuple("SYN_F0" if i % 2 == 0 else "SYN_F1"
                                           for i in range(10)),
                                     {"SYN_F0": (.4, .6, .1, .12),
                                      "SYN_F1": (.3, .5, .15, .18)},
                                     facts_per_incident=3, claims_per_incident=4,
                                     cluster_dependence=.1)
        sample = generate_summary_counts(design, 11)
        self.assertEqual(sum(item.counts[0] for item in sample),
                         sum(design.cluster_sizes) * 3)
        self.assertEqual(set(summary_population_truth(design)), {"delta_cfr", "delta_ucr"})
        self.assertEqual(set(cached_rq2_endpoints(sample)), {"delta_cfr", "delta_ucr"})
        a, b = pair_design(dependence=0), pair_design("SYN_B", dependence=0)
        cross = generate_rq3_counts(a, b, 13)
        self.assertEqual(len(cross), 20)
        self.assertEqual({item.environment for item in cross}, {"SYN_A", "SYN_B"})
        self.assertTrue(all(abs(value) < 1e-12 for value in
                            rq3_population_truth(a, b).values()))
        result = bootstrap_intervals(cross, evaluator=cached_rq3_endpoints,
                                     methods={"advantage_macro_f1": "two_sided",
                                              "advantage_supported_precision": "two_sided"},
                                     repetitions=20, seed=4,
                                     stratum_of=lambda item: item.environment)
        self.assertEqual(result["cluster_counts"], {"SYN_A": 10, "SYN_B": 10})

    def test_invalid_designs_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_pair_count_design"):
            PairCountDesign("SYN_A", (1, 2), ("SYN_F0",),
                            {"SYN_F0": (.5, .25, .25)}, {"SYN_F0": (.3, .2)})
        with self.assertRaisesRegex(ValueError, "invalid_pair_count_design"):
            PairCountDesign("SYN_A", (2,), ("SYN_F0",),
                            {"SYN_F0": (.5, .25, .25)}, {"SYN_F0": (.02, .02)}, .2)
        with self.assertRaisesRegex(ValueError, "invalid_summary_count_design"):
            SummaryCountDesign((1,), ("SYN_F0",),
                               {"SYN_F0": (.4, .6, .1, 1.2)}, 2, 2)


if __name__ == "__main__":
    unittest.main()
