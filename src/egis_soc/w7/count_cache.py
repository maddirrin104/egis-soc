"""Immutable per-lineage count arrays for synthetic bootstrap calibration."""

from __future__ import annotations

from dataclasses import dataclass

from egis_soc.development.matched_evaluation import LABEL_ORDER

from .metrics import PairUnit, SummaryIncident

INDEX = {label: index for index, label in enumerate(LABEL_ORDER)}


@dataclass(frozen=True)
class PairCounts:
    lineage_component: str
    environment: str
    v2: tuple[int, ...]  # 3x3 gold-row/predicted-column matrix
    v3: tuple[int, ...]
    source_family: str = "SYN_UNSPECIFIED_FAMILY"


@dataclass(frozen=True)
class SummaryCounts:
    lineage_component: str
    environment: str
    counts: tuple[int, ...]  # eligible, covered S2/S3, claims, unsupported S2/S3


def cache_pairs(units: tuple[PairUnit, ...]) -> tuple[PairCounts, ...]:
    if not units:
        raise ValueError("empty_pair_cache_input")
    grouped: dict[tuple[str, str], list[PairUnit]] = {}
    for unit in units:
        grouped.setdefault((unit.environment, unit.lineage_component), []).append(unit)
    result = []
    for (environment, component), group in sorted(grouped.items()):
        matrices = []
        for arm in ("v2", "v3"):
            counts = [0] * 9
            for unit in group:
                attempt = getattr(unit.row, arm)
                counts[3 * INDEX[unit.row.expected] + INDEX[attempt.prediction]] += 1
            matrices.append(tuple(counts))
        families = {unit.source_family for unit in group}
        result.append(PairCounts(component, environment, *matrices,
                                 next(iter(families)) if len(families) == 1 else "SYN_MIXED_FAMILY"))
    if len({item.lineage_component for item in result}) != len(result):
        raise ValueError("component_crosses_environments")
    return tuple(result)


def cache_summaries(units: tuple[SummaryIncident, ...]) -> tuple[SummaryCounts, ...]:
    if not units:
        raise ValueError("empty_summary_cache_input")
    grouped: dict[str, list[SummaryIncident]] = {}
    for unit in units:
        grouped.setdefault(unit.lineage_component, []).append(unit)
    result = []
    for component, group in sorted(grouped.items()):
        counts = [0] * 8
        for item in group:
            for arm, offset in (("s2", 0), ("s3", 1)):
                if getattr(item, f"{arm}_status") == "FAILED":
                    continue
                facts = [fact for fact in item.facts if fact.eligible]
                claims = getattr(item, f"{arm}_claims")
                counts[offset] += len(facts)
                counts[2 + offset] += sum(getattr(fact, f"covered_{arm}") for fact in facts)
                counts[4 + offset] += len(claims)
                counts[6 + offset] += sum(claim.support != "supported" for claim in claims)
        result.append(SummaryCounts(component, "SYN_A", tuple(counts)))
    return tuple(result)


def _matrix_metrics(matrix: tuple[int, ...]) -> tuple[float | None, float | None, float | None]:
    f1 = []
    for index in range(3):
        tp = matrix[3 * index + index]
        gold = sum(matrix[3 * index:3 * index + 3])
        predicted = sum(matrix[3 * row + index] for row in range(3))
        denominator = gold + predicted
        f1.append(2 * tp / denominator if denominator else None)
    macro = sum(f1) / 3 if all(value is not None for value in f1) else None
    predicted_s = sum(matrix[3 * row] for row in range(3))
    sp = matrix[0] / predicted_s if predicted_s else None
    nonsupport = sum(matrix[3:])
    fsr = (matrix[3] + matrix[6]) / nonsupport if nonsupport else None
    return macro, sp, fsr


def _sum_matrices(items: tuple[PairCounts, ...], arm: str) -> tuple[int, ...]:
    return tuple(sum(getattr(item, arm)[index] for item in items) for index in range(9))


def cached_rq1_endpoints(items: tuple[PairCounts, ...]) -> dict[str, float | None]:
    v2, v3 = _matrix_metrics(_sum_matrices(items, "v2")), _matrix_metrics(_sum_matrices(items, "v3"))
    return {"delta_macro_f1": v3[0] - v2[0] if v3[0] is not None and v2[0] is not None else None,
            "delta_supported_precision": v3[1] - v2[1] if v3[1] is not None and v2[1] is not None else None,
            "fsr_reduction": v2[2] - v3[2] if v2[2] is not None and v3[2] is not None else None}


def cached_rq2_endpoints(items: tuple[SummaryCounts, ...]) -> dict[str, float | None]:
    counts = [sum(item.counts[index] for item in items) for index in range(8)]
    cfr2 = counts[2] / counts[0] if counts[0] else None
    cfr3 = counts[3] / counts[1] if counts[1] else None
    ucr2 = counts[6] / counts[4] if counts[4] else None
    ucr3 = counts[7] / counts[5] if counts[5] else None
    return {"delta_cfr": cfr3 - cfr2 if cfr2 is not None and cfr3 is not None else None,
            "delta_ucr": ucr3 - ucr2 if ucr2 is not None and ucr3 is not None else None}


def cached_rq3_endpoints(items: tuple[PairCounts, ...]) -> dict[str, float | None]:
    values = {}
    for environment in ("SYN_A", "SYN_B"):
        subset = tuple(item for item in items if item.environment == environment)
        if not subset:
            raise ValueError("missing_synthetic_environment")
        values[environment] = {arm: _matrix_metrics(_sum_matrices(subset, arm))
                               for arm in ("v2", "v3")}
    result = {}
    for name, index in (("advantage_macro_f1", 0), ("advantage_supported_precision", 1)):
        a2, a3 = values["SYN_A"]["v2"][index], values["SYN_A"]["v3"][index]
        b2, b3 = values["SYN_B"]["v2"][index], values["SYN_B"]["v3"][index]
        result[name] = (a2 - b2) - (a3 - b3) if all(
            value is not None for value in (a2, a3, b2, b3)) else None
    return result
