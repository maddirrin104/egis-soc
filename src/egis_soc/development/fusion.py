"""W4-02 versioned synthetic V3 rule/NLI fusion and review routing."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from egis_soc.development_v2 import DevelopmentV2

from .contract import VerifierInput, VerifierOutput, run_v2
from .rules import SyntheticV0Rules


VERSION = "w4-v3-synthetic-fusion-1"
CALIBRATION_STATUS = "SYNTHETIC_PREDECLARED_UNCALIBRATED"


@dataclass(frozen=True)
class FusionPolicy:
    """Engineering-only thresholds; no test/OOD or real-label tuning."""

    minimum_top_probability: float = 0.60
    minimum_margin: float = 0.15
    version: str = VERSION
    calibration_status: str = CALIBRATION_STATUS

    def __post_init__(self) -> None:
        if (self.version != VERSION or self.calibration_status != CALIBRATION_STATUS
                or type(self.minimum_top_probability) is not float
                or type(self.minimum_margin) is not float
                or not math.isfinite(self.minimum_top_probability)
                or not math.isfinite(self.minimum_margin)
                or not 0.0 <= self.minimum_top_probability <= 1.0
                or not 0.0 <= self.minimum_margin <= 1.0):
            raise ValueError("invalid_synthetic_fusion_policy")

    @property
    def sha256(self) -> str:
        record = {
            "version": self.version,
            "calibration_status": self.calibration_status,
            "minimum_top_probability": format(self.minimum_top_probability, ".17g"),
            "minimum_margin": format(self.minimum_margin, ".17g"),
        }
        raw = json.dumps(record, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
        return hashlib.sha256(raw).hexdigest()


class SyntheticV3Verifier:
    """Execute V0 and the unchanged pinned V2 over the same frozen input."""

    def __init__(self, nli: DevelopmentV2, *,
                 rules: SyntheticV0Rules | None = None,
                 policy: FusionPolicy | None = None) -> None:
        if not isinstance(nli, DevelopmentV2):
            raise TypeError("pinned_v2_adapter_required")
        self.nli = nli
        self.rules = rules if rules is not None else SyntheticV0Rules()
        self.policy = policy if policy is not None else FusionPolicy()
        if not isinstance(self.rules, SyntheticV0Rules) or not isinstance(self.policy, FusionPolicy):
            raise TypeError("synthetic_rule_and_policy_required")

    def compare(self, request: VerifierInput) -> tuple[VerifierOutput, VerifierOutput]:
        """Return paired V2/V3 outputs from one unchanged V2 inference."""
        if not isinstance(request, VerifierInput):
            raise TypeError("verifier_input_required")
        v0 = self.rules.evaluate(request)
        v2 = run_v2(request, self.nli)
        if v0.request is not request or v2.request is not request:
            raise ValueError("unmatched_verifier_request")
        scores = v2.nli_scores
        ordered = sorted(scores.values(), reverse=True)
        low_confidence = (ordered[0] < self.policy.minimum_top_probability
                          or ordered[0] - ordered[1] < self.policy.minimum_margin)
        citation_warning = v0.rule_trace[0].outcome != "pass"

        if v0.prediction == "contradicted" and v0.decision_reason == "DIRECT_FIELD_REFUTATION":
            prediction = "contradicted"
            reason = "DIRECT_RULE_REFUTATION"
            review = (v2.prediction != "contradicted" or low_confidence
                      or v2.truncated or citation_warning)
        elif v0.prediction != "supported":
            prediction = "insufficient"
            reason = "RULES_UNRESOLVED"
            review = True
        elif v2.truncated:
            prediction = "insufficient"
            reason = "TRUNCATED_NLI_INPUT"
            review = True
        elif low_confidence:
            prediction = "insufficient"
            reason = "LOW_NLI_CONFIDENCE"
            review = True
        elif v2.prediction != "supported":
            prediction = "insufficient"
            reason = "RULE_NLI_DISAGREEMENT"
            review = True
        else:
            prediction = "supported"
            reason = "FULL_RULE_AND_NLI_SUPPORT"
            review = citation_warning

        v3 = VerifierOutput(
            request=request, arm="V3", prediction=prediction,
            review_required=review, decision_reason=reason,
            rule_trace=v0.rule_trace, citation_checks=request.citation_checks,
            nli_scores=scores, model_id=v2.model_id,
            model_revision=v2.model_revision, truncated=v2.truncated,
            policy_version=self.policy.version, policy_sha256=self.policy.sha256,
        )
        return v2, v3

    def predict(self, request: VerifierInput) -> VerifierOutput:
        return self.compare(request)[1]
