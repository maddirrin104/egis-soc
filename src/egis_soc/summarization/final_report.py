"""W5-07 synthetic analyst packet; automated output never records approval."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from egis_soc.integrity import canonical_bytes

from .s1 import S1Report
from .s2 import ReviewBatch


VERSION = "w5-07-synthetic-final-report-1"
STATUS = "SYNTHETIC_REVIEW_PACKET_NOT_GOLD"
FILES = frozenset({"report.json", "manifest.json"})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _surface_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    paths = {
        "review_api": Path(__file__).with_name("review_api.py"),
        "review_server": root / "scripts" / "w5_review_server.py",
        "review_html": root / "dashboard" / "w5_review.html",
        "review_js": root / "dashboard" / "w5_review.js",
    }
    return {name: _sha(path.read_bytes()) for name, path in paths.items()}


def build_final_report(s1: S1Report, review: ReviewBatch, s2: dict,
                       s3: dict | None, inventory: dict | None,
                       omission: dict | None, fork_bytes: bytes) -> dict:
    """Project verified stage records into a scoped, reviewable packet.

    A missing S3 stage is visible as a failure; no S2 claim is silently
    presented as an S3 final claim. This function does not score gold.
    """
    if type(s1) is not S1Report or type(review) is not ReviewBatch or type(s2) is not dict:
        raise ValueError("w5_07_synthetic_parent_required")
    incident, tenant = s1.incident_id, s1.tenant_id
    ids = set(s1.retrieved_evidence_ids)
    if (s2.get("incident_id") != incident or s2.get("tenant_id") != tenant
            or s2.get("s1_sha256") != _sha(canonical_bytes(s1.to_record()))
            or s2.get("draft_sha256") != s1.draft_sha256
            or s2.get("retrieved_evidence_ids") != list(s1.retrieved_evidence_ids)
            or s2.get("gold_status") != "NOT_GOLD"
            or review.s1_sha256 != s2["s1_sha256"]
            or review.draft_sha256 != s1.draft_sha256
            or tuple(item.claim_id for item in review.candidates) !=
            tuple(item.claim_id for item in s1.claims)
            or not isinstance(fork_bytes, bytes)):
        raise ValueError("w5_07_parent_scope_mismatch")
    stages = {"s1": "AVAILABLE", "s2": "AVAILABLE", "s3": "FAILED_OR_MISSING"}
    if s3 is not None:
        if (type(s3) is not dict or type(inventory) is not dict
                or type(omission) is not dict
                or any(item.get("incident_id") != incident or
                       item.get("tenant_id") != tenant
                       for item in (s3, inventory, omission))
                or s3.get("fork_sha256") != _sha(fork_bytes)
                or s3.get("omission_sha256") != _sha(canonical_bytes(omission))
                or s3.get("inventory_sha256") != _sha(canonical_bytes(inventory))
                or omission.get("fork_sha256") != _sha(fork_bytes)
                or s3.get("s2_final_claim_ids") !=
                [item["claim_id"] for item in s2["final_claims"]]
                or s3.get("gold_status") != "NOT_GOLD"
                or s3.get("cfr_status") != "NOT_SCORED"):
            raise ValueError("w5_07_s3_scope_mismatch")
        stages["s3"] = "AVAILABLE"
    elif inventory is not None or omission is not None:
        raise ValueError("w5_07_partial_s3_input")

    evidence = [asdict(item) for item in s1.evidence]
    if (len(ids) != len(evidence)
            or any(item["incident_id"] != incident or item["tenant_id"] != tenant
                   or item["evidence_id"] not in ids for item in evidence)):
        raise ValueError("w5_07_evidence_scope_mismatch")
    final = [] if s3 is None else s3["final_claims"]
    assessments = {item["claim_id"]: item for item in s2["verification"]}
    if s3 is not None:
        assessments.update((item["assessment"]["claim_id"], item["assessment"])
                           for item in s3["verifications"])
    source_review = {item.claim_id: item for item in review.candidates}
    final_rows = []
    for claim in final:
        cid = claim["claim_id"]
        assessment = assessments.get(cid)
        if (assessment is None or assessment["prediction"] != "supported"
                or assessment["review_required"] or assessment["failure_tag"]
                or claim["prediction"] != "supported" or claim["review_required"]
                or claim["text"] != assessment["text"]
                or claim["citation_ids"] != assessment["citation_ids"]
                or claim["evidence_ids"] != assessment["evidence_ids"]
                or not claim["citation_ids"]
                or not set(claim["citation_ids"]) <= ids
                or not all(check["valid"] for check in assessment["citation_checks"])):
            raise ValueError("w5_07_unverified_final_claim")
        original = source_review.get(claim.get("source_claim_id"))
        citation_support = ("reviewed_supported" if original is not None and
                            original.cited_set_support == "supported" else
                            "reviewed_in_s3_action" if claim.get("origin") ==
                            "S3_REVERIFIED_REPAIR" else "review_required")
        final_rows.append({
            "claim_id": cid, "source_claim_id": claim.get("source_claim_id"),
            "text": claim["text"], "origin": claim.get("origin"),
            "source_fact_id": claim.get("source_fact_id"),
            "prediction": assessment["prediction"],
            "review_required": assessment["review_required"],
            "citation_ids": claim["citation_ids"],
            "citation_validity": assessment["citation_checks"],
            "citation_support_review": citation_support,
            "verification": assessment,
        })
    decisions = {item["source_claim_id"]: item for item in s2["decisions"]}
    candidate_rows = []
    for claim in s1.claims:
        decision = decisions[claim.claim_id]
        check = assessments.get(claim.claim_id)
        candidate_rows.append({
            "claim_id": claim.claim_id, "text": claim.text,
            "section": claim.section, "s2_action": decision["action"],
            "s2_reason": decision["reason"],
            "prediction": None if check is None else check["prediction"],
            "review_required": decision["review_required"],
            "citations": [asdict(item) for item in claim.citations],
            "cited_set_support": claim.cited_set_support,
            "review_reasons": list(claim.review_reasons),
            "verification": check,
        })
    facts = {} if inventory is None else {
        fact["fact_id"]: fact for fact in inventory["facts"]}
    if (inventory is not None and (len(facts) != len(inventory["facts"])
            or {item["fact_id"] for item in omission["findings"]} != set(facts))):
        raise ValueError("w5_07_omission_fact_mismatch")
    omission_rows = [] if omission is None else [
        {**finding, "source_fact": facts[finding["fact_id"]]}
        for finding in omission["findings"]]
    warnings = []
    if not final:
        warnings.append("EMPTY_FINAL_REPORT_REQUIRES_ANALYST_REVIEW")
    if s3 is None:
        warnings.append("S3_STAGE_FAILED_OR_MISSING")
    if any(not claim["citations"] for claim in candidate_rows):
        warnings.append("UNCITED_DRAFT_CLAIM")
    if any(any(not citation["valid_in_scope"] for citation in claim["citations"])
           for claim in candidate_rows):
        warnings.append("INVALID_CITATION")
    if any(claim["cited_set_support"] != "supported" for claim in candidate_rows):
        warnings.append("CITATION_SUPPORT_UNRESOLVED")
    if any(claim["review_required"] for claim in candidate_rows):
        warnings.append("S2_CLAIMS_REQUIRE_REVIEW")
    if any(item["review_required"] for item in omission_rows):
        warnings.append("OPERATIONAL_OMISSIONS_UNADJUDICATED")
    final_by_source = {item.get("source_claim_id"): item for item in final_rows
                       if item.get("source_claim_id") is not None}
    section_names = ("timeline", "affected_entities", "observed_behaviors",
                     "confirmed_outcomes", "uncertainties")
    sections = {name: [final_by_source[source_id]["claim_id"]
                       for source_id in getattr(s1, name)
                       if source_id in final_by_source]
                for name in section_names}
    assigned = {claim_id for values in sections.values() for claim_id in values}
    sections["unclassified"] = [item["claim_id"] for item in final_rows
                                if item["claim_id"] not in assigned]
    structured = {
        "incident_overview": "",  # No unsupported draft sentence is promoted.
        **sections,
        "claims": [item["claim_id"] for item in final_rows],
        "citations": {item["claim_id"]: item["citation_ids"]
                      for item in final_rows},
        "verification_status": "SYNTHETIC_V3_PREDICTIONS_REVIEW_REQUIRED",
        "analyst_notes": [],  # Actual notes live in the separate review log.
    }
    return {
        "version": VERSION, "status": STATUS, "gold_status": "NOT_GOLD",
        "research_result": "NOT_RUN_SYNTHETIC_DEVELOPMENT_ONLY",
        "incident_id": incident, "tenant_id": tenant,
        "draft_sha256": s1.draft_sha256, "fork_sha256": _sha(fork_bytes),
        "structured_report": structured,
        "stage_status": stages, "section_claim_ids": {
            name: list(getattr(s1, name)) for name in
            ("timeline", "affected_entities", "observed_behaviors",
             "confirmed_outcomes", "uncertainties")},
        "original_draft_text": s1.original_draft_text,
        "final_claims": final_rows, "draft_candidates": candidate_rows,
        "evidence": evidence, "omission_findings": omission_rows,
        "repair_history": [] if s3 is None else s3["history"],
        "repair_verifications": [] if s3 is None else s3["verifications"],
        "review_queue": [] if s3 is None else s3["review_queue"],
        "stop_reason": None if s3 is None else s3["stop_reason"],
        "warnings": warnings,
        "analyst_review_status": "SEPARATE_RECORD_REQUIRED",
    }


def create_final_archive(report: dict, parent_manifests: dict[str, bytes],
                         target: Path) -> dict:
    """Create a separate content-addressed packet after upstream verification."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w5_07_archive_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w5_07_archive_parent_required")
    raw = canonical_bytes(report)
    manifest = {"version": VERSION, "status": STATUS,
                "report_sha256": _sha(raw),
                "source_manifest_sha256": {key: _sha(value) for key, value in
                                           sorted(parent_manifests.items())},
                "code_sha256": _sha(Path(__file__).read_bytes()),
                "surface_sha256": _surface_hashes(),
                "gold_status": "NOT_GOLD"}
    target.mkdir(exist_ok=False)
    for name, value in (("report.json", raw),
                        ("manifest.json", canonical_bytes(manifest))):
        with (target / name).open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    return manifest


def verify_final_archive(expected: dict, parent_manifests: dict[str, bytes],
                         target: Path) -> dict:
    target = Path(target)
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} != FILES
            or any((target / name).is_symlink() for name in FILES)):
        raise ValueError("invalid_w5_07_archive_file_set")
    raw = (target / "report.json").read_bytes()
    manifest_raw = (target / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    expected_manifest = {"version": VERSION, "status": STATUS,
                         "report_sha256": _sha(canonical_bytes(expected)),
                         "source_manifest_sha256": {key: _sha(value) for key, value in
                                                    sorted(parent_manifests.items())},
                         "code_sha256": _sha(Path(__file__).read_bytes()),
                         "surface_sha256": _surface_hashes(),
                         "gold_status": "NOT_GOLD"}
    if (raw != canonical_bytes(expected)
            or manifest_raw != canonical_bytes(expected_manifest)
            or manifest != expected_manifest):
        raise ValueError("w5_07_archive_drift")
    return expected
