"""Fixed synthetic W3 benchmark run with per-case diagnostics, never real gold."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

from .development_benchmark import (
    LABELS, PROVENANCE, ClassificationCase, RetrievalCase,
    classification_metrics, retrieval_metrics,
)
from .development_data import DevelopmentData
from .development_retrieval import DevelopmentRetriever
from .development_v1 import DevelopmentPair, DevelopmentV1
from .development_v2 import LABEL_MAP, NLI_LABELS, DevelopmentV2, NLIPair


VERSION = "w3-synthetic-benchmark-fixture-1"
STATUS = "SYNTHETIC_ENGINEERING_DIAGNOSTIC_NOT_GOLD"


def _section(section: dict, *, evaluation: bool) -> tuple[DevelopmentData, list[dict], list[dict]]:
    if (set(section) != ({"incident_id", "events", "pairs", "queries"}
                         if evaluation else {"incident_id", "events", "pairs"})
            or not isinstance(section["incident_id"], str)
            or not section["incident_id"].startswith("SYN-")
            or not isinstance(section["events"], list)
            or not section["events"]):
        raise ValueError("invalid_synthetic_benchmark_section")
    events = []
    for index, row in enumerate(section["events"], 1):
        if (not isinstance(row, dict) or set(row) != {"id", "message"}
                or not isinstance(row["id"], str) or not row["id"].startswith("EV-" if evaluation else "TR-")
                or not isinstance(row["message"], str) or not row["message"].strip()):
            raise ValueError("invalid_synthetic_benchmark_event")
        events.append({"evidence_id": row["id"], "incident_id": section["incident_id"],
                       "tenant_id": "SYN-TENANT", "source_ref": f"synthetic:{index}",
                       "timestamp_utc": f"2026-01-01T00:00:{index:02d}+00:00",
                       "event_data": {"message": row["message"]}})
    ids = {row["evidence_id"] for row in events}
    if len(ids) != len(events):
        raise ValueError("duplicate_synthetic_benchmark_evidence")
    pairs = section["pairs"]
    if not isinstance(pairs, list) or len(pairs) < 6:
        raise ValueError("missing_synthetic_benchmark_pairs")
    pair_ids = set()
    for row in pairs:
        if (not isinstance(row, dict)
                or set(row) != {"id", "claim", "evidence_ids", "expected"}
                or not isinstance(row["id"], str) or not row["id"]
                or row["id"] in pair_ids
                or not isinstance(row["claim"], str) or not row["claim"].strip()
                or row["expected"] not in LABELS
                or not isinstance(row["evidence_ids"], list)
                or not row["evidence_ids"]
                or len(set(row["evidence_ids"])) != len(row["evidence_ids"])
                or not set(row["evidence_ids"]) <= ids):
            raise ValueError("invalid_synthetic_benchmark_pair")
        pair_ids.add(row["id"])
    if set(row["expected"] for row in pairs) != set(LABELS):
        raise ValueError("synthetic_benchmark_requires_three_classes")
    queries = section.get("queries", [])
    if evaluation:
        if not isinstance(queries, list) or not queries:
            raise ValueError("missing_synthetic_benchmark_queries")
        query_ids = set()
        for row in queries:
            if (not isinstance(row, dict)
                    or set(row) != {"id", "query", "gold_evidence_ids"}
                    or not isinstance(row["id"], str) or not row["id"]
                    or row["id"] in query_ids
                    or not isinstance(row["query"], str) or not row["query"].strip()
                    or not isinstance(row["gold_evidence_ids"], list)
                    or not row["gold_evidence_ids"]
                    or len(set(row["gold_evidence_ids"])) != len(row["gold_evidence_ids"])
                    or not set(row["gold_evidence_ids"]) <= ids):
                raise ValueError("invalid_synthetic_benchmark_query")
            query_ids.add(row["id"])
    data = DevelopmentData(section["incident_id"], "SYN-TENANT", "train",
                           "SYNTHETIC", "synthetic", None, tuple(events))
    DevelopmentRetriever(data)
    return data, pairs, queries


def validate_fixture(fixture: dict) -> tuple:
    if (not isinstance(fixture, dict)
            or set(fixture) != {"version", "label_provenance", "train", "evaluation"}
            or fixture["version"] != VERSION
            or fixture["label_provenance"] != PROVENANCE):
        raise ValueError("non_synthetic_benchmark_fixture")
    train, train_pairs, _ = _section(fixture["train"], evaluation=False)
    evaluation, eval_pairs, queries = _section(fixture["evaluation"], evaluation=True)
    if (train.incident_id == evaluation.incident_id
            or {row["id"] for row in train_pairs} & {row["id"] for row in eval_pairs}
            or {event["evidence_id"] for event in train.events}
            & {event["evidence_id"] for event in evaluation.events}):
        raise ValueError("synthetic_benchmark_train_eval_overlap")
    return train, train_pairs, evaluation, eval_pairs, queries


def _error_kind(expected: str, predicted: str) -> str | None:
    if expected == predicted:
        return None
    if predicted == "supported":
        return "FALSE_SUPPORTED"
    if expected == "supported":
        return "MISSED_SUPPORTED"
    return "CONTRADICTED_INSUFFICIENT_CONFUSION"


def run_fixture(fixture: dict, *, v2_factory: Callable[[], DevelopmentV2] = DevelopmentV2) -> dict:
    train, train_pairs, evaluation, eval_pairs, queries = validate_fixture(fixture)
    train_samples = tuple((train, DevelopmentPair(
        row["id"], train.incident_id, train.tenant_id, row["claim"],
        tuple(row["evidence_ids"]), row["expected"], PROVENANCE))
        for row in train_pairs)
    v1 = DevelopmentV1().fit(train_samples)
    v2 = v2_factory()
    retriever = DevelopmentRetriever(evaluation)
    retrieval_rows = []
    for row in queries:
        hits = retriever.search(row["query"], incident_id=evaluation.incident_id,
                                tenant_id=evaluation.tenant_id, limit=10)
        ranked = [hit.evidence_id for hit in hits]
        retrieval_rows.append({"case_id": row["id"],
                               "gold_evidence_ids": row["gold_evidence_ids"],
                               "ranked_evidence_ids": ranked,
                               "missed_at_5": sorted(set(row["gold_evidence_ids"]) - set(ranked[:5])),
                               "missed_at_10": sorted(set(row["gold_evidence_ids"]) - set(ranked[:10]))})
    classifications = {"v1": [], "v2": []}
    for row in eval_pairs:
        common = (row["id"], evaluation.incident_id, evaluation.tenant_id,
                  row["claim"], tuple(row["evidence_ids"]))
        v1_result = v1.predict(evaluation, DevelopmentPair(
            *common, row["expected"], PROVENANCE))
        v2_result = v2.predict(evaluation, NLIPair(*common))
        if v2_result["scores"] is None or set(v2_result["scores"]) != set(NLI_LABELS):
            raise ValueError("invalid_synthetic_benchmark_nli_scores")
        v2_scores = {LABEL_MAP[label]: score for label, score in v2_result["scores"].items()}
        for arm, result, scores in (
            ("v1", v1_result, v1_result["probabilities"]),
            ("v2", v2_result, v2_scores),
        ):
            if (result["pair_id"] != row["id"] or result["prediction"] not in LABELS
                    or scores is None or set(scores) != set(LABELS)
                    or any(not math.isfinite(score) for score in scores.values())):
                raise ValueError("invalid_synthetic_benchmark_model_output")
            classifications[arm].append({
                "case_id": row["id"], "expected": row["expected"],
                "predicted": result["prediction"], "scores": scores,
                "error_kind": _error_kind(row["expected"], result["prediction"]),
                "truncated": bool(result.get("truncated", False)),
            })
    retrieval = retrieval_metrics(tuple(RetrievalCase(
        row["case_id"], tuple(row["gold_evidence_ids"]),
        tuple(row["ranked_evidence_ids"])) for row in retrieval_rows))
    metrics = {arm: classification_metrics(tuple(ClassificationCase(
        row["case_id"], row["expected"], row["predicted"])
        for row in classifications[arm])) for arm in ("v1", "v2")}
    errors = {arm: dict(sorted(Counter(row["error_kind"] for row in rows
                                      if row["error_kind"]).items()))
              for arm, rows in classifications.items()}
    return {"version": VERSION, "status": STATUS,
            "fixture_provenance": PROVENANCE, "train_pair_count": len(train_pairs),
            "evaluation_pair_count": len(eval_pairs),
            "retrieval": {"cases": retrieval_rows, "metrics": retrieval},
            "classification": {arm: {"cases": classifications[arm], "metrics": metrics[arm],
                                     "error_counts": errors[arm]}
                               for arm in ("v1", "v2")},
            "real_pilot_recall_f1": "NOT_RUN_NO_HUMAN_REVIEWED_GOLD"}


def verify_result(fixture: dict, result: dict) -> None:
    _, train_pairs, _, eval_pairs, queries = validate_fixture(fixture)
    if (result.get("version") != VERSION or result.get("status") != STATUS
            or result.get("fixture_provenance") != PROVENANCE
            or result.get("real_pilot_recall_f1") != "NOT_RUN_NO_HUMAN_REVIEWED_GOLD"
            or result.get("train_pair_count") != len(train_pairs)
            or result.get("evaluation_pair_count") != len(eval_pairs)):
        raise ValueError("synthetic_benchmark_result_scope_changed")
    retrieval_rows = result["retrieval"]["cases"]
    if [(row["case_id"], row["gold_evidence_ids"]) for row in retrieval_rows] != [
            (row["id"], row["gold_evidence_ids"]) for row in queries]:
        raise ValueError("synthetic_benchmark_retrieval_population_changed")
    for row in retrieval_rows:
        gold = set(row["gold_evidence_ids"])
        ranked = row["ranked_evidence_ids"]
        if (row["missed_at_5"] != sorted(gold - set(ranked[:5]))
                or row["missed_at_10"] != sorted(gold - set(ranked[:10]))):
            raise ValueError("synthetic_benchmark_retrieval_error_changed")
    expected_retrieval = retrieval_metrics(tuple(RetrievalCase(
        row["case_id"], tuple(row["gold_evidence_ids"]),
        tuple(row["ranked_evidence_ids"])) for row in retrieval_rows))
    if result["retrieval"]["metrics"] != expected_retrieval:
        raise ValueError("synthetic_benchmark_retrieval_metric_changed")
    for arm in ("v1", "v2"):
        cases = result["classification"][arm]["cases"]
        if [(row["case_id"], row["expected"]) for row in cases] != [
                (row["id"], row["expected"]) for row in eval_pairs]:
            raise ValueError("synthetic_benchmark_classification_population_changed")
        for row in cases:
            if (row["predicted"] not in LABELS
                    or row["error_kind"] != _error_kind(row["expected"], row["predicted"])
                    or set(row["scores"]) != set(LABELS)
                    or any(not math.isfinite(value) or value < 0 or value > 1
                           for value in row["scores"].values())
                    or abs(sum(row["scores"].values()) - 1) > 1e-5):
                raise ValueError("synthetic_benchmark_case_changed")
        expected_metric = classification_metrics(tuple(ClassificationCase(
            row["case_id"], row["expected"], row["predicted"]) for row in cases))
        errors = dict(sorted(Counter(row["error_kind"] for row in cases
                                     if row["error_kind"]).items()))
        if (result["classification"][arm]["metrics"] != expected_metric
                or result["classification"][arm]["error_counts"] != errors):
            raise ValueError("synthetic_benchmark_classification_metric_changed")
