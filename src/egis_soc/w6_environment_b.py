"""W6 blinded Environment B metadata screen; no event or label access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VERSION = "w6-b-readiness-1"
REQUIRED = (
    "collection_ref", "source_provenance_ref", "rights_review_ref",
    "acquisition_ref", "collection_pipeline_ref",
    "operator_ref", "collection_dates_ref", "instrumentation_ref",
    "sensors_ref", "schema_ref", "telemetry_sources_ref",
    "incident_boundary_ref", "tenant_boundary_ref",
    "original_incident_lineage_ref", "simulation_run_lineage_ref",
    "template_family_review_ref", "duplicate_audit_ref",
    "near_duplicate_audit_ref", "source_family_review_ref", "audit_evidence_ref",
)
FINDINGS = (
    "operator_independence", "collection_independence", "instrumentation_shift",
    "incident_tenant_boundary", "original_run_overlap", "template_family_overlap",
    "cross_partition_duplicates", "cross_partition_near_duplicates", "rights_clearance",
    "source_family_overlap", "independent_cluster_sufficiency",
)
DENIED = frozenset({"events", "raw_events", "labels", "gold", "predictions", "scores", "test_ids", "ood_ids", "raw", "incident_ids", "split_ids", "fingerprints", "event_hashes"})


def _check_metadata(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.casefold() in DENIED or "gold" in key.casefold():
                raise ValueError("sealed_or_nonmetadata_input")
            _check_metadata(item)
    elif isinstance(value, list):
        for item in value:
            _check_metadata(item)


def audit_environment_b(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Screen custodian-supplied categorical findings, never sealed fingerprints.

    PASS records metadata completeness only. Human approval and W7 seal gates
    are separate, even when every condition passes this screen.
    """
    if not isinstance(candidate, Mapping):
        raise ValueError("invalid_b_metadata")
    _check_metadata(candidate)
    if set(candidate) - (set(REQUIRED) | set(FINDINGS) |
                         {"version", "reviewer_decision", "exclusion_reason"}):
        raise ValueError("unexpected_b_metadata_field")
    if candidate.get("version") != VERSION:
        raise ValueError("invalid_b_metadata_version")
    checks: dict[str, dict[str, str | None]] = {}
    for name in REQUIRED:
        ref = candidate.get(name)
        valid = isinstance(ref, str) and bool(ref.strip())
        checks[name] = {"status": "PASS" if valid else "UNKNOWN",
                        "reason": "evidence_reference_recorded" if valid else "evidence_reference_missing",
                        "evidence_ref": ref if valid else None}
    for name in FINDINGS:
        finding = candidate.get(name)
        if not isinstance(finding, Mapping):
            checks[name] = {"status": "UNKNOWN", "reason": "custodian_finding_missing",
                            "evidence_ref": None}
            continue
        status, reason, ref = finding.get("status"), finding.get("reason"), finding.get("evidence_ref")
        if status not in {"PASS", "FAIL", "PENDING", "UNKNOWN"} or not isinstance(reason, str) or not reason.strip():
            raise ValueError("invalid_b_finding")
        if status in {"PASS", "FAIL"} and (not isinstance(ref, str) or not ref.strip()):
            raise ValueError("finding_requires_audit_evidence")
        checks[name] = {"status": status, "reason": reason,
                        "evidence_ref": ref if isinstance(ref, str) and ref.strip() else None}
    approval = candidate.get("reviewer_decision")
    if not isinstance(approval, Mapping):
        checks["reviewer_decision"] = {"status": "PENDING", "reason": "independent_review_missing",
                                       "evidence_ref": None}
    else:
        status, ref = approval.get("status"), approval.get("evidence_ref")
        if status not in {"PASS", "FAIL", "PENDING", "UNKNOWN"}:
            raise ValueError("invalid_reviewer_decision")
        if status in {"PASS", "FAIL"} and (not isinstance(ref, str) or not ref.strip()):
            raise ValueError("review_decision_requires_evidence")
        checks["reviewer_decision"] = {
            "status": status, "reason": approval.get("reason") or "review_decision_unresolved",
            "evidence_ref": ref if isinstance(ref, str) and ref.strip() else None}
    states = {item["status"] for item in checks.values()}
    overall = "FAIL" if "FAIL" in states else "UNKNOWN" if "UNKNOWN" in states else "PENDING" if "PENDING" in states else "PASS"
    exclusion_reason = candidate.get("exclusion_reason")
    if exclusion_reason is not None and (not isinstance(exclusion_reason, str) or not exclusion_reason.strip()):
        raise ValueError("invalid_exclusion_reason")
    if overall == "FAIL" and not exclusion_reason:
        raise ValueError("failed_candidate_requires_exclusion_reason")
    return {"version": VERSION, "status": overall, "qualification": "NOT_APPROVED_FOR_EVALUATION",
            "checks": checks, "exclusion_reason": exclusion_reason,
            "reviewer_decision_ref": checks["reviewer_decision"]["evidence_ref"]}
