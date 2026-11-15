"""Matched V0/V2/V3 diagnostic on authored synthetic train cases only.

Fixture answers are kept outside VerifierInput. This is an engineering check,
not a pilot, held-out comparison, or estimate of RQ1 performance.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable

from egis_soc.development_benchmark import (
    LABELS, PROVENANCE, ClassificationCase, classification_metrics,
)
from egis_soc.development_data import DevelopmentData
from egis_soc.development_v2 import (
    LABEL_MAP, MODEL_ID, MODEL_REVISION, DevelopmentV2, NLIPair,
)
from egis_soc.integrity import canonical_bytes

from .contract import VerifierInput, VerifierOutput
from .fusion import FusionPolicy, SyntheticV3Verifier
from .rules import SyntheticV0Rules, VERSION as RULE_VERSION


VERSION = "w4-matched-synthetic-diagnostic-1"
FIXTURE_VERSION = "w4-matched-synthetic-fixture-1"
STATUS = "SYNTHETIC_ENGINEERING_NOT_GOLD_NOT_RQ1"
ARMS = ("V0", "V2", "V3")
REAL_STATUS = "NOT_RUN_NO_ACCEPTED_HUMAN_GOLD_PILOT"


def _digest(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _input_record(request: VerifierInput) -> dict:
    return {
        "pair_id": request.pair.pair_id,
        "incident_id": request.pair.incident_id,
        "tenant_id": request.pair.tenant_id,
        "claim": request.pair.claim,
        "evidence_ordered": [{"id": item.evidence_id, "text": item.text}
                             for item in request.evidence],
        "citation_ids": list(request.citation_ids),
    }


def validate_fixture(fixture: dict) -> tuple[tuple[VerifierInput, str], ...]:
    if (type(fixture) is not dict
            or set(fixture) != {"version", "label_provenance", "partition",
                                "lineage_group", "cases"}
            or fixture["version"] != FIXTURE_VERSION
            or fixture["label_provenance"] != PROVENANCE
            or fixture["partition"] != "train"
            or fixture["lineage_group"] != "SYNTHETIC"
            or type(fixture["cases"]) is not list or not fixture["cases"]):
        raise ValueError("invalid_w4_synthetic_fixture")
    seen_cases: set[str] = set()
    seen_evidence: set[str] = set()
    prepared: list[tuple[VerifierInput, str]] = []
    for row in fixture["cases"]:
        if (type(row) is not dict
                or set(row) != {"id", "expected", "claim", "evidence_ids",
                                    "citation_ids", "events"}
                or not isinstance(row["id"], str) or not row["id"].startswith("W4-C")
                or row["id"] in seen_cases or row["expected"] not in LABELS
                or not isinstance(row["claim"], str) or not row["claim"].strip()
                or type(row["evidence_ids"]) is not list or not row["evidence_ids"]
                or type(row["citation_ids"]) is not list
                or type(row["events"]) is not list or not row["events"]):
            raise ValueError("invalid_w4_synthetic_case")
        seen_cases.add(row["id"])
        incident_id = f"SYN-{row['id']}"
        tenant_id = "SYN-TENANT"
        events = []
        for index, event in enumerate(row["events"], 1):
            if (type(event) is not dict
                    or set(event) not in ({"id", "time", "event_data"},
                                          {"id", "time", "event_data", "padding_tokens"})
                    or not isinstance(event["id"], str)
                    or not event["id"].startswith("W4-E")
                    or event["id"] in seen_evidence
                    or not isinstance(event["time"], str)
                    or type(event["event_data"]) is not dict
                    or any(not isinstance(key, str) or not isinstance(value, str)
                           for key, value in event["event_data"].items())):
                raise ValueError("invalid_w4_synthetic_event")
            seen_evidence.add(event["id"])
            body = dict(event["event_data"])
            if "padding_tokens" in event:
                count = event["padding_tokens"]
                if type(count) is not int or not 512 <= count <= 1024 or "message" in body:
                    raise ValueError("invalid_w4_synthetic_padding")
                body["message"] = " ".join(["padding"] * count)
            events.append({
                "evidence_id": event["id"], "incident_id": incident_id,
                "tenant_id": tenant_id, "source_ref": f"synthetic:{row['id']}:{index}",
                "timestamp_utc": event["time"], "event_data": body,
            })
        available = {event["evidence_id"] for event in events}
        ids = row["evidence_ids"]
        if (any(not isinstance(item, str) for item in ids)
                or len(set(ids)) != len(ids) or set(ids) != available
                or any(not isinstance(item, str) for item in row["citation_ids"])):
            raise ValueError("unmatched_w4_synthetic_evidence")
        data = DevelopmentData(incident_id, tenant_id, "train", "SYNTHETIC",
                               "synthetic", None, tuple(events))
        pair = NLIPair(row["id"], incident_id, tenant_id, row["claim"], tuple(ids))
        request = VerifierInput.from_synthetic_data(
            data, pair, citation_ids=tuple(row["citation_ids"]))
        prepared.append((request, row["expected"]))
    if {expected for _, expected in prepared} != set(LABELS):
        raise ValueError("w4_fixture_requires_three_labels")
    return tuple(prepared)


def _arm_record(output: VerifierOutput) -> dict:
    return {
        "prediction": output.prediction,
        "review_required": output.review_required,
        "decision_reason": output.decision_reason,
        "truncated": output.truncated,
        "citation_checks": [{"evidence_id": item.evidence_id, "valid": item.valid,
                             "reason": item.reason} for item in output.citation_checks],
        "rule_trace": [{"rule_id": trace.rule_id, "outcome": trace.outcome,
                        "evidence_ids": list(trace.evidence_ids), "reason": trace.reason}
                       for trace in output.rule_trace],
        "nli_scores": dict(output.nli_scores) if output.nli_scores is not None else None,
        "model_id": output.model_id,
        "model_revision": output.model_revision,
        "policy_version": output.policy_version,
        "policy_sha256": output.policy_sha256,
    }


def _error_kind(expected: str, predicted: str) -> str | None:
    return None if expected == predicted else f"{expected.upper()}_AS_{predicted.upper()}"


def _summaries(cases: list[dict]) -> dict:
    total = len(cases)
    arms = {}
    for arm in ARMS:
        arm_cases = tuple(ClassificationCase(row["case_id"], row["expected"],
                                             row["arms"][arm]["prediction"])
                          for row in cases)
        errors = Counter(_error_kind(row["expected"], row["arms"][arm]["prediction"])
                         for row in cases if row["expected"] != row["arms"][arm]["prediction"])
        routed = sum(row["arms"][arm]["review_required"] for row in cases)
        arms[arm] = {
            "classification": classification_metrics(arm_cases),
            "error_counts": dict(sorted(errors.items())),
            "review_count": routed,
            "review_rate": routed / total,
        }
    factual_rules = ("entity", "temporal", "event_semantic")
    coverage = {group: sum(any(
        trace["rule_id"] == f"{RULE_VERSION}:{group}"
        and trace["outcome"] != "not_applicable"
        for trace in row["arms"]["V0"]["rule_trace"]) for row in cases)
        for group in factual_rules}
    return {
        "arms": arms,
        "v2_v3_disagreement_count": sum(
            row["arms"]["V2"]["prediction"] != row["arms"]["V3"]["prediction"]
            for row in cases),
        "v2_v3_identical_score_count": sum(
            row["arms"]["V2"]["nli_scores"] == row["arms"]["V3"]["nli_scores"]
            for row in cases),
        "truncated_v2_count": sum(row["arms"]["V2"]["truncated"] for row in cases),
        "citation_warning_count": sum(
            row["arms"]["V0"]["rule_trace"][0]["outcome"] != "pass"
            for row in cases),
        "factual_rule_applicable_counts": coverage,
    }


def run_fixture(fixture: dict, *,
                v2_factory: Callable[[], DevelopmentV2] = DevelopmentV2) -> dict:
    prepared = validate_fixture(fixture)
    verifier = SyntheticV3Verifier(v2_factory())
    rules = SyntheticV0Rules()
    cases = []
    for request, expected in prepared:
        v0 = rules.evaluate(request)
        v2, v3 = verifier.compare(request)
        if (any(output.request is not request for output in (v0, v2, v3))
                or v2.nli_scores != v3.nli_scores
                or v2.model_id != v3.model_id or v2.model_revision != v3.model_revision
                or v0.rule_trace != v3.rule_trace):
            raise ValueError("unmatched_w4_verifier_execution")
        cases.append({
            "case_id": request.pair.pair_id, "expected": expected,
            "input_sha256": _digest(_input_record(request)),
            "evidence_ids_ordered": list(request.pair.evidence_ids),
            "citation_ids": list(request.citation_ids),
            "arms": {arm: _arm_record(output) for arm, output in
                     zip(ARMS, (v0, v2, v3))},
            "errors": {arm: _error_kind(expected, output.prediction) for arm, output in
                       zip(ARMS, (v0, v2, v3))},
        })
    return {
        "version": VERSION, "status": STATUS,
        "label_provenance": PROVENANCE, "case_count": len(cases),
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "rule_version": RULE_VERSION, "policy_version": verifier.policy.version,
        "policy_sha256": verifier.policy.sha256,
        "policy_calibration_status": verifier.policy.calibration_status,
        "cases": cases, "summary": _summaries(cases),
        "real_pilot_metric": REAL_STATUS,
        "rq1_claim": "NOT_RUN_NO_HUMAN_GOLD_OR_FROZEN_DRAFT_PAIR_POPULATION",
    }


def verify_result(fixture: dict, result: dict) -> None:
    prepared = validate_fixture(fixture)
    policy = FusionPolicy()
    if (result.get("version") != VERSION or result.get("status") != STATUS
            or result.get("label_provenance") != PROVENANCE
            or result.get("case_count") != len(prepared)
            or result.get("model_id") != MODEL_ID
            or result.get("model_revision") != MODEL_REVISION
            or result.get("rule_version") != RULE_VERSION
            or result.get("policy_version") != policy.version
            or result.get("policy_sha256") != policy.sha256
            or result.get("policy_calibration_status") != policy.calibration_status
            or result.get("real_pilot_metric") != REAL_STATUS
            or result.get("rq1_claim") !=
            "NOT_RUN_NO_HUMAN_GOLD_OR_FROZEN_DRAFT_PAIR_POPULATION"
            or type(result.get("cases")) is not list
            or len(result["cases"]) != len(prepared)):
        raise ValueError("w4_diagnostic_scope_or_population_changed")
    for (request, expected), row in zip(prepared, result["cases"]):
        if (row.get("case_id") != request.pair.pair_id or row.get("expected") != expected
                or row.get("input_sha256") != _digest(_input_record(request))
                or row.get("evidence_ids_ordered") != list(request.pair.evidence_ids)
                or row.get("citation_ids") != list(request.citation_ids)
                or set(row.get("arms", {})) != set(ARMS)
                or set(row.get("errors", {})) != set(ARMS)):
            raise ValueError("w4_diagnostic_case_binding_changed")
        for arm in ARMS:
            output = row["arms"][arm]
            prediction = output.get("prediction")
            checks = output.get("citation_checks")
            if (prediction not in LABELS or type(output.get("review_required")) is not bool
                    or type(output.get("truncated")) is not bool
                    or not isinstance(output.get("decision_reason"), str)
                    or row["errors"][arm] != _error_kind(expected, prediction)
                    or checks != [{"evidence_id": item.evidence_id,
                                   "valid": item.valid, "reason": item.reason}
                                  for item in request.citation_checks]):
                raise ValueError("w4_diagnostic_arm_changed")
            traces = output.get("rule_trace")
            if type(traces) is not list or (arm == "V2" and traces) or (arm != "V2" and not traces):
                raise ValueError("w4_diagnostic_trace_changed")
            for trace in traces:
                if (trace.get("rule_id") not in {f"{RULE_VERSION}:{group}" for group in
                                                   ("citation", "entity", "temporal", "event_semantic")}
                        or trace.get("outcome") not in
                        {"pass", "contradiction", "insufficient", "not_applicable"}
                        or not set(trace.get("evidence_ids", [])) <= set(request.pair.evidence_ids)):
                    raise ValueError("w4_diagnostic_trace_changed")
            scores = output.get("nli_scores")
            if arm == "V0":
                if (scores is not None or output.get("model_id") is not None
                        or output.get("model_revision") is not None
                        or output.get("policy_sha256") is not None):
                    raise ValueError("w4_diagnostic_v0_has_nli")
            else:
                if (type(scores) is not dict
                        or set(scores) != {"contradiction", "entailment", "neutral"}
                        or any(type(value) is not float or not 0.0 <= value <= 1.0
                               for value in scores.values())
                        or abs(sum(scores.values()) - 1.0) > 1e-8
                        or output.get("model_id") != MODEL_ID
                        or output.get("model_revision") != MODEL_REVISION):
                    raise ValueError("w4_diagnostic_nli_changed")
                if arm == "V2" and prediction != LABEL_MAP[max(scores, key=scores.get)]:
                    raise ValueError("w4_diagnostic_v2_argmax_changed")
                if arm == "V3" and (output.get("policy_version") != policy.version
                                    or output.get("policy_sha256") != policy.sha256):
                    raise ValueError("w4_diagnostic_policy_changed")
        if (row["arms"]["V2"]["nli_scores"] != row["arms"]["V3"]["nli_scores"]
                or row["arms"]["V2"]["truncated"] != row["arms"]["V3"]["truncated"]
                or row["arms"]["V0"]["rule_trace"] != row["arms"]["V3"]["rule_trace"]):
            raise ValueError("unmatched_w4_saved_outputs")
    if result.get("summary") != _summaries(result["cases"]):
        raise ValueError("w4_diagnostic_summary_changed")


def result_bytes(result: dict) -> bytes:
    return json.dumps(result, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
