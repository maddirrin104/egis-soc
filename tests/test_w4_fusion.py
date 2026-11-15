"""W4-02 matched synthetic V2/V3 fusion and routing behavior."""

import math
import unittest

from egis_soc.development import (
    DevelopmentV2, FusionPolicy, SyntheticV3Verifier,
)
from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION

from test_w4_rules import CLAIM, FULL, request_for


class FakeBackend:
    def __init__(self, logits=(0.0, 5.0, 0.0), truncated=False):
        self.logits = logits
        self.truncated = truncated
        self.calls = []

    def score(self, premise, hypothesis):
        self.calls.append((premise, hypothesis))
        return self.logits, self.truncated


class SyntheticFusionTests(unittest.TestCase):
    def test_matched_v2_v3_support_and_deterministic_replay(self):
        request = request_for(FULL, citation_ids=("E1",))
        backend = FakeBackend()
        nli = DevelopmentV2(backend)
        verifier = SyntheticV3Verifier(nli)
        first_v2, first_v3 = verifier.compare(request)
        second_v2, second_v3 = verifier.compare(request)
        self.assertEqual((first_v2.prediction, first_v3.prediction),
                         ("supported", "supported"))
        self.assertEqual((first_v3.review_required, first_v3.decision_reason),
                         (False, "FULL_RULE_AND_NLI_SUPPORT"))
        self.assertEqual((first_v2, first_v3), (second_v2, second_v3))
        self.assertEqual(first_v3.nli_scores, first_v2.nli_scores)
        self.assertEqual((first_v3.model_id, first_v3.model_revision),
                         (MODEL_ID, MODEL_REVISION))
        self.assertEqual(first_v3.policy_version, verifier.policy.version)
        self.assertEqual(first_v3.policy_sha256, verifier.policy.sha256)
        self.assertEqual(backend.calls, [(request.evidence[0].text, CLAIM)] * 2)
        direct = nli.predict(request.data, request.pair)
        self.assertEqual((first_v2.prediction, first_v2.nli_scores),
                         (direct["prediction"], direct["scores"]))

    def test_direct_rule_refutation_overrides_nli_and_routes_disagreement(self):
        request = request_for(dict(FULL, outcome="failure"))
        v2, v3 = SyntheticV3Verifier(DevelopmentV2(FakeBackend())).compare(request)
        self.assertEqual((v2.prediction, v3.prediction, v3.review_required),
                         ("supported", "contradicted", True))
        self.assertEqual(v3.decision_reason, "DIRECT_RULE_REFUTATION")
        agreed = SyntheticV3Verifier(DevelopmentV2(FakeBackend((5.0, 0.0, 0.0))))
        _, agreed_v3 = agreed.compare(request)
        self.assertEqual((agreed_v3.prediction, agreed_v3.review_required),
                         ("contradicted", False))

    def test_low_confidence_disagreement_truncation_and_unknown_rules_route(self):
        request = request_for(FULL)
        cases = (
            (FakeBackend((0.0, 0.0, 0.0)), "LOW_NLI_CONFIDENCE"),
            (FakeBackend((5.0, 0.0, 0.0)), "RULE_NLI_DISAGREEMENT"),
            (FakeBackend(truncated=True), "TRUNCATED_NLI_INPUT"),
        )
        for backend, reason in cases:
            with self.subTest(reason=reason):
                v2, v3 = SyntheticV3Verifier(DevelopmentV2(backend)).compare(request)
                self.assertEqual((v3.prediction, v3.review_required, v3.decision_reason),
                                 ("insufficient", True, reason))
                self.assertEqual(len(backend.calls), 1)
                self.assertEqual(v3.nli_scores, v2.nli_scores)
        malformed = request_for(FULL, claim="free text claim")
        v2, v3 = SyntheticV3Verifier(DevelopmentV2(FakeBackend())).compare(malformed)
        self.assertEqual((v2.prediction, v3.prediction, v3.review_required),
                         ("supported", "insufficient", True))
        self.assertEqual(v3.decision_reason, "RULES_UNRESOLVED")

    def test_invalid_citation_warns_without_changing_factual_support(self):
        request = request_for(FULL, citation_ids=("UNKNOWN",))
        _, v3 = SyntheticV3Verifier(DevelopmentV2(FakeBackend())).compare(request)
        self.assertEqual((v3.prediction, v3.review_required), ("supported", True))
        self.assertFalse(v3.citation_checks[0].valid)
        no_citation = request_for(FULL, citation_ids=())
        _, routed = SyntheticV3Verifier(DevelopmentV2(FakeBackend())).compare(no_citation)
        self.assertEqual((routed.prediction, routed.review_required), ("supported", True))

    def test_policy_is_versioned_finite_and_synthetic_only(self):
        self.assertEqual(FusionPolicy().sha256, FusionPolicy().sha256)
        self.assertNotEqual(FusionPolicy().sha256,
                            FusionPolicy(minimum_margin=0.20).sha256)
        for bad in (math.nan, math.inf, -0.1, 1.1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                FusionPolicy(minimum_top_probability=bad)
        with self.assertRaises(ValueError):
            FusionPolicy(calibration_status="TEST_TUNED")


if __name__ == "__main__":
    unittest.main()
