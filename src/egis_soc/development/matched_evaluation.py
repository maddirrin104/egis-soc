"""Descriptive matched W4 scoring; synthetic execution only until data gates pass.

The arithmetic accepts already admitted, paired rows. It does not admit a
research manifest, certify human gold, or authorize final-test access.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

from egis_soc.integrity import canonical_bytes
from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION

from .contract import LABELS, RuleTrace, VerifierInput, VerifierOutput
from .fusion import SyntheticV3Verifier
from .rules import VERSION as RULE_VERSION


VERSION = "w4-matched-descriptive-scoring-1"
LABEL_ORDER = ("supported", "contradicted", "insufficient")
PROVENANCES = frozenset({"SYNTHETIC_KNOWN_ANSWER", "INDEPENDENT_HUMAN_GOLD"})
FAILURE_TAGS = frozenset({"TIMEOUT", "INFERENCE_ERROR", "MISSING_OUTPUT",
                          "UNPARSEABLE_OUTPUT"})
RULE_GROUPS = ("entity", "temporal", "event_semantic")


@dataclass(frozen=True)
class ArmAttempt:
    prediction: str
    review_required: bool
    decision_reason: str
    failure_tag: str | None = None
    rule_trace: tuple[RuleTrace, ...] = ()

    def __post_init__(self) -> None:
        if (self.prediction not in LABELS or type(self.review_required) is not bool
                or not self.decision_reason or type(self.rule_trace) is not tuple
                or any(not isinstance(item, RuleTrace) for item in self.rule_trace)):
            raise ValueError("invalid_matched_arm_attempt")
        if self.failure_tag is not None and (
                self.failure_tag not in FAILURE_TAGS
                or self.prediction != "insufficient" or not self.review_required
                or self.rule_trace):
            raise ValueError("invalid_failure_fallback")


@dataclass(frozen=True)
class MatchedRow:
    pair_id: str
    incident_id: str
    expected: str
    input_sha256: str
    v2: ArmAttempt
    v3: ArmAttempt
    gold_provenance: str = "SYNTHETIC_KNOWN_ANSWER"

    def __post_init__(self) -> None:
        if (not self.pair_id or not self.incident_id or self.expected not in LABELS
                or self.gold_provenance not in PROVENANCES
                or not isinstance(self.v2, ArmAttempt)
                or not isinstance(self.v3, ArmAttempt)
                or len(self.input_sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.input_sha256)):
            raise ValueError("invalid_matched_row")


def _fallback(tag: str) -> ArmAttempt:
    return ArmAttempt("insufficient", True, tag, tag)


def _attempt(request: VerifierInput, arm: str, value: object) -> ArmAttempt:
    if value is None:
        return _fallback("MISSING_OUTPUT")
    if not isinstance(value, VerifierOutput) or value.arm != arm:
        return _fallback("UNPARSEABLE_OUTPUT")
    if value.request is not request:
        raise ValueError("unmatched_verifier_request")
    return ArmAttempt(value.prediction, value.review_required,
                      value.decision_reason, rule_trace=value.rule_trace)


def _input_hash(request: VerifierInput) -> str:
    record = {
        "pair_id": request.pair.pair_id,
        "incident_id": request.pair.incident_id,
        "tenant_id": request.pair.tenant_id,
        "claim": request.pair.claim,
        "ordered_evidence": [(item.evidence_id, item.text) for item in request.evidence],
        "citation_ids": request.citation_ids,
    }
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def run_synthetic_matched(
        cases: tuple[tuple[VerifierInput, str], ...],
        verifier: SyntheticV3Verifier) -> tuple[MatchedRow, ...]:
    """Run fixed authored train cases; answers never enter the verifier call.

    A failed inference remains in the paired population as I plus review.
    An explicit cross-request or V2/V3 model/score mismatch is a hard error.
    """
    if (type(cases) is not tuple or not cases
            or not isinstance(verifier, SyntheticV3Verifier)):
        raise ValueError("invalid_synthetic_matched_batch")
    seen: set[str] = set()
    for request, expected in cases:
        if (not isinstance(request, VerifierInput) or expected not in LABELS
                or request.pair.gold_status != "NOT_GOLD"
                or request.pair.pair_id in seen):
            raise ValueError("invalid_synthetic_matched_case")
        seen.add(request.pair.pair_id)
    rows = []
    for request, expected in cases:
        try:
            outputs = verifier.compare(request)
        except TimeoutError:
            outputs = (None, None)
            failure = "TIMEOUT"
        except Exception:
            outputs = (None, None)
            failure = "INFERENCE_ERROR"
        else:
            failure = None
        if failure is not None:
            v2 = v3 = _fallback(failure)
        else:
            if not isinstance(outputs, tuple) or len(outputs) != 2:
                outputs = (None, None)
            v2, v3 = (_attempt(request, "V2", outputs[0]),
                      _attempt(request, "V3", outputs[1]))
            if v2.failure_tag is None and v3.failure_tag is None:
                left, right = outputs
                if (left.nli_scores != right.nli_scores
                        or left.model_id != right.model_id
                        or left.model_revision != right.model_revision
                        or left.truncated != right.truncated):
                    raise ValueError("unmatched_v2_v3_nli")
        rows.append(MatchedRow(request.pair.pair_id, request.pair.incident_id,
                               expected, _input_hash(request), v2, v3))
    return tuple(rows)


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _arm_metrics(rows: tuple[MatchedRow, ...], arm: str) -> dict:
    attempts = tuple(getattr(row, arm.lower()) for row in rows)
    matrix = {gold: {predicted: 0 for predicted in LABEL_ORDER}
              for gold in LABEL_ORDER}
    for row, attempt in zip(rows, attempts):
        matrix[row.expected][attempt.prediction] += 1
    by_class = {}
    for label in LABEL_ORDER:
        tp = matrix[label][label]
        gold_count = sum(matrix[label].values())
        predicted_count = sum(matrix[gold][label] for gold in LABEL_ORDER)
        fp = predicted_count - tp
        fn = gold_count - tp
        by_class[label] = {
            "tp": tp, "fp": fp, "fn": fn, "gold_count": gold_count,
            "predicted_count": predicted_count,
            "f1": _rate(2 * tp, 2 * tp + fp + fn),
        }
    f1s = [by_class[label]["f1"] for label in LABEL_ORDER]
    predicted_s = by_class["supported"]["predicted_count"]
    gold_s = by_class["supported"]["gold_count"]
    nonsupport = len(rows) - gold_s
    false_support_c = matrix["contradicted"]["supported"]
    false_support_i = matrix["insufficient"]["supported"]
    failures = Counter(attempt.failure_tag for attempt in attempts
                       if attempt.failure_tag is not None)
    reviews = sum(attempt.review_required for attempt in attempts)
    errors = Counter(f"{row.expected.upper()}_AS_{attempt.prediction.upper()}"
                     for row, attempt in zip(rows, attempts)
                     if row.expected != attempt.prediction)
    return {
        "confusion_matrix": matrix,
        "by_class": by_class,
        "macro_f1": sum(f1s) / 3 if all(item is not None for item in f1s) else None,
        "supported_precision": _rate(matrix["supported"]["supported"], predicted_s),
        "supported_precision_denominator": predicted_s,
        "supported_recall": _rate(matrix["supported"]["supported"], gold_s),
        "false_support_rate_proposed": _rate(false_support_c + false_support_i,
                                              nonsupport),
        "false_support_numerator": false_support_c + false_support_i,
        "false_support_c_to_s": false_support_c,
        "false_support_i_to_s": false_support_i,
        "false_support_denominator_proposed": nonsupport,
        "review_count": reviews, "review_rate": reviews / len(rows),
        "failure_count": sum(failures.values()),
        "failure_rate": sum(failures.values()) / len(rows),
        "failure_tags": dict(sorted(failures.items())),
        "error_counts": dict(sorted(errors.items())),
    }


def score_matched(rows: tuple[MatchedRow, ...]) -> dict:
    """Pure descriptive arithmetic for previously admitted rows.

    A future human-gold adapter must validate source rights, immutable pair
    manifest, lineage, blinding and approval before constructing rows. This
    function deliberately never declares a confirmatory result.
    """
    if (type(rows) is not tuple or not rows
            or any(not isinstance(row, MatchedRow) for row in rows)
            or len({row.pair_id for row in rows}) != len(rows)
            or len({row.gold_provenance for row in rows}) != 1):
        raise ValueError("invalid_matched_scoring_population")
    arms = {arm: _arm_metrics(rows, arm) for arm in ("V2", "V3")}
    incidents = {}
    for incident_id in dict.fromkeys(row.incident_id for row in rows):
        subset = tuple(row for row in rows if row.incident_id == incident_id)
        incidents[incident_id] = {
            "attempted_pairs": len(subset),
            "v2_review_count": sum(row.v2.review_required for row in subset),
            "v3_review_count": sum(row.v3.review_required for row in subset),
            "v2_failure_count": sum(row.v2.failure_tag is not None for row in subset),
            "v3_failure_count": sum(row.v3.failure_tag is not None for row in subset),
        }
    diagnostics = [
        {
            "pair_id": row.pair_id, "incident_id": row.incident_id,
            "gold_label": row.expected,
            "input_sha256": row.input_sha256,
            "arms": {arm: {
                "prediction": attempt.prediction,
                "review_required": attempt.review_required,
                "decision_reason": attempt.decision_reason,
                "failure_tag": attempt.failure_tag,
            } for arm, attempt in (("V2", row.v2), ("V3", row.v3))},
            "v3_rule_trace": [
                {"rule_id": trace.rule_id, "outcome": trace.outcome,
                 "evidence_ids": list(trace.evidence_ids), "reason": trace.reason}
                for trace in row.v3.rule_trace
            ],
        } for row in rows
    ]
    coverage = {}
    for group in RULE_GROUPS:
        traces = [next((trace for trace in row.v3.rule_trace
                        if trace.rule_id == f"{RULE_VERSION}:{group}"), None)
                  for row in rows]
        coverage[group] = {
            "evaluable_count": sum(trace is not None and
                                   trace.outcome != "not_applicable" for trace in traces),
            "contradiction_trigger_count": sum(trace is not None and
                                               trace.outcome == "contradiction" for trace in traces),
            "false_trigger_count": None,
            "denominator": len(rows),
        }
    return {
        "version": VERSION, "status": "DESCRIPTIVE_NOT_CONFIRMATORY",
        "gold_provenance": rows[0].gold_provenance,
        "case_count": len(rows), "pair_ids": [row.pair_id for row in rows],
        "input_sha256_by_pair": {row.pair_id: row.input_sha256 for row in rows},
        "arms": arms, "per_incident": incidents,
        "case_diagnostics": diagnostics, "rule_coverage": coverage,
        "fsr_denominator_status": "PROPOSED_AWAITING_PRETEST_APPROVAL",
        "confirmatory_eligible": False,
        "undefined_encoding": "null_means_NA_with_zero_denominator",
    }


def synthetic_run_report(
        cases: tuple[tuple[VerifierInput, str], ...],
        verifier: SyntheticV3Verifier) -> dict:
    """Build a no-write report with the exact synthetic model and policy IDs."""
    rows = run_synthetic_matched(cases, verifier)
    return {
        "evaluation": score_matched(rows),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "rule_version": RULE_VERSION,
        "policy_version": verifier.policy.version,
        "policy_sha256": verifier.policy.sha256,
        "policy_calibration_status": verifier.policy.calibration_status,
        "real_pilot_metric": "NOT_RUN_NO_ACCEPTED_HUMAN_GOLD_PILOT",
    }
