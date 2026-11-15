"""Secondary synthetic V3 ablations with matched V2/NLI checks."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace

from egis_soc.development.contract import VerifierInput, VerifierOutput
from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development.rules import SyntheticV0Rules

VERSION = "w7-synthetic-ablation-1"
VARIANTS = ("without_entity", "without_temporal", "without_event_semantic",
            "without_abstention_review")
GROUPS = {"without_entity": "entity", "without_temporal": "temporal",
          "without_event_semantic": "event_semantic"}


class AblatedRules(SyntheticV0Rules):
    def __init__(self, group: str):
        if group not in GROUPS.values():
            raise ValueError("unknown_rule_group")
        self.group = group

    def evaluate(self, request: VerifierInput) -> VerifierOutput:
        base = super().evaluate(request)
        traces = tuple(replace(trace, outcome="not_applicable", reason="ABLATION_GROUP_REMOVED",
                               evidence_ids=()) if trace.rule_id.endswith(f":{self.group}")
                       else trace for trace in base.rule_trace)
        factual = [trace for trace in traces[1:] if trace.outcome != "not_applicable"]
        if any(trace.outcome == "insufficient" for trace in factual) or not factual:
            prediction = "insufficient"
        elif any(trace.outcome == "contradiction" for trace in factual):
            prediction = "contradicted"
        else:
            prediction = "supported"
        reason = {"supported": "FULL_FIELD_SUPPORT", "contradicted": "DIRECT_FIELD_REFUTATION",
                  "insufficient": "UNRESOLVED_RULE_EVIDENCE"}[prediction]
        return replace(base, prediction=prediction,
                       review_required=(prediction == "insufficient" or traces[0].outcome != "pass"),
                       decision_reason=reason, rule_trace=traces)


class AblatedV3(SyntheticV3Verifier):
    def __init__(self, nli, *, kind: str, policy=None):
        if kind not in VARIANTS:
            raise ValueError("unknown_ablation")
        self.kind = kind
        super().__init__(nli, rules=AblatedRules(GROUPS[kind]) if kind in GROUPS else None,
                         policy=policy)

    def compare(self, request: VerifierInput) -> tuple[VerifierOutput, VerifierOutput]:
        v2, v3 = super().compare(request)
        if self.kind == "without_abstention_review":
            if all(check.valid for check in request.citation_checks):
                prediction = (v3.prediction if v3.decision_reason == "DIRECT_RULE_REFUTATION"
                              else v2.prediction)
                v3 = replace(v3, prediction=prediction, review_required=False,
                             decision_reason="ABLATION_NO_ABSTENTION_REVIEW")
        digest = hashlib.sha256(f"{VERSION}:{self.kind}:{self.policy.sha256}".encode()).hexdigest()
        return v2, replace(v3, policy_version=f"{VERSION}:{self.kind}", policy_sha256=digest)


def run_ablation_suite(requests: tuple[VerifierInput, ...], baseline: SyntheticV3Verifier,
                       factory: Callable[[str], AblatedV3]) -> dict:
    """Compare identical synthetic requests and NLI scores; never scores gold."""
    if (not requests or any(not isinstance(item, VerifierInput) for item in requests)
            or len({item.pair.pair_id for item in requests}) != len(requests)
            or not isinstance(baseline, SyntheticV3Verifier)):
        raise ValueError("invalid_ablation_requests")
    expected = {request.pair.pair_id: baseline.compare(request) for request in requests}
    results = {}
    for kind in VARIANTS:
        verifier = factory(kind)
        if (not isinstance(verifier, AblatedV3) or verifier.kind != kind
                or verifier.policy.sha256 != baseline.policy.sha256):
            raise ValueError("ablation_policy_drift")
        rows = []
        for request in requests:
            pair_id = request.pair.pair_id
            v2, v3 = verifier.compare(request)
            original_v2, original_v3 = expected[pair_id]
            if (v2.nli_scores != original_v2.nli_scores
                    or v2.model_id != original_v2.model_id
                    or v2.model_revision != original_v2.model_revision
                    or v2.truncated != original_v2.truncated
                    or v2.request is not request or v3.request is not request):
                raise ValueError("ablation_nli_or_input_drift")
            rows.append({"pair_id": pair_id, "baseline_v3": original_v3.prediction,
                         "variant_v3": v3.prediction, "variant_review": v3.review_required,
                         "nli_identical": True, "policy_sha256": v3.policy_sha256})
        results[kind] = rows
    return {"version": VERSION, "scope": "SYNTHETIC_SECONDARY_ONLY",
            "pair_count": len(requests), "variants": results,
            "baseline_policy_sha256": baseline.policy.sha256,
            "confirmatory_eligible": False}
