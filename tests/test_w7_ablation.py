"""Secondary synthetic W7 ablation configuration and identity tests."""

import unittest

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import DevelopmentV2
from egis_soc.w7.ablation import AblatedV3, VARIANTS, run_ablation_suite
from test_w4_rules import FULL, request_for


class Backend:
    def __init__(self, logits=(0.0, 5.0, 0.0)):
        self.logits = logits
        self.calls = 0

    def score(self, premise, hypothesis):
        self.calls += 1
        return self.logits, False


class W7AblationTests(unittest.TestCase):
    def test_four_secondary_variants_share_input_nli_and_policy(self):
        request = request_for(dict(FULL, actor="bob"))
        backend = Backend()
        baseline = SyntheticV3Verifier(DevelopmentV2(backend))
        report = run_ablation_suite((request,), baseline,
                                    lambda kind: AblatedV3(DevelopmentV2(backend),
                                                           kind=kind, policy=baseline.policy))
        self.assertEqual(set(report["variants"]), set(VARIANTS))
        self.assertEqual(backend.calls, 5)
        self.assertEqual(report["variants"]["without_entity"][0]["variant_v3"], "supported")
        self.assertEqual(report["variants"]["without_event_semantic"][0]["variant_v3"],
                         "contradicted")
        self.assertEqual(report["variants"]["without_abstention_review"][0]["variant_v3"],
                         "contradicted")
        self.assertTrue(all(rows[0]["nli_identical"] for rows in report["variants"].values()))
        self.assertFalse(report["confirmatory_eligible"])

    def test_drift_is_rejected(self):
        request = request_for(FULL)
        baseline = SyntheticV3Verifier(DevelopmentV2(Backend()))
        with self.assertRaisesRegex(ValueError, "ablation_nli_or_input_drift"):
            run_ablation_suite((request,), baseline,
                               lambda kind: AblatedV3(DevelopmentV2(Backend((5.0, 0.0, 0.0))),
                                                      kind=kind, policy=baseline.policy))
        with self.assertRaisesRegex(ValueError, "unknown_ablation"):
            AblatedV3(DevelopmentV2(Backend()), kind="unregistered")


if __name__ == "__main__":
    unittest.main()
