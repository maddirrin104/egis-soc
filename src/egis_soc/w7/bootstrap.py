"""Paired lineage-component bootstrap over synthetic count-bearing units."""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from egis_soc.development.matched_evaluation import _arm_metrics

from .metrics import PairUnit, SummaryIncident, score_summaries

T = TypeVar("T")
VERSION = "w7-lineage-bootstrap-1"


def _percentile(values: list[float], q: float) -> float:
    """Type-7 empirical percentile; implementation choice pending final lock."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def rq1_endpoints(units: tuple[PairUnit, ...]) -> dict[str, float | None]:
    rows = tuple(unit.row for unit in units)
    left, right = _arm_metrics(rows, "V2"), _arm_metrics(rows, "V3")
    def diff(key: str, reverse: bool = False) -> float | None:
        a, b = left[key], right[key]
        return ((a - b) if reverse else (b - a)) if a is not None and b is not None else None
    return {"delta_macro_f1": diff("macro_f1"),
            "delta_supported_precision": diff("supported_precision"),
            "fsr_reduction": diff("false_support_rate_proposed", True)}


def rq2_endpoints(units: tuple[SummaryIncident, ...]) -> dict[str, float | None]:
    result = score_summaries(units, _resampled=True)
    return {"delta_cfr": result["delta_cfr"], "delta_ucr": result["delta_ucr"]}


def rq3_endpoints(units: tuple[PairUnit, ...]) -> dict[str, float | None]:
    scores = {}
    for environment in ("SYN_A", "SYN_B"):
        rows = tuple(unit.row for unit in units if unit.environment == environment)
        scores[environment] = {arm: _arm_metrics(rows, arm) for arm in ("V2", "V3")}
    result = {}
    for name, key in (("advantage_macro_f1", "macro_f1"),
                      ("advantage_supported_precision", "supported_precision")):
        values = [scores[env][arm][key] for env in ("SYN_A", "SYN_B")
                  for arm in ("V2", "V3")]
        result[name] = ((values[0] - values[2]) - (values[1] - values[3])) if all(
            value is not None for value in values) else None
    return result


def bootstrap_intervals(units: tuple[T, ...], *,
                        evaluator: Callable[[tuple[T, ...]], Mapping[str, float | None]],
                        methods: Mapping[str, str], repetitions: int = 10_000,
                        seed: int = 0,
                        stratum_of: Callable[[T], str] | None = None) -> dict[str, Any]:
    """Resample complete components within strata using common indices per endpoint.

    Never produces a confirmatory decision. The 10-unit and 5%-invalid checks
    are proposed necessary conditions and remain subject to calibration/lock.
    """
    if (type(units) is not tuple or not units or type(repetitions) is not int
            or repetitions < 1 or type(seed) is not int or seed < 0 or not methods
            or any(method not in {"two_sided", "lower", "upper"} for method in methods.values())):
        raise ValueError("invalid_bootstrap_plan")
    if stratum_of is None:
        stratum_of = lambda _: "single"
    strata: dict[str, dict[str, list[T]]] = {}
    for unit in units:
        component = getattr(unit, "lineage_component", None)
        stratum = stratum_of(unit)
        if not isinstance(component, str) or not component or not isinstance(stratum, str) or not stratum:
            raise ValueError("missing_lineage_or_stratum")
        strata.setdefault(stratum, {}).setdefault(component, []).append(unit)
    if len({component for groups in strata.values() for component in groups}) != sum(
            len(groups) for groups in strata.values()):
        raise ValueError("component_crosses_strata")
    observed = dict(evaluator(units))
    if set(observed) != set(methods):
        raise ValueError("endpoint_plan_mismatch")
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {name: [] for name in methods}
    invalid: dict[str, Counter[str]] = {name: Counter() for name in methods}
    ordered = {stratum: tuple(sorted(groups)) for stratum, groups in sorted(strata.items())}
    for _ in range(repetitions):
        draw: list[T] = []
        for stratum, names in ordered.items():
            for _ in names:
                draw.extend(strata[stratum][names[rng.randrange(len(names))]])
        estimates = evaluator(tuple(draw))
        if set(estimates) != set(methods):
            raise ValueError("endpoint_plan_mismatch")
        for name, value in estimates.items():
            if value is None or not math.isfinite(value):
                invalid[name]["UNDEFINED_REPLICATE"] += 1
            else:
                samples[name].append(value)
    cluster_counts = {stratum: len(names) for stratum, names in ordered.items()}
    endpoints = {}
    for name, method in methods.items():
        observed_value = observed[name]
        invalid_count = sum(invalid[name].values())
        reason = ("UNDEFINED_OBSERVED" if observed_value is None or not math.isfinite(observed_value)
                  else "FEWER_THAN_10_INDEPENDENT_COMPONENTS" if any(count < 10 for count in cluster_counts.values())
                  else "INVALID_REPLICATES_AT_LEAST_5_PERCENT" if invalid_count * 20 >= repetitions
                  else None)
        values = samples[name]
        bound = None
        if reason is None:
            if method == "two_sided":
                bound = {"lower": _percentile(values, .025), "upper": _percentile(values, .975)}
            elif method == "lower":
                bound = {"lower": _percentile(values, .05), "upper": None}
            else:
                bound = {"lower": None, "upper": _percentile(values, .95)}
        endpoints[name] = {"observed": observed_value, "method": method,
                           "interval": bound, "status": "NA" if reason else "EXPLORATORY_INTERVAL",
                           "na_reason": reason, "valid_replicates": len(values),
                           "invalid_replicates": invalid_count,
                           "invalid_reasons": dict(invalid[name])}
    return {"version": VERSION, "scope": "SYNTHETIC_EXPLORATORY_ONLY",
            "seed": seed, "repetitions": repetitions, "cluster_counts": cluster_counts,
            "endpoints": endpoints, "confirmatory_eligible": False,
            "percentile_method": "linear_type7_pending_pretest_lock"}
