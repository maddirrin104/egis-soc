"""Development-only repeated-run checks for the pinned V2 NLI baseline."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence

from ..development_data import DevelopmentData
from ..development_v2 import DevelopmentV2, NLIPair


PairInput = tuple[DevelopmentData, NLIPair]


def run_repeated_batch(
    pairs: Sequence[PairInput], model_factory: Callable[[], DevelopmentV2],
    *, score_tolerance: float = 1e-6,
) -> dict:
    """Run the same ordered inputs with two fresh models; never score weak labels."""
    if (not pairs or not math.isfinite(score_tolerance)
            or score_tolerance < 0 or score_tolerance > 1e-3):
        raise ValueError("invalid_v2_qa_batch_or_tolerance")
    ids = [pair.pair_id for _, pair in pairs]
    if len(ids) != len(set(ids)) or any(not pair_id for pair_id in ids):
        raise ValueError("duplicate_or_missing_v2_qa_pair_id")
    if any(pair.gold_status != "NOT_GOLD" for _, pair in pairs):
        raise ValueError("v2_qa_gold_input_forbidden")

    runs = []
    for _ in range(2):
        model = model_factory()
        runs.append(tuple(model.predict(data, pair) for data, pair in pairs))

    cases = []
    largest_delta = 0.0
    for pair_id, first, second in zip(ids, *runs, strict=True):
        if first["pair_id"] != pair_id or second["pair_id"] != pair_id:
            raise ValueError("v2_qa_pair_order_changed")
        for key in ("prediction", "reason", "truncated", "model_called",
                    "model_id", "model_revision", "status", "version"):
            if first[key] != second[key]:
                raise ValueError(f"v2_qa_repeated_{key}_changed")
        if first["scores"] is None or second["scores"] is None:
            if first["scores"] is not None or second["scores"] is not None:
                raise ValueError("v2_qa_repeated_scores_changed")
        else:
            if set(first["scores"]) != set(second["scores"]):
                raise ValueError("v2_qa_repeated_score_labels_changed")
            for label in first["scores"]:
                delta = abs(first["scores"][label] - second["scores"][label])
                if not math.isfinite(delta) or delta > score_tolerance:
                    raise ValueError("v2_qa_repeated_scores_changed")
                largest_delta = max(largest_delta, delta)
        cases.append({"pair_id": pair_id, "prediction": first["prediction"],
                      "truncated": first["truncated"],
                      "model_called": first["model_called"],
                      "scores_first": first["scores"],
                      "scores_second": second["scores"]})

    return {"status": "DEVELOPMENT_DIAGNOSTIC_NOT_GOLD",
            "run_count": 2, "pair_count": len(pairs),
            "prediction_counts": dict(sorted(Counter(
                case["prediction"] for case in cases).items())),
            "truncated_count": sum(case["truncated"] for case in cases),
            "model_called_count": sum(case["model_called"] for case in cases),
            "max_probability_delta": largest_delta,
            "score_tolerance": score_tolerance, "cases": cases,
            "real_f1": "NOT_RUN_NO_HUMAN_REVIEWED_GOLD"}
