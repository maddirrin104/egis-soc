"""Evidence-reference gate matrix; never grants held-out access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VERSION = "w7-readiness-1"
GATES = (
    "source_rights_privacy_approval", "original_incident_run_template_lineage",
    "incident_tenant_boundaries", "independent_human_gold",
    "gold_fact_operational_inventory_separation", "arm_independent_draft_pair_manifest",
    "s2_s3_fork_identity", "split_duplicate_near_duplicate_audit",
    "environment_b_independence", "d032_owner_approval_threshold_lock",
    "model_checkpoint_config_lock", "annotation_blinding_access_audit",
    "statistical_scenario_method_lock", "pretest_ci_calibration",
    "denominator_cluster_eligibility", "heldout_access_authorization",
)
_DENIED = frozenset({"events", "raw_events", "gold", "labels", "predictions",
                     "scores", "test_ids", "ood_ids", "split_ids", "fingerprints"})


def _check_metadata(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.casefold() in _DENIED or "gold" in key.casefold() and key != "independent_human_gold" and key != "gold_fact_operational_inventory_separation":
                raise ValueError("sealed_content_in_readiness_input")
            _check_metadata(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _check_metadata(item)


def check_readiness(findings: Mapping[str, Mapping[str, str]] | None = None) -> dict[str, Any]:
    """Caller-supplied refs require independent verification outside this tool."""
    findings = findings or {}
    _check_metadata(findings)
    if set(findings) - set(GATES):
        raise ValueError("unknown_w7_gate")
    checks = {}
    for name in GATES:
        finding = findings.get(name)
        if finding is None:
            checks[name] = {"status": "PENDING", "reason": "evidence_not_supplied",
                            "evidence_ref": None}
            continue
        if not isinstance(finding, Mapping) or set(finding) - {"status", "reason", "evidence_ref"}:
            raise ValueError("invalid_w7_gate_finding")
        status, reason, ref = finding.get("status"), finding.get("reason"), finding.get("evidence_ref")
        if status not in {"PASS", "FAIL", "PENDING", "UNKNOWN"} or not isinstance(reason, str) or not reason:
            raise ValueError("invalid_w7_gate_finding")
        if status in {"PASS", "FAIL"} and (not isinstance(ref, str) or not ref):
            raise ValueError("gate_disposition_requires_evidence_ref")
        checks[name] = {"status": status, "reason": reason,
                        "evidence_ref": ref if isinstance(ref, str) and ref else None}
    states = {item["status"] for item in checks.values()}
    overall = "BLOCKED" if "FAIL" in states else "PENDING"
    return {"version": VERSION, "status": overall,
            "checks": checks, "heldout_execution_authorized": False,
            "reason": ("failed_gate" if "FAIL" in states else
                       "caller_refs_not_authenticated_or_all_gates_not_complete"),
            "research_claims_authorized": False}
