"""W5-08 offline replay of the fixed synthetic W5 archive chain.

The replay re-derives retrieval and checks saved stage contracts. It never
regenerates text, reruns NLI, accesses evaluation gold, or scores RQ2 metrics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from egis_soc.integrity import canonical_bytes

from .atomization import verify_claim_archive
from .contract import RetrievedIncident, retrieve_synthetic_incident
from .final_report import build_final_report, verify_final_archive
from .generation import GenerationConfig, verify_archive
from .omission import verify_omission_archive
from .s1 import verify_s1_archive
from .s2 import ReviewBatch, read_common_fork, verify_s2_archive
from .s3 import RepairPlan, verify_s3_archive


VERSION = "w5-08-synthetic-offline-qa-1"
STATUS = "SYNTHETIC_DEVELOPMENT_QA_NOT_GOLD"
STAGES = ("retrieval", "generation", "claims", "s1", "s2", "fork_identity",
          "omission", "s3", "final")
FILES = frozenset({"qa_report.json", "manifest.json"})
_SAFE_ERROR = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,99}\Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ReplaySources:
    generation: Path
    claims: Path
    s1: Path
    s2: Path
    omission: Path
    s3: Path
    final: Path

    def paths(self) -> dict[str, Path]:
        return {name: Path(getattr(self, name)) for name in
                ("generation", "claims", "s1", "s2", "omission", "s3", "final")}


def _source_hashes(sources: ReplaySources) -> dict[str, str | None]:
    result = {}
    for name, directory in sources.paths().items():
        path = directory / "manifest.json"
        result[name] = (_sha(path.read_bytes()) if directory.is_dir()
                        and not directory.is_symlink() and path.is_file()
                        and not path.is_symlink() else None)
    return result


def _retrieval_record(context: RetrievedIncident) -> dict:
    by_id = {event.evidence_id: event for event in context.events}
    return {"incident_id": context.bundle.incident_id,
            "tenant_id": context.bundle.tenant_id,
            "query": context.query,
            "evidence": [{"evidence_id": hit.evidence_id,
                          "passage": hit.passage, "source_ref": hit.source_ref,
                          "timestamp_utc": hit.timestamp_utc,
                          "raw_sha256": by_id[hit.evidence_id].provenance.sha256}
                         for hit in context.hits]}


def _error_code(error: Exception) -> str:
    message = str(error)
    return message if _SAFE_ERROR.fullmatch(message) else "UNSPECIFIED_CHECK_FAILURE"


def replay_synthetic_chain(context: RetrievedIncident, config: GenerationConfig,
                           review: ReviewBatch, plan: RepairPlan,
                           backend_binding: dict[str, str],
                           sources: ReplaySources) -> dict:
    """Check each stage in order; a failed parent blocks its descendants."""
    if (type(context) is not RetrievedIncident
            or type(config) is not GenerationConfig
            or type(review) is not ReviewBatch or type(plan) is not RepairPlan
            or type(sources) is not ReplaySources
            or type(backend_binding) is not dict):
        raise TypeError("w5_08_synthetic_inputs_required")
    paths = sources.paths()
    state: dict = {}
    stages: list[dict] = []
    status: dict[str, str] = {}

    def check(name: str, dependencies: tuple[str, ...], action: Callable[[], dict]) -> None:
        blocked = [item for item in dependencies if status[item] != "PASS"]
        if blocked:
            stage = {"stage": name, "status": "BLOCKED",
                     "blocked_by": blocked, "error_code": None, "details": {}}
        else:
            try:
                details = action()
                stage = {"stage": name, "status": "PASS", "blocked_by": [],
                         "error_code": None, "details": details}
            except Exception as error:
                stage = {"stage": name, "status": "FAIL", "blocked_by": [],
                         "error_code": _error_code(error),
                         "details": {"exception_type": type(error).__name__}}
        stages.append(stage)
        status[name] = stage["status"]

    def retrieval() -> dict:
        fresh = retrieve_synthetic_incident(
            context.bundle, context.events, query=context.query,
            limit=len(context.hits))
        if fresh.hits != context.hits or fresh.evidence_ids != context.evidence_ids:
            raise ValueError("w5_08_retrieval_replay_drift")
        raw = canonical_bytes(_retrieval_record(fresh))
        state["retrieval_raw"] = raw
        return {"retrieval_sha256": _sha(raw),
                "evidence_ids": list(fresh.evidence_ids),
                "hit_count": len(fresh.hits)}

    def generation() -> dict:
        generated = verify_archive(context, config, paths["generation"])
        state["generation"] = generated
        return {"draft_id": generated.draft_id,
                "response_sha256": generated.response_sha256,
                "config_sha256": generated.config_sha256}

    def claims() -> dict:
        result = verify_claim_archive(
            context, config, paths["generation"], paths["claims"])
        if (result.draft.draft_id != state["generation"].draft_id
                or result.draft.text != state["generation"].text):
            raise ValueError("w5_08_draft_claim_identity_drift")
        state["claims"] = result
        return {"draft_sha256": result.draft.sha256,
                "claim_ids": [item.claim_id for item in result.draft.claims],
                "review_reason_count": result.review_count}

    def s1() -> dict:
        report = verify_s1_archive(
            context, config, paths["generation"], paths["claims"], paths["s1"])
        if report.draft_sha256 != state["claims"].draft.sha256:
            raise ValueError("w5_08_s1_draft_identity_drift")
        state["s1"] = report
        return {"s1_sha256": _sha(canonical_bytes(report.to_record())),
                "claim_count": len(report.claims),
                "citation_count": sum(len(item.citations) for item in report.claims)}

    def s2() -> dict:
        report = verify_s2_archive(
            context, config, paths["generation"], paths["claims"],
            paths["s1"], review, backend_binding, paths["s2"])
        if ((paths["s2"] / "retrieval.json").read_bytes()
                != state["retrieval_raw"]):
            raise ValueError("w5_08_retrieval_archive_drift")
        state["s2"] = report
        return {"verification_count": len(report["verification"]),
                "final_claim_ids": [item["claim_id"] for item in report["final_claims"]],
                "decision_reasons": [item["reason"] for item in report["decisions"]]}

    def fork_identity() -> dict:
        args = (context, config, paths["generation"], paths["claims"],
                paths["s1"], review, backend_binding, paths["s2"])
        s2_fork = read_common_fork(*args, arm="S2")
        s3_fork = read_common_fork(*args, arm="S3")
        if (s2_fork != s3_fork
                or s2_fork != (paths["s2"] / "fork.json").read_bytes()
                or json.loads(s2_fork).get("operational_inventory_status")
                != "NOT_ACCESSED_S2"):
            raise ValueError("w5_08_fork_identity_drift")
        state["fork"] = s2_fork
        return {"same_fork_bytes": True, "fork_sha256": _sha(s2_fork),
                "s2_inventory_status": "NOT_ACCESSED_S2"}

    def omission() -> dict:
        report = verify_omission_archive(
            context, config, paths["generation"], paths["claims"],
            paths["s1"], review, backend_binding, paths["s2"],
            paths["omission"])
        inventory = json.loads((paths["omission"] / "inventory.json").read_bytes())
        if (report["fork_sha256"] != _sha(state["fork"])
                or report["gold_status"] != "NOT_GOLD"
                or report["cfr_status"] != "NOT_SCORED"):
            raise ValueError("w5_08_omission_boundary_drift")
        state["omission"], state["inventory"] = report, inventory
        return {"fact_candidate_count": len(inventory["facts"]),
                "review_finding_count": sum(item["review_required"] for item in
                                            report["findings"]),
                "cfr_status": report["cfr_status"]}

    def s3() -> dict:
        report = verify_s3_archive(
            context, config, paths["generation"], paths["claims"],
            paths["s1"], review, backend_binding, paths["s2"],
            paths["omission"], plan, paths["s3"])
        if (report["fork_sha256"] != _sha(state["fork"])
                or report["s2_final_claim_ids"] !=
                [item["claim_id"] for item in state["s2"]["final_claims"]]
                or report["gold_status"] != "NOT_GOLD"
                or report["cfr_status"] != "NOT_SCORED"):
            raise ValueError("w5_08_s3_fork_or_gold_drift")
        state["s3"] = report
        return {"executed_rounds": report["executed_rounds"],
                "stop_reason": report["stop_reason"],
                "final_claim_ids": [item["claim_id"] for item in report["final_claims"]],
                "review_queue_count": len(report["review_queue"]),
                "s3_v3_calls": report["s3_only_cost"]["v3_calls"]}

    def final() -> dict:
        report = build_final_report(
            state["s1"], review, state["s2"], state["s3"],
            state["inventory"], state["omission"], state["fork"])
        parents = {name: (paths[name] / "manifest.json").read_bytes()
                   for name in ("s1", "s2", "omission", "s3")}
        verify_final_archive(report, parents, paths["final"])
        if (report["fork_sha256"] != _sha(state["fork"])
                or [item["claim_id"] for item in report["final_claims"]] !=
                [item["claim_id"] for item in state["s3"]["final_claims"]]
                or report["gold_status"] != "NOT_GOLD"
                or report["analyst_review_status"] != "SEPARATE_RECORD_REQUIRED"):
            raise ValueError("w5_08_final_lineage_drift")
        state["final"] = report
        return {"final_claim_count": len(report["final_claims"]),
                "warning_codes": report["warnings"],
                "review_queue_count": len(report["review_queue"])}

    for name, deps, action in (
            ("retrieval", (), retrieval),
            ("generation", ("retrieval",), generation),
            ("claims", ("generation",), claims),
            ("s1", ("claims",), s1),
            ("s2", ("s1",), s2),
            ("fork_identity", ("s2",), fork_identity),
            ("omission", ("fork_identity",), omission),
            ("s3", ("omission",), s3),
            ("final", ("s3",), final)):
        check(name, deps, action)

    negative = []
    if "s2" in state:
        negative.extend("S2_" + item["prediction"].upper()
                        for item in state["s2"]["verification"]
                        if item["prediction"] != "supported")
        if any(item["action"] == "abstain" for item in state["s2"]["decisions"]):
            negative.append("S2_ABSTAINED_CLAIM")
    if "omission" in state and any(
            item["outcome"] == "candidate_unmentioned"
            for item in state["omission"]["findings"]):
        negative.append("OPERATIONAL_CANDIDATE_UNMENTIONED_NOT_GOLD")
    if "s3" in state and state["s3"]["executed_rounds"] == 0:
        negative.append("S3_ZERO_REPAIR_ROUNDS")
    if "final" in state and not state["final"]["final_claims"]:
        negative.append("EMPTY_FINAL_REPORT")

    return {"version": VERSION, "status": STATUS,
            "incident_id": context.bundle.incident_id,
            "tenant_id": context.bundle.tenant_id,
            "config": config.record, "config_sha256": config.sha256,
            "backend_binding_sha256": _sha(canonical_bytes(backend_binding)),
            "review_sha256": _sha(canonical_bytes(review.to_record())),
            "plan_sha256": _sha(canonical_bytes(plan.to_record())),
            "source_manifest_sha256": _source_hashes(sources),
            "stage_checks": stages,
            "overall": "PASS" if all(item["status"] == "PASS"
                                     for item in stages) else "FAIL",
            "negative_findings": negative,
            "identity": ({"status": "VERIFIED",
                          "fork_sha256": _sha(state["fork"]),
                          "s2_s3_same_fork_bytes": True,
                          "s3_uses_s2_final_ids": True,
                          "final_uses_s3_claim_ids": True}
                         if all(name in state for name in
                                ("fork", "s2", "s3", "final"))
                         else {"status": "NOT_VERIFIED"}),
            "gold_status": "NOT_GOLD",
            "rq2_metrics_status": "NOT_SCORED",
            "research_result": "NOT_RUN_SYNTHETIC_DEVELOPMENT_ONLY"}


def _manifest(report_raw: bytes, source_hashes: dict) -> dict:
    root = Path(__file__).resolve().parents[3]
    return {"version": VERSION, "status": STATUS,
            "report_sha256": _sha(report_raw),
            "source_manifest_sha256": source_hashes,
            "qa_code_sha256": _sha(Path(__file__).read_bytes()),
            "cli_code_sha256": _sha((root / "scripts" / "w5_synthetic_qa.py").read_bytes()),
            "gold_status": "NOT_GOLD",
            "research_result": "NOT_RUN_SYNTHETIC_DEVELOPMENT_ONLY"}


def create_qa_archive(report: dict, target: Path) -> dict:
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w5_08_archive_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w5_08_archive_parent_required")
    report_raw = canonical_bytes(report)
    manifest = _manifest(report_raw, report["source_manifest_sha256"])
    target.mkdir(exist_ok=False)
    for name, raw in (("qa_report.json", report_raw),
                      ("manifest.json", canonical_bytes(manifest))):
        with (target / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return manifest


def verify_qa_archive(expected_report: dict, target: Path) -> dict:
    target = Path(target)
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} != FILES
            or any((target / name).is_symlink() or not (target / name).is_file()
                   for name in FILES)):
        raise ValueError("invalid_w5_08_archive_file_set")
    report_raw = canonical_bytes(expected_report)
    expected_manifest = canonical_bytes(_manifest(
        report_raw, expected_report["source_manifest_sha256"]))
    if ((target / "qa_report.json").read_bytes() != report_raw
            or (target / "manifest.json").read_bytes() != expected_manifest):
        raise ValueError("w5_08_archive_drift")
    return expected_report
