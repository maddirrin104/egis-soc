"""W3 synthetic development metrics and create-only experiment logging.

This module refuses weak PDS-01 labels as metric truth. Real pilot metrics
require a separately reviewed source/evidence/annotation gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from .integrity import canonical_bytes


VERSION = "w3-synthetic-development-benchmark-1"
LABELS = ("supported", "contradicted", "insufficient")
PROVENANCE = "SYNTHETIC_KNOWN_ANSWER"


def _canonical_metric_value(value):
    """Encode finite metric floats as decimal strings for strict canonical JSON."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("nonfinite_experiment_metric")
        return format(value, ".17g")
    if isinstance(value, dict):
        return {key: _canonical_metric_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_metric_value(item) for item in value]
    return value


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    gold_evidence_ids: tuple[str, ...]
    ranked_evidence_ids: tuple[str, ...]
    label_provenance: str = PROVENANCE


@dataclass(frozen=True)
class ClassificationCase:
    case_id: str
    expected: str
    predicted: str
    label_provenance: str = PROVENANCE


def retrieval_metrics(cases: tuple[RetrievalCase, ...]) -> dict:
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("synthetic_retrieval_cases_missing_or_repeated")
    total_gold = 0
    hits_5 = hits_10 = 0
    reciprocal_rank = 0.0
    for case in cases:
        gold = set(case.gold_evidence_ids)
        if (case.label_provenance != PROVENANCE or not case.case_id or not gold
                or len(gold) != len(case.gold_evidence_ids)
                or len(set(case.ranked_evidence_ids)) != len(case.ranked_evidence_ids)):
            raise ValueError("non_synthetic_or_invalid_retrieval_truth")
        total_gold += len(gold)
        hits_5 += len(gold.intersection(case.ranked_evidence_ids[:5]))
        hits_10 += len(gold.intersection(case.ranked_evidence_ids[:10]))
        reciprocal_rank += next((1.0 / rank for rank, evidence_id in
                                 enumerate(case.ranked_evidence_ids, 1)
                                 if evidence_id in gold), 0.0)
    return {"version": VERSION, "status": "SYNTHETIC_KNOWN_ANSWER_ONLY",
            "case_count": len(cases), "gold_evidence_count": total_gold,
            "recall_at_5_micro": hits_5 / total_gold,
            "recall_at_10_micro": hits_10 / total_gold,
            "mrr": reciprocal_rank / len(cases),
            "denominator_note": "Recall pools synthetic supporting IDs; MRR averages synthetic queries."}


def classification_metrics(cases: tuple[ClassificationCase, ...]) -> dict:
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("synthetic_classification_cases_missing_or_repeated")
    matrix = {actual: {predicted: 0 for predicted in LABELS} for actual in LABELS}
    for case in cases:
        if (case.label_provenance != PROVENANCE
                or case.expected not in LABELS or case.predicted not in LABELS):
            raise ValueError("non_synthetic_or_invalid_classification_truth")
        matrix[case.expected][case.predicted] += 1
    by_label = {}
    for label in LABELS:
        tp = matrix[label][label]
        predicted_total = sum(matrix[actual][label] for actual in LABELS)
        actual_total = sum(matrix[label].values())
        precision = tp / predicted_total if predicted_total else 0.0
        recall = tp / actual_total if actual_total else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        by_label[label] = {"support": actual_total, "precision": precision,
                           "recall": recall, "f1": f1}
    macro_f1 = sum(value["f1"] for value in by_label.values()) / len(LABELS)
    if not math.isfinite(macro_f1):
        raise ValueError("invalid_synthetic_f1")
    return {"version": VERSION, "status": "SYNTHETIC_KNOWN_ANSWER_ONLY",
            "case_count": len(cases), "labels": list(LABELS),
            "confusion_matrix": matrix, "by_label": by_label, "macro_f1": macro_f1,
            "denominator_note": "Fixed three-class macro average on synthetic cases only."}


def write_experiment_log(path: Path, *, retrieval: dict, classification: dict,
                         code_sha256: dict[str, str], seed: int) -> str:
    """Record a synthetic run without sensitive event text or weak-label scores."""
    if (retrieval.get("status") != "SYNTHETIC_KNOWN_ANSWER_ONLY"
            or classification.get("status") != "SYNTHETIC_KNOWN_ANSWER_ONLY"
            or type(seed) is not int or seed < 0
            or not code_sha256 or any(len(value) != 64 for value in code_sha256.values())):
        raise ValueError("invalid_synthetic_experiment_log")
    path = Path(path)
    if path.is_symlink() or path.exists():
        raise FileExistsError("experiment_log_already_exists")
    record = {"version": VERSION, "dataset_kind": "synthetic",
              "label_provenance": PROVENANCE, "gold_status": "NOT_GOLD",
              "real_pilot_recall_f1": "NOT_RUN_NO_HUMAN_REVIEWED_GOLD",
              "metric_number_encoding": "finite_decimal_string",
              "seed": seed, "code_sha256": code_sha256,
              "retrieval": _canonical_metric_value(retrieval),
              "classification": _canonical_metric_value(classification)}
    raw = canonical_bytes(record)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()
