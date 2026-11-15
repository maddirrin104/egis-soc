"""Candidate adverse count scenarios; not an approved calibration grid."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from .count_cache import PairCounts, SummaryCounts, _matrix_metrics

VERSION = "w7-adverse-count-scenarios-1"


def _families(sizes: tuple[int, ...], family_by_cluster: tuple[str, ...],
              families: set[str]) -> bool:
    return (bool(sizes) and len(sizes) == len(family_by_cluster)
            and all(type(size) is int and size > 0 for size in sizes)
            and set(family_by_cluster) == families
            and all(family.startswith("SYN_") for family in family_by_cluster))


@dataclass(frozen=True)
class PairCountDesign:
    environment: str
    cluster_sizes: tuple[int, ...]
    family_by_cluster: tuple[str, ...]
    prevalence_by_family: Mapping[str, tuple[float, float, float]]
    errors_by_family: Mapping[str, tuple[float, float]]  # V2, V3
    cluster_dependence: float = 0.0

    def __post_init__(self) -> None:
        if (self.environment not in {"SYN_A", "SYN_B"}
                or not _families(self.cluster_sizes, self.family_by_cluster,
                                 set(self.prevalence_by_family))
                or any(len(probs) != 3 or any(not 0 <= p <= 1 for p in probs)
                       or abs(sum(probs) - 1) > 1e-9
                       for probs in self.prevalence_by_family.values())
                or set(self.errors_by_family) != set(self.prevalence_by_family)
                or not 0 <= self.cluster_dependence <= 1
                or any(len(errors) != 2 or any(not self.cluster_dependence / 2 <= error
                                              <= 1 - self.cluster_dependence / 2
                                              for error in errors)
                       for errors in self.errors_by_family.values())):
            raise ValueError("invalid_pair_count_design")


def generate_pair_counts(design: PairCountDesign, seed: int) -> tuple[PairCounts, ...]:
    """Sample correlated claims within each component; arms share each gold unit."""
    if type(seed) is not int or seed < 0:
        raise ValueError("invalid_scenario_seed")
    rng = random.Random(seed)
    result = []
    for cluster, (size, family) in enumerate(zip(design.cluster_sizes, design.family_by_cluster)):
        shift = (rng.random() - .5) * design.cluster_dependence
        matrix2, matrix3 = [0] * 9, [0] * 9
        for _ in range(size):
            gold = rng.choices(range(3), weights=design.prevalence_by_family[family])[0]
            for arm, matrix in enumerate((matrix2, matrix3)):
                error = design.errors_by_family[family][arm] + shift
                predicted = gold if rng.random() >= error else rng.choice(
                    [label for label in range(3) if label != gold])
                matrix[3 * gold + predicted] += 1
        result.append(PairCounts(f"SYN-C-{design.environment}-{cluster}",
                                 design.environment, tuple(matrix2), tuple(matrix3), family))
    return tuple(result)


def pair_population_truth(design: PairCountDesign) -> dict[str, float | None]:
    """Expected pooled-count contrast, weighted by component size/family."""
    matrices = [[0.0] * 9, [0.0] * 9]
    for size, family in zip(design.cluster_sizes, design.family_by_cluster):
        prevalence = design.prevalence_by_family[family]
        for arm in range(2):
            error = design.errors_by_family[family][arm]
            for gold in range(3):
                for predicted in range(3):
                    matrices[arm][3 * gold + predicted] += size * prevalence[gold] * (
                        1 - error if gold == predicted else error / 2)
    v2, v3 = _matrix_metrics(tuple(matrices[0])), _matrix_metrics(tuple(matrices[1]))
    return {"delta_macro_f1": v3[0] - v2[0] if v3[0] is not None and v2[0] is not None else None,
            "delta_supported_precision": v3[1] - v2[1] if v3[1] is not None and v2[1] is not None else None,
            "fsr_reduction": v2[2] - v3[2] if v2[2] is not None and v3[2] is not None else None}


@dataclass(frozen=True)
class SummaryCountDesign:
    cluster_sizes: tuple[int, ...]  # incidents per component
    family_by_cluster: tuple[str, ...]
    rates_by_family: Mapping[str, tuple[float, float, float, float]]  # CFR2,CFR3,UCR2,UCR3
    facts_per_incident: int
    claims_per_incident: int
    cluster_dependence: float = 0.0

    def __post_init__(self) -> None:
        if (not _families(self.cluster_sizes, self.family_by_cluster,
                          set(self.rates_by_family))
                or min(self.facts_per_incident, self.claims_per_incident) < 1
                or not 0 <= self.cluster_dependence <= 1
                or any(len(rates) != 4 or any(not self.cluster_dependence / 2 <= rate
                                             <= 1 - self.cluster_dependence / 2
                                             for rate in rates)
                       for rates in self.rates_by_family.values())):
            raise ValueError("invalid_summary_count_design")


def generate_summary_counts(design: SummaryCountDesign, seed: int) -> tuple[SummaryCounts, ...]:
    if type(seed) is not int or seed < 0:
        raise ValueError("invalid_scenario_seed")
    rng = random.Random(seed)
    result = []
    for cluster, (incidents, family) in enumerate(zip(design.cluster_sizes,
                                                      design.family_by_cluster)):
        shift = (rng.random() - .5) * design.cluster_dependence
        rates = tuple(rate + shift for rate in design.rates_by_family[family])
        eligible = incidents * design.facts_per_incident
        claims = incidents * design.claims_per_incident
        covered2 = covered3 = unsupported2 = unsupported3 = 0
        for _ in range(eligible):
            draw = rng.random()
            covered2 += draw < rates[0]
            covered3 += draw < rates[1]
        for _ in range(claims):
            unsupported2 += rng.random() < rates[2]
            unsupported3 += rng.random() < rates[3]
        result.append(SummaryCounts(f"SYN-C-RQ2-{cluster}", "SYN_A",
                                    (eligible, eligible, covered2, covered3,
                                     claims, claims, unsupported2, unsupported3)))
    return tuple(result)


def summary_population_truth(design: SummaryCountDesign) -> dict[str, float]:
    total = sum(design.cluster_sizes)
    averages = [sum(size * design.rates_by_family[family][index]
                    for size, family in zip(design.cluster_sizes, design.family_by_cluster)) / total
                for index in range(4)]
    return {"delta_cfr": averages[1] - averages[0],
            "delta_ucr": averages[3] - averages[2]}


def generate_rq3_counts(a: PairCountDesign, b: PairCountDesign,
                        seed: int) -> tuple[PairCounts, ...]:
    if a.environment != "SYN_A" or b.environment != "SYN_B":
        raise ValueError("synthetic_a_b_design_required")
    rng = random.Random(seed)
    return (generate_pair_counts(a, rng.randrange(2**63))
            + generate_pair_counts(b, rng.randrange(2**63)))


def rq3_population_truth(a: PairCountDesign, b: PairCountDesign) -> dict[str, float | None]:
    if a.environment != "SYN_A" or b.environment != "SYN_B":
        raise ValueError("synthetic_a_b_design_required")
    left, right = pair_population_truth(a), pair_population_truth(b)
    return {"advantage_macro_f1": (right["delta_macro_f1"] - left["delta_macro_f1"]
                                   if right["delta_macro_f1"] is not None
                                   and left["delta_macro_f1"] is not None else None),
            "advantage_supported_precision": (
                right["delta_supported_precision"] - left["delta_supported_precision"]
                if right["delta_supported_precision"] is not None
                and left["delta_supported_precision"] is not None else None)}
