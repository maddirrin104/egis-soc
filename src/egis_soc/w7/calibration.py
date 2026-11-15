"""Monte Carlo calibration scaffold; smoke runs never satisfy the W7 gate."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from scipy.stats import beta

from .bootstrap import bootstrap_intervals

T = TypeVar("T")
VERSION = "w7-calibration-smoke-1"
OFFICIAL_OUTER = 1_000
OFFICIAL_INNER = 10_000
MIN_USABLE_COVERAGE_LOWER = .93
MAX_TYPE_I_UPPER = .07
REQUIRED_METHODS = {
    "RQ1": {"delta_macro_f1": "two_sided", "delta_supported_precision": "two_sided",
            "fsr_reduction": "two_sided"},
    "RQ2": {"delta_cfr": "lower", "delta_ucr": "upper"},
    "RQ3": {"advantage_macro_f1": "two_sided",
            "advantage_supported_precision": "two_sided"},
}


def exact_binomial_bounds(successes: int, trials: int, *, alpha: float = .05) -> dict[str, float]:
    """One-sided exact Clopper-Pearson bounds for Monte Carlo proportions."""
    if (type(successes) is not int or type(trials) is not int or trials < 1
            or not 0 <= successes <= trials or not 0 < alpha < 1):
        raise ValueError("invalid_binomial_counts")
    lower = 0.0 if successes == 0 else float(beta.ppf(alpha, successes, trials - successes + 1))
    upper = 1.0 if successes == trials else float(beta.ppf(1 - alpha, successes + 1, trials - successes))
    return {"lower": lower, "upper": upper}


@dataclass(frozen=True)
class Scenario:
    name: str
    rq: str
    truth: Mapping[str, float]
    methods: Mapping[str, str]
    hypothesis: str  # COMPOSITE_NULL or TRUE_H1
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if (not self.name or self.rq not in {"RQ1", "RQ2", "RQ3"}
                or self.hypothesis not in {"COMPOSITE_NULL", "TRUE_H1"}
                or dict(self.methods) != REQUIRED_METHODS.get(self.rq)
                or set(self.truth) != set(self.methods)
                or any(not isinstance(value, (int, float)) or not math.isfinite(value)
                       for value in self.truth.values())
                or any(method not in {"two_sided", "lower", "upper"}
                       for method in self.methods.values())):
            raise ValueError("invalid_calibration_scenario")


def _claim_passes(rq: str, endpoints: Mapping[str, Any]) -> bool:
    if any(item["interval"] is None for item in endpoints.values()):
        return False
    if rq == "RQ2":
        return (endpoints["delta_cfr"]["interval"]["lower"] > 0
                and endpoints["delta_ucr"]["interval"]["upper"] < .03)
    return all(item["interval"]["lower"] > 0 for item in endpoints.values())


def run_smoke(scenario: Scenario, *, generator: Callable[[int], tuple[T, ...]],
              evaluator: Callable[[tuple[T, ...]], Mapping[str, float | None]],
              outer: int = 3, inner: int = 30, seed: int = 0,
              stratum_of: Callable[[T], str] | None = None,
              stop_after: int | None = None,
              resume_from: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Small engineering probe; official 1000 x 10000 grid is deliberately separate."""
    if (not isinstance(scenario, Scenario) or type(outer) is not int or not 1 <= outer < OFFICIAL_OUTER
            or type(inner) is not int or not 1 <= inner < OFFICIAL_INNER
            or type(seed) is not int or seed < 0):
        raise ValueError("smoke_budget_only")
    if stop_after is not None and (type(stop_after) is not int or not 1 <= stop_after <= outer):
        raise ValueError("invalid_smoke_stop")
    planned = stop_after if stop_after is not None else outer
    signature = hashlib.sha256(json.dumps({"name": scenario.name, "rq": scenario.rq,
        "truth": dict(scenario.truth), "methods": dict(scenario.methods),
        "hypothesis": scenario.hypothesis, "parameters": dict(scenario.parameters)},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    root = random.Random(seed)
    seed_pairs = [(root.randrange(2**63), root.randrange(2**63)) for _ in range(outer)]
    records = list(resume_from.get("records", ())) if resume_from is not None else []
    if resume_from is not None and (
            resume_from.get("scenario_signature") != signature
            or resume_from.get("seed") != seed or resume_from.get("outer") != outer
            or resume_from.get("inner") != inner or len(records) > planned
            or any(record.get("index") != index
                   or (record.get("dataset_seed"), record.get("bootstrap_seed")) != seed_pairs[index]
                   for index, record in enumerate(records))):
        raise ValueError("resume_plan_or_seed_mismatch")
    start = time.perf_counter_ns()
    for index in range(len(records), planned):
        dataset_seed, bootstrap_seed = seed_pairs[index]
        try:
            units = generator(dataset_seed)
            result = bootstrap_intervals(units, evaluator=evaluator, methods=scenario.methods,
                                         repetitions=inner, seed=bootstrap_seed,
                                         stratum_of=stratum_of)
            coverage = {}
            for name, truth in scenario.truth.items():
                interval = result["endpoints"][name]["interval"]
                if interval is None:
                    coverage[name] = False
                else:
                    low, high = interval["lower"], interval["upper"]
                    coverage[name] = ((low is None or low <= truth)
                                      and (high is None or truth <= high))
            undefined = {name: result["endpoints"][name]["na_reason"]
                         for name in scenario.methods if result["endpoints"][name]["interval"] is None}
            full_claim_pass = _claim_passes(scenario.rq, result["endpoints"])
        except Exception as error:
            coverage = {name: False for name in scenario.methods}
            undefined = {name: f"ENGINEERING_EXCEPTION_{type(error).__name__}" for name in scenario.methods}
            full_claim_pass = False
        records.append({"index": index, "dataset_seed": dataset_seed,
                        "bootstrap_seed": bootstrap_seed,
                        "coverage": coverage, "full_claim_pass": full_claim_pass,
                        "undefined": undefined})
    elapsed = time.perf_counter_ns() - start
    attempted = len(records)
    endpoint_summary = {}
    for name in scenario.methods:
        usable = sum(record["coverage"][name] for record in records)
        defined = sum(name not in record["undefined"] for record in records)
        conditional = sum(record["coverage"][name] for record in records if name not in record["undefined"])
        endpoint_summary[name] = {"usable_coverage": usable / attempted,
                                  "usable_successes": usable, "outer_datasets": attempted,
                                  "defined_datasets": defined,
                                  "conditional_coverage": conditional / defined if defined else None,
                                  "exact_lower_for_usable": (exact_binomial_bounds(usable, outer)["lower"]
                                                             if attempted == outer else None),
                                  "undefined_count": attempted - defined}
    full_pass = sum(record["full_claim_pass"] for record in records)
    return {"version": VERSION, "status": ("ENGINEERING_SMOKE_NOT_CALIBRATION"
                                           if attempted == outer else "PARTIAL_ENGINEERING_SMOKE"),
            "scenario": {"name": scenario.name, "rq": scenario.rq,
                         "truth": dict(scenario.truth), "methods": dict(scenario.methods),
                         "hypothesis": scenario.hypothesis, "parameters": dict(scenario.parameters)},
            "scenario_signature": signature, "seed": seed, "outer": outer, "inner": inner,
            "endpoint_summary": endpoint_summary,
            "false_full_claim_count": full_pass if scenario.hypothesis == "COMPOSITE_NULL" else None,
            "type_i_upper_exact": (exact_binomial_bounds(full_pass, outer)["upper"]
                                   if scenario.hypothesis == "COMPOSITE_NULL" and attempted == outer else None),
            "power_diagnostic": full_pass / outer if scenario.hypothesis == "TRUE_H1" and attempted == outer else None,
            "elapsed_ns": elapsed, "records": records,
            "official_work_estimate": {"outer_per_scenario": OFFICIAL_OUTER,
                                       "inner_per_dataset": OFFICIAL_INNER,
                                       "count_reaggregations_per_scenario": OFFICIAL_OUTER * OFFICIAL_INNER,
                                       "rough_linear_seconds_from_smoke": (
                                           elapsed / (max(1, attempted - (len(resume_from.get("records", ())) if resume_from else 0)) * inner)
                                           * OFFICIAL_OUTER * OFFICIAL_INNER / 1e9),
                                       "projection_limit": "linear_extrapolation_from_tiny_smoke_not_official_grid"},
            "calibration_gate": "NOT_RUN_NO_SCENARIO_LOCK"}


def synthetic_pair_generator(*, clusters: int, pairs_per_cluster: int,
                             prevalence: tuple[float, float, float],
                             v2_error: float, v3_error: float,
                             environment: str = "SYN_A") -> Callable[[int], tuple[Any, ...]]:
    """Authored toy data generator; no LLM/NLI and no gold record creation."""
    if (clusters < 1 or pairs_per_cluster < 1 or len(prevalence) != 3
            or abs(sum(prevalence) - 1) > 1e-9
            or any(p < 0 for p in prevalence)
            or not 0 <= v2_error <= 1 or not 0 <= v3_error <= 1
            or environment not in {"SYN_A", "SYN_B"}):
        raise ValueError("invalid_synthetic_generator_config")
    from egis_soc.development.matched_evaluation import ArmAttempt, MatchedRow, LABEL_ORDER
    from .metrics import PairUnit

    def generate(seed: int) -> tuple[Any, ...]:
        rng = random.Random(seed)
        result = []
        for cluster in range(clusters):
            for index in range(pairs_per_cluster):
                gold = rng.choices(LABEL_ORDER, weights=prevalence)[0]
                def attempt(error: float) -> ArmAttempt:
                    wrong = [label for label in LABEL_ORDER if label != gold]
                    prediction = gold if rng.random() >= error else rng.choice(wrong)
                    return ArmAttempt(prediction, False, "SYNTHETIC_GENERATOR")
                pair_id = f"{environment}-{cluster}-{index}"
                row = MatchedRow(pair_id, f"SYN-I-{environment}-{cluster}", gold,
                                 hashlib.sha256(pair_id.encode()).hexdigest(),
                                 attempt(v2_error), attempt(v3_error))
                result.append(PairUnit(row, f"SYN-C-{environment}-{cluster}", environment,
                                       f"SYN_FAMILY_{cluster % 2}",
                                       f"SYN_COLLECTION_{environment}_{cluster}"))
        return tuple(result)
    return generate


def population_truth(*, prevalence: tuple[float, float, float],
                     v2_error: float, v3_error: float) -> dict[str, float]:
    """Analytical infinite-population RQ1 contrasts for the toy generator."""
    from egis_soc.development.matched_evaluation import LABEL_ORDER
    def metrics(error: float) -> tuple[float, float, float]:
        matrix = [[prevalence[i] * ((1 - error) if i == j else error / 2)
                   for j in range(3)] for i in range(3)]
        f1 = sum(2 * matrix[i][i] / (prevalence[i] + sum(matrix[j][i] for j in range(3)))
                 for i in range(3)) / 3
        sp = matrix[0][0] / sum(matrix[j][0] for j in range(3))
        fsr = (matrix[1][0] + matrix[2][0]) / (prevalence[1] + prevalence[2])
        return f1, sp, fsr
    if (len(prevalence) != len(LABEL_ORDER) or min(prevalence) <= 0
            or abs(sum(prevalence) - 1) > 1e-9):
        raise ValueError("invalid_population_truth_config")
    v2, v3 = metrics(v2_error), metrics(v3_error)
    return {"delta_macro_f1": v3[0] - v2[0],
            "delta_supported_precision": v3[1] - v2[1],
            "fsr_reduction": v2[2] - v3[2]}


def synthetic_summary_generator(*, clusters: int, incidents_per_cluster: int,
                                facts_per_incident: int, claims_per_incident: int,
                                cfr_s2: float, cfr_s3: float,
                                ucr_s2: float, ucr_s3: float,
                                cluster_dependence: float = 0) -> Callable[[int], tuple[Any, ...]]:
    """Paired toy facts/claims with known marginal CFR and UCR contrasts."""
    probabilities = (cfr_s2, cfr_s3, ucr_s2, ucr_s3)
    if (min(clusters, incidents_per_cluster, facts_per_incident, claims_per_incident) < 1
            or not 0 <= cluster_dependence <= 1
            or any(not cluster_dependence / 2 <= p <= 1 - cluster_dependence / 2
                   for p in probabilities)):
        raise ValueError("invalid_summary_scenario_config")
    from .metrics import SummaryClaim, SummaryFact, SummaryIncident

    def generate(seed: int) -> tuple[Any, ...]:
        rng = random.Random(seed)
        results = []
        for cluster in range(clusters):
            shift = (rng.random() - .5) * cluster_dependence
            for incident in range(incidents_per_cluster):
                facts = []
                for index in range(facts_per_incident):
                    draw = rng.random()
                    facts.append(SummaryFact(f"F{index}", f"synthetic:{cluster}:{incident}:{index}",
                                             True, draw < cfr_s2 + shift,
                                             draw < cfr_s3 + shift))
                arm_claims = {}
                for arm, risk in (("s2", ucr_s2), ("s3", ucr_s3)):
                    claims = []
                    for index in range(claims_per_incident):
                        unsupported = rng.random() < risk + shift
                        claims.append(SummaryClaim(f"{arm}-{index}", f"synthetic claim {index}",
                                                   "insufficient" if unsupported else "supported",
                                                   (True,), (True,), not unsupported,
                                                   False if arm == "s3" and unsupported else None))
                    arm_claims[arm] = tuple(claims)
                results.append(SummaryIncident(f"SYN-I-{cluster}-{incident}", f"SYN-C-{cluster}",
                                               "a" * 64, "a" * 64, "VALID", "VALID",
                                               tuple(facts), arm_claims["s2"], arm_claims["s3"]))
        return tuple(results)
    return generate


def synthetic_rq3_generator(*, clusters_a: int, clusters_b: int,
                            pairs_per_cluster: int,
                            prevalence_a: tuple[float, float, float],
                            prevalence_b: tuple[float, float, float],
                            errors_a: tuple[float, float],
                            errors_b: tuple[float, float]) -> Callable[[int], tuple[Any, ...]]:
    """Two separately seeded *synthetic* environments, never an actual B."""
    a = synthetic_pair_generator(clusters=clusters_a, pairs_per_cluster=pairs_per_cluster,
                                 prevalence=prevalence_a, v2_error=errors_a[0],
                                 v3_error=errors_a[1], environment="SYN_A")
    b = synthetic_pair_generator(clusters=clusters_b, pairs_per_cluster=pairs_per_cluster,
                                 prevalence=prevalence_b, v2_error=errors_b[0],
                                 v3_error=errors_b[1], environment="SYN_B")
    def generate(seed: int) -> tuple[Any, ...]:
        rng = random.Random(seed)
        return a(rng.randrange(2**63)) + b(rng.randrange(2**63))
    return generate


def rq3_population_truth(*, prevalence_a: tuple[float, float, float],
                         prevalence_b: tuple[float, float, float],
                         errors_a: tuple[float, float],
                         errors_b: tuple[float, float]) -> dict[str, float]:
    a = population_truth(prevalence=prevalence_a, v2_error=errors_a[0], v3_error=errors_a[1])
    b = population_truth(prevalence=prevalence_b, v2_error=errors_b[0], v3_error=errors_b[1])
    return {"advantage_macro_f1": b["delta_macro_f1"] - a["delta_macro_f1"],
            "advantage_supported_precision": (b["delta_supported_precision"]
                                              - a["delta_supported_precision"])}
