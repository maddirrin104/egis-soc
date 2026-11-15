"""Protocol-shaped descriptive metrics over explicitly synthetic fixed units."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from egis_soc.development.matched_evaluation import (
    LABEL_ORDER, MatchedRow, _arm_metrics, score_matched,
)

VERSION = "w7-synthetic-metrics-1"
DELTA_UCR = 0.03  # Approved methodological pooled-rate margin; not a safety guarantee.


def rate(numerator: int, denominator: int, *, reason: str) -> dict[str, Any]:
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError("invalid_metric_counts")
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator,
            "na_reason": None if denominator else reason}


@dataclass(frozen=True)
class PairUnit:
    row: MatchedRow
    lineage_component: str
    environment: str
    source_family: str = "SYN_UNSPECIFIED_FAMILY"
    source_collection: str = "SYN_UNSPECIFIED_COLLECTION"

    def __post_init__(self) -> None:
        if (not isinstance(self.row, MatchedRow)
                or self.row.gold_provenance != "SYNTHETIC_KNOWN_ANSWER"
                or not self.lineage_component or self.environment not in {"SYN_A", "SYN_B"}
                or not isinstance(self.source_family, str)
                or not self.source_family.startswith("SYN_")
                or not isinstance(self.source_collection, str)
                or not self.source_collection.startswith("SYN_")):
            raise ValueError("w7_synthetic_pair_required")


def _enrich_arm(rows: tuple[MatchedRow, ...], arm: str) -> dict[str, Any]:
    raw = _arm_metrics(rows, arm)
    by_class = {}
    for label in LABEL_ORDER:
        counts = raw["by_class"][label]
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        by_class[label] = {**counts,
                           "precision": rate(tp, tp + fp, reason="NO_PREDICTED_CLASS"),
                           "recall": rate(tp, tp + fn, reason="NO_GOLD_CLASS"),
                           "f1_metric": rate(2 * tp, 2 * tp + fp + fn,
                                             reason="ABSENT_GOLD_AND_PREDICTED_CLASS")}
    s = by_class["supported"]
    false_support = raw["false_support_numerator"]
    fsr_denominator = raw["false_support_denominator_proposed"]
    return {**raw, "by_class": by_class,
            "macro_f1_metric": {"value": raw["macro_f1"], "denominator": 3,
                                "na_reason": "ABSENT_CLASS" if raw["macro_f1"] is None else None},
            "supported_precision_metric": rate(s["tp"], s["predicted_count"],
                                               reason="NO_PREDICTED_SUPPORTED"),
            "supported_recall_metric": rate(s["tp"], s["gold_count"],
                                            reason="NO_GOLD_SUPPORTED"),
            "false_support_rate_metric": rate(false_support, fsr_denominator,
                                              reason="NO_GOLD_NON_SUPPORTED"),
            "review_rate_metric": rate(raw["review_count"], len(rows), reason="NO_ATTEMPTED_PAIRS"),
            "failure_rate_metric": rate(raw["failure_count"], len(rows), reason="NO_ATTEMPTED_PAIRS")}


def score_pairs(units: tuple[PairUnit, ...]) -> dict[str, Any]:
    """Reuse W4 count scorer; add explicit NA and incident/lineage reporting."""
    if (type(units) is not tuple or not units
            or any(not isinstance(unit, PairUnit) for unit in units)
            or len({unit.row.pair_id for unit in units}) != len(units)
            or len({unit.environment for unit in units}) != 1):
        raise ValueError("invalid_w7_pair_population")
    rows = tuple(unit.row for unit in units)
    base = score_matched(rows)
    per_incident = {}
    for incident_id in sorted({row.incident_id for row in rows}):
        subset = tuple(row for row in rows if row.incident_id == incident_id)
        components = {unit.lineage_component for unit in units if unit.row.incident_id == incident_id}
        if len(components) != 1:
            raise ValueError("incident_split_across_lineage_components")
        per_incident[incident_id] = {"lineage_component": next(iter(components)),
                                     "attempted_pairs": len(subset),
                                     "source_families": sorted({unit.source_family for unit in units
                                                                if unit.row.incident_id == incident_id}),
                                     "arms": {arm: _enrich_arm(subset, arm) for arm in ("V2", "V3")}}
    def breakdown(attribute: str) -> dict[str, Any]:
        return {name: {"attempted_pairs": sum(getattr(unit, attribute) == name for unit in units),
                       "independent_components": len({unit.lineage_component for unit in units
                                                      if getattr(unit, attribute) == name}),
                       "arms": {arm: _enrich_arm(tuple(unit.row for unit in units
                                                        if getattr(unit, attribute) == name), arm)
                                for arm in ("V2", "V3")}}
                for name in sorted({getattr(unit, attribute) for unit in units})}
    return {"version": VERSION, "scope": "SYNTHETIC_DESCRIPTIVE_ONLY",
            "environment": units[0].environment, "attempted_pairs": len(rows),
            "independent_components": len({unit.lineage_component for unit in units}),
            "arms": {arm: _enrich_arm(rows, arm) for arm in ("V2", "V3")},
            "per_incident": per_incident,
            "per_source_family": breakdown("source_family"),
            "per_source_collection": breakdown("source_collection"),
            "w4_source_version": base["version"],
            "input_sha256_by_pair": base["input_sha256_by_pair"],
            "confirmatory_eligible": False,
            "fsr_denominator_status": "PROPOSED_AWAITING_PRETEST_APPROVAL"}


def rq1_differences(units: tuple[PairUnit, ...]) -> dict[str, float | None]:
    score = score_pairs(units)["arms"]
    def difference(key: str, left: str, right: str) -> float | None:
        a, b = score[left][key]["value"], score[right][key]["value"]
        return a - b if a is not None and b is not None else None
    return {"delta_macro_f1": difference("macro_f1_metric", "V3", "V2"),
            "delta_supported_precision": difference("supported_precision_metric", "V3", "V2"),
            "fsr_reduction": difference("false_support_rate_metric", "V2", "V3")}


def rq3_drops(a: tuple[PairUnit, ...], b: tuple[PairUnit, ...]) -> dict[str, Any]:
    if not a or not b or any(unit.environment != "SYN_A" for unit in a) or any(
            unit.environment != "SYN_B" for unit in b):
        raise ValueError("rq3_environment_separation_required")
    if {unit.row.pair_id for unit in a} & {unit.row.pair_id for unit in b}:
        raise ValueError("cross_environment_pair_overlap")
    if {unit.lineage_component for unit in a} & {unit.lineage_component for unit in b}:
        raise ValueError("cross_environment_lineage_overlap")
    scores = {"A": score_pairs(a), "B": score_pairs(b)}
    drops = {}
    for arm in ("V2", "V3"):
        drops[arm] = {}
        for name, key in (("macro_f1", "macro_f1_metric"),
                          ("supported_precision", "supported_precision_metric")):
            va = scores["A"]["arms"][arm][key]["value"]
            vb = scores["B"]["arms"][arm][key]["value"]
            drops[arm][name] = va - vb if va is not None and vb is not None else None
    advantages = {}
    for name in ("macro_f1", "supported_precision"):
        v2, v3 = drops["V2"][name], drops["V3"][name]
        advantages[name] = v2 - v3 if v2 is not None and v3 is not None else None
    b_fsr = {arm: scores["B"]["arms"][arm]["false_support_rate_metric"]
             for arm in ("V2", "V3")}
    return {"scope": "SYNTHETIC_NOT_INDEPENDENT_OOD", "environments": scores,
            "drops": drops, "advantages": advantages,
            "b_fsr": b_fsr, "confirmatory_eligible": False}


@dataclass(frozen=True)
class SummaryClaim:
    claim_id: str
    text: str
    support: str
    citation_validity: tuple[bool, ...] = ()
    citation_relevance: tuple[bool, ...] = ()
    cited_set_supports_all_atoms: bool = False
    unsupported_s2_predecessor: bool | None = None

    def __post_init__(self) -> None:
        if (not self.claim_id or not self.text or self.support not in LABEL_ORDER
                or len(self.citation_validity) != len(self.citation_relevance)
                or any(type(value) is not bool for value in
                       (*self.citation_validity, *self.citation_relevance))
                or type(self.cited_set_supports_all_atoms) is not bool):
            raise ValueError("invalid_synthetic_claim")


@dataclass(frozen=True)
class SummaryFact:
    fact_id: str
    source_ref: str
    eligible: bool
    covered_s2: bool
    covered_s3: bool

    def __post_init__(self) -> None:
        if (not self.fact_id or not self.source_ref.startswith("synthetic:")
                or any(type(value) is not bool for value in
                       (self.eligible, self.covered_s2, self.covered_s3))
                or not self.eligible and (self.covered_s2 or self.covered_s3)):
            raise ValueError("invalid_synthetic_fact")


@dataclass(frozen=True)
class RepairDiagnostics:
    rounds: int
    attempted_actions: int
    verified_actions: int
    reverify_failures: int
    stop_reason: str

    def __post_init__(self) -> None:
        if (any(type(value) is not int or value < 0 for value in
                (self.rounds, self.attempted_actions, self.verified_actions,
                 self.reverify_failures))
                or self.rounds > 2 or self.verified_actions > self.attempted_actions
                or self.reverify_failures > self.attempted_actions
                or self.verified_actions + self.reverify_failures > self.attempted_actions
                or not self.stop_reason):
            raise ValueError("invalid_synthetic_repair_diagnostic")


@dataclass(frozen=True)
class SummaryIncident:
    incident_id: str
    lineage_component: str
    s2_fork_sha256: str
    s3_fork_sha256: str
    s2_status: str
    s3_status: str
    facts: tuple[SummaryFact, ...]
    s2_claims: tuple[SummaryClaim, ...]
    s3_claims: tuple[SummaryClaim, ...]
    s2_tokens: int | None = None
    s3_tokens: int | None = None
    s3_repair: RepairDiagnostics | None = None

    def __post_init__(self) -> None:
        if (not self.incident_id or not self.lineage_component
                or len(self.s2_fork_sha256) != 64
                or self.s2_fork_sha256 != self.s3_fork_sha256
                or self.s2_status not in {"VALID", "EMPTY", "FAILED"}
                or self.s3_status not in {"VALID", "EMPTY", "FAILED"}
                or any(status != "VALID" and claims for status, claims in
                       ((self.s2_status, self.s2_claims), (self.s3_status, self.s3_claims)))
                or any((self.s2_status == "EMPTY" and fact.covered_s2)
                       or (self.s3_status == "EMPTY" and fact.covered_s3)
                       for fact in self.facts)
                or len({fact.fact_id for fact in self.facts}) != len(self.facts)
                or len({claim.claim_id for claim in self.s2_claims}) != len(self.s2_claims)
                or len({claim.claim_id for claim in self.s3_claims}) != len(self.s3_claims)
                or any(value is not None and (type(value) is not int or value < 0)
                       for value in (self.s2_tokens, self.s3_tokens))
                or (self.s3_repair is not None and not isinstance(self.s3_repair, RepairDiagnostics))):
            raise ValueError("invalid_synthetic_summary_incident")


def score_summaries(incidents: tuple[SummaryIncident, ...], *,
                    _resampled: bool = False) -> dict[str, Any]:
    if (type(incidents) is not tuple or not incidents
            or any(not isinstance(item, SummaryIncident) for item in incidents)
            or (not _resampled and len({item.incident_id for item in incidents}) != len(incidents))):
        raise ValueError("invalid_summary_population")
    per_incident = {}
    arms = {}
    for arm in ("s2", "s3"):
        valid = [item for item in incidents if getattr(item, f"{arm}_status") != "FAILED"]
        facts = [fact for item in valid for fact in item.facts if fact.eligible]
        covered = sum(getattr(fact, f"covered_{arm}") for fact in facts)
        claims = [claim for item in valid for claim in getattr(item, f"{arm}_claims")]
        unsupported = sum(claim.support != "supported" for claim in claims)
        cited = [claim for claim in claims if claim.citation_validity]
        refs = [reference for claim in claims for reference in claim.citation_validity]
        citation_supported = sum(claim.support == "supported" and
                                 claim.cited_set_supports_all_atoms and
                                 all(claim.citation_validity) and
                                 all(claim.citation_relevance) for claim in cited)
        introduced = sum(claim.support != "supported" and
                         claim.unsupported_s2_predecessor is False for claim in claims) if arm == "s3" else None
        ambiguous = sum(claim.support != "supported" and
                        claim.unsupported_s2_predecessor is None for claim in claims) if arm == "s3" else None
        arms[arm.upper()] = {
            "attempted_incidents": len(incidents), "valid_incidents": len(valid),
            "failed_incidents": len(incidents) - len(valid),
            "empty_incidents": sum(getattr(item, f"{arm}_status") == "EMPTY" for item in incidents),
            "cfr": rate(covered, len(facts), reason="NO_ELIGIBLE_CRITICAL_FACTS"),
            "omission_rate": rate(len(facts) - covered, len(facts), reason="NO_ELIGIBLE_CRITICAL_FACTS"),
            "ucr": rate(unsupported, len(claims), reason="NO_FACTUAL_CLAIMS"),
            "citation_validity": rate(sum(refs), len(refs), reason="NO_CITATIONS"),
            "csa": rate(citation_supported, len(cited), reason="NO_CITED_FACTUAL_CLAIMS"),
            "unsupported_count": unsupported, "factual_claim_count": len(claims),
            "uncited_claim_count": len(claims) - len(cited),
            "invalid_citation_count": len(refs) - sum(refs),
            "introduced_unsupported_count": introduced,
            "ambiguous_predecessor_count": ambiguous,
            "claim_char_count": sum(len(claim.text) for claim in claims),
            "measured_token_count": (sum(getattr(item, f"{arm}_tokens") for item in valid
                                         if getattr(item, f"{arm}_tokens") is not None)
                                     if any(getattr(item, f"{arm}_tokens") is not None for item in valid)
                                     else None),
            "token_measurement_coverage": sum(getattr(item, f"{arm}_tokens") is not None for item in valid),
            "repair_diagnostics": ({"measured_incidents": sum(item.s3_repair is not None
                                                                  for item in incidents),
                                    "rounds": (sum(item.s3_repair.rounds for item in incidents
                                                   if item.s3_repair is not None)
                                               if any(item.s3_repair is not None for item in incidents) else None),
                                    "attempted_actions": (sum(item.s3_repair.attempted_actions
                                                              for item in incidents if item.s3_repair is not None)
                                                          if any(item.s3_repair is not None for item in incidents) else None),
                                    "verified_actions": (sum(item.s3_repair.verified_actions
                                                             for item in incidents if item.s3_repair is not None)
                                                         if any(item.s3_repair is not None for item in incidents) else None),
                                    "reverify_failures": (sum(item.s3_repair.reverify_failures
                                                              for item in incidents if item.s3_repair is not None)
                                                          if any(item.s3_repair is not None for item in incidents) else None)}
                                   if arm == "s3" else None),
        }
    for item in incidents:
        local_arms = {}
        for arm in ("s2", "s3"):
            status = getattr(item, f"{arm}_status")
            claims = getattr(item, f"{arm}_claims")
            eligible = [fact for fact in item.facts if fact.eligible]
            if status == "FAILED":
                local_arms[arm.upper()] = {"status": status,
                    "facts_eligible": len(eligible), "factual_count": None,
                    "unsupported_count": None,
                    "cfr": {"value": None, "numerator": None,
                            "denominator": len(eligible), "na_reason": "FAILED_REPORT"},
                    "ucr": {"value": None, "numerator": None,
                            "denominator": None, "na_reason": "FAILED_REPORT"},
                    "csa": {"value": None, "numerator": None,
                            "denominator": None, "na_reason": "FAILED_REPORT"}}
                continue
            cited = [claim for claim in claims if claim.citation_validity]
            csa_count = sum(claim.support == "supported" and
                            claim.cited_set_supports_all_atoms and
                            all(claim.citation_validity) and
                            all(claim.citation_relevance) for claim in cited)
            local_arms[arm.upper()] = {"status": status,
                "facts_eligible": len(eligible), "factual_count": len(claims),
                "unsupported_count": sum(c.support != "supported" for c in claims),
                "cfr": rate(sum(getattr(fact, f"covered_{arm}") for fact in eligible),
                            len(eligible), reason="NO_ELIGIBLE_CRITICAL_FACTS"),
                "ucr": rate(sum(claim.support != "supported" for claim in claims),
                            len(claims), reason="NO_FACTUAL_CLAIMS"),
                "csa": rate(csa_count, len(cited), reason="NO_CITED_FACTUAL_CLAIMS")}
        per_incident[item.incident_id] = {"lineage_component": item.lineage_component,
                                          "arms": local_arms,
                                          "s3_repair": (item.s3_repair.__dict__
                                                        if item.s3_repair is not None else None)}
    cfr2, cfr3 = arms["S2"]["cfr"]["value"], arms["S3"]["cfr"]["value"]
    ucr2, ucr3 = arms["S2"]["ucr"]["value"], arms["S3"]["ucr"]["value"]
    return {"version": VERSION, "scope": "SYNTHETIC_DESCRIPTIVE_ONLY",
            "arms": arms, "per_incident": per_incident,
            "delta_cfr": cfr3 - cfr2 if cfr2 is not None and cfr3 is not None else None,
            "delta_ucr": ucr3 - ucr2 if ucr2 is not None and ucr3 is not None else None,
            "approved_methodological_ucr_margin": DELTA_UCR,
            "confirmatory_eligible": False,
            "blocking_empty_or_failed": any(item.s2_status != "VALID" or item.s3_status != "VALID"
                                            for item in incidents)}
