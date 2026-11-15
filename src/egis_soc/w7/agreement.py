"""Initial two-rater S/C/I agreement; no consensus-label substitution."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from egis_soc.development.matched_evaluation import LABEL_ORDER

VERSION = "w7-agreement-1"


@dataclass(frozen=True)
class InitialJudgment:
    unit_id: str
    incident_id: str
    environment: str
    annotator_id: str
    label: str
    audit_ref: str
    phase: str = "INITIAL_INDEPENDENT"

    def __post_init__(self) -> None:
        if (not self.unit_id or not self.incident_id or not self.environment
                or not self.annotator_id or self.label not in LABEL_ORDER
                or not self.audit_ref or self.phase != "INITIAL_INDEPENDENT"):
            raise ValueError("initial_independent_judgment_required")


def score_agreement(left: tuple[InitialJudgment, ...], right: tuple[InitialJudgment, ...], *,
                    unresolved_unit_ids: frozenset[str] = frozenset(),
                    ac1_sensitivity: bool = True) -> dict[str, Any]:
    if (not left or len(left) != len(right) or type(left) is not tuple or type(right) is not tuple
            or len({item.unit_id for item in left}) != len(left)
            or len({item.unit_id for item in right}) != len(right)
            or {item.unit_id for item in left} != {item.unit_id for item in right}
            or len({item.annotator_id for item in left}) != 1
            or len({item.annotator_id for item in right}) != 1
            or left[0].annotator_id == right[0].annotator_id
            or not unresolved_unit_ids <= {item.unit_id for item in left}):
        raise ValueError("invalid_independent_annotation_alignment")
    by_right = {item.unit_id: item for item in right}
    matrix = {a: {b: 0 for b in LABEL_ORDER} for a in LABEL_ORDER}
    incidents: dict[str, int] = {}
    environments: dict[str, int] = {}
    for item in left:
        other = by_right[item.unit_id]
        if (item.incident_id != other.incident_id or item.environment != other.environment
                or item.annotator_id == other.annotator_id):
            raise ValueError("misaligned_annotation_unit")
        matrix[item.label][other.label] += 1
        incidents[item.incident_id] = incidents.get(item.incident_id, 0) + 1
        environments[item.environment] = environments.get(item.environment, 0) + 1
    n = len(left)
    agreement = sum(matrix[label][label] for label in LABEL_ORDER) / n
    p_left = {label: sum(matrix[label].values()) / n for label in LABEL_ORDER}
    p_right = {label: sum(matrix[a][label] for a in LABEL_ORDER) / n for label in LABEL_ORDER}
    expected = sum(p_left[label] * p_right[label] for label in LABEL_ORDER)
    kappa = (agreement - expected) / (1 - expected) if expected < 1 else None
    pooled = {label: (p_left[label] + p_right[label]) / 2 for label in LABEL_ORDER}
    ac1_expected = sum(p * (1 - p) for p in pooled.values()) / (len(LABEL_ORDER) - 1)
    ac1 = (agreement - ac1_expected) / (1 - ac1_expected) if ac1_expected < 1 else None
    return {"version": VERSION, "scope": "INITIAL_INDEPENDENT_ONLY",
            "unit_count": n, "annotator_refs": [left[0].annotator_id, right[0].annotator_id],
            "audit_refs": sorted({item.audit_ref for item in (*left, *right)}),
            "cross_tabulation": matrix, "raw_agreement": agreement,
            "cohens_kappa": {"value": kappa,
                              "na_reason": "EXPECTED_AGREEMENT_ONE" if kappa is None else None},
            "gwet_ac1_sensitivity": ({"value": ac1,
                                      "na_reason": "AC1_UNDEFINED" if ac1 is None else None}
                                     if ac1_sensitivity else None),
            "prevalence_left": p_left, "prevalence_right": p_right,
            "disagreement_count": n - sum(matrix[label][label] for label in LABEL_ORDER),
            "unresolved_adjudications": len(unresolved_unit_ids),
            "incident_count": len(incidents), "pairs_by_environment": environments,
            "absent_class_warning": any(p_left[label] == 0 or p_right[label] == 0
                                        for label in LABEL_ORDER),
            "real_agreement_status": "NOT_MEASURED"}
