"""W8 authenticated/versioned extension of the W5 local review hash chain.

This stores synthetic analyst decisions only. It is not an annotation store,
evaluation gold, a tamper-proof ledger, or a way to edit verified evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from egis_soc.integrity import canonical_bytes
from egis_soc.summarization.review_api import ReviewStore
from egis_soc.w8_demo import run_case


VERSION = "w8-01-authenticated-review-1"
_VERSION_FILE = re.compile(r"version-([0-9]{6})\.json\Z")
_CLAIM_ACTIONS = {"accept_claim", "reject_claim", "request_claim_changes"}
_REPORT_ACTIONS = {"start_review", "request_report_changes",
                   "approve_report", "reject_report", "start_revision", "note"}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_report(report: dict) -> dict:
    """Discard only nondeterministic S3 timing before binding the demo source."""
    record = json.loads(canonical_bytes(report))
    for item in record["repair_verifications"]:
        item["v3_latency_ns"] = 0
    return record


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_new(path: Path, raw: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise FileExistsError("review_snapshot_exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(path, flags, 0o600)
    try:
        if os.write(fd, raw) != len(raw):
            raise OSError("review_snapshot_short_write")
        os.fsync(fd)
    finally:
        os.close(fd)


class AuthenticatedReviewStore(ReviewStore):
    """Use W5's report-bound hash-chain reader with immutable W8 snapshots."""

    def __init__(self, root: Path, report: dict):
        if (type(report) is not dict or report.get("gold_status") != "NOT_GOLD"
                or report.get("w8_demo", {}).get("mode") != "SYNTHETIC_OFFLINE"):
            raise ValueError("synthetic_w8_report_required")
        case = report["w8_demo"]["case"]
        if stable_report(run_case(case)) != stable_report(report):
            raise ValueError("w8_report_source_drift")
        self.base_report = stable_report(report)
        self.source_hash = _sha(canonical_bytes(self.base_report))
        self.report_id = "W8R-" + _sha(canonical_bytes({
            "incident_id": report["incident_id"],
            "tenant_id": report["tenant_id"],
            "mode": "SYNTHETIC_OFFLINE",
        }))[:24]
        root = Path(root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("review_root_must_exist")
        directory = root / self.report_id
        if directory.is_symlink():
            raise ValueError("review_directory_symlink")
        if not directory.exists():
            directory.mkdir(exist_ok=False)
        super().__init__(directory, self.base_report)
        self.lock_path = directory / ".mutation-lock"
        if not (directory / "version-000001.json").exists():
            if any(directory.iterdir()):
                raise ValueError("review_incomplete_initial_state")
            initial = {
                "schema": VERSION, "report_id": self.report_id,
                "report_version": 1, "parent_version": None,
                "created_at_utc": _utc_now(),
                "incident_id": report["incident_id"],
                "tenant_id": report["tenant_id"],
                "source_report_sha256": self.source_hash,
                "report": self.base_report,
                "review": self._empty_review(), "gold_status": "NOT_GOLD",
            }
            _write_new(directory / "version-000001.json", canonical_bytes(initial))
        self.latest()  # Reject a stale, partial or tampered store before serving.

    @staticmethod
    def _empty_review() -> dict:
        return {"status": "DRAFT", "claim_decisions": {}, "notes": [],
                "report_changes_requested": False,
                "decision_reason": None, "decision_by": None}

    def _version_path(self, number: int) -> Path:
        return self.directory / f"version-{number:06d}.json"

    def _transition(self, previous: dict, event: dict) -> dict:
        action = event["action"]
        reason = event["reason"]
        claim_id = event["claim_id"]
        status = previous["review"]["status"]
        if (type(action) is not str or action not in _CLAIM_ACTIONS | _REPORT_ACTIONS
                or type(reason) is not str or not 1 <= len(reason.strip()) <= 4000
                or reason != reason.strip()
                or event["expected_version"] != previous["report_version"]
                or (claim_id is not None and type(claim_id) is not str)
                or (action in _CLAIM_ACTIONS and claim_id is None)
                or (action in _REPORT_ACTIONS and action != "note" and claim_id is not None)):
            raise ValueError("invalid_review_transition")
        all_claims = {item["claim_id"] for item in self.base_report["final_claims"]}
        all_claims.update(item["claim_id"] for item in self.base_report["draft_candidates"])
        final_claims = {item["claim_id"]: item
                        for item in self.base_report["final_claims"]}
        if claim_id is not None and claim_id not in all_claims:
            raise ValueError("foreign_review_claim")
        if action == "accept_claim" and claim_id not in final_claims:
            raise ValueError("cannot_accept_unverified_claim")
        if action == "start_review" and status != "DRAFT":
            raise ValueError("review_not_draft")
        if action == "start_revision" and status not in {"APPROVED", "REJECTED"}:
            raise ValueError("revision_requires_finalized_parent")
        if action not in {"start_review", "start_revision"} and status != "REVIEW_PENDING":
            raise ValueError("review_not_pending")
        if action == "approve_report":
            decisions = previous["review"]["claim_decisions"]
            if (previous["review"]["report_changes_requested"]
                    or any(decisions.get(cid, {}).get("status") != "accepted"
                           for cid in final_claims)):
                raise ValueError("report_not_ready_for_approval")
        snapshot = json.loads(canonical_bytes(previous))
        snapshot["report_version"] = previous["report_version"] + 1
        snapshot["parent_version"] = previous["report_version"]
        snapshot["created_at_utc"] = event["recorded_at_utc"]
        review = snapshot["review"]
        if action == "start_revision":
            snapshot["review"] = self._empty_review()
            review = snapshot["review"]
        elif action == "start_review":
            review["status"] = "REVIEW_PENDING"
        elif action in _CLAIM_ACTIONS:
            decision = {"accept_claim": "accepted", "reject_claim": "rejected",
                        "request_claim_changes": "changes_requested"}[action]
            review["claim_decisions"][claim_id] = {
                "status": decision, "reason": reason,
                "reviewer_id": event["reviewer_id"],
                "recorded_at_utc": event["recorded_at_utc"],
                "audit_record_id": event["audit_record_id"],
            }
        elif action == "note":
            review["notes"].append({"claim_id": claim_id, "text": reason,
                                    "reviewer_id": event["reviewer_id"],
                                    "recorded_at_utc": event["recorded_at_utc"],
                                    "audit_record_id": event["audit_record_id"]})
        elif action == "request_report_changes":
            review["report_changes_requested"] = True
        elif action == "approve_report":
            review["status"] = "APPROVED"
            review["decision_reason"] = reason
            review["decision_by"] = event["reviewer_id"]
        elif action == "reject_report":
            review["status"] = "REJECTED"
            review["decision_reason"] = reason
            review["decision_by"] = event["reviewer_id"]
        if review["status"] != event["new_status"]:
            raise ValueError("review_status_drift")
        return snapshot

    def latest(self, *, allow_lock: bool = False) -> dict:
        if not allow_lock and (self.lock_path.exists() or self.lock_path.is_symlink()):
            raise ValueError("review_mutation_incomplete")
        files = list(self.directory.iterdir())
        if any(item.is_symlink() or not item.is_file() or
               (item.name != self.path.name
                and not (allow_lock and item.name == self.lock_path.name)
                and _VERSION_FILE.fullmatch(item.name) is None)
               for item in files):
            raise ValueError("review_unknown_file")
        numbers = sorted(int(_VERSION_FILE.fullmatch(item.name).group(1))
                         for item in files if _VERSION_FILE.fullmatch(item.name))
        if not numbers or numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("review_version_gap")
        events = self.read()
        if len(events) != len(numbers) - 1:
            raise ValueError("review_audit_version_mismatch")
        previous = None
        for number in numbers:
            raw = self._version_path(number).read_bytes()
            try:
                snapshot = json.loads(raw)
                if raw != canonical_bytes(snapshot):
                    raise ValueError("review_snapshot_not_canonical")
                if (snapshot["schema"] != VERSION
                        or snapshot["report_id"] != self.report_id
                        or snapshot["report_version"] != number
                        or snapshot["parent_version"] != (number - 1 if number > 1 else None)
                        or snapshot["source_report_sha256"] != self.source_hash
                        or snapshot["incident_id"] != self.base_report["incident_id"]
                        or snapshot["tenant_id"] != self.base_report["tenant_id"]
                        or snapshot["report"] != self.base_report
                        or snapshot["gold_status"] != "NOT_GOLD"):
                    raise ValueError("review_snapshot_drift")
                if number == 1:
                    if snapshot["review"] != self._empty_review():
                        raise ValueError("review_initial_state_drift")
                else:
                    event = events[number - 2]
                    audit_id = event.get("audit_record_id")
                    unsigned = {key: value for key, value in event.items()
                                if key != "audit_record_id"}
                    if (audit_id != "W8A-" + _sha(canonical_bytes(unsigned))[:24]
                            or event["identity_status"] != "AUTHENTICATED_LOCAL"
                            or type(event["reviewer_id"]) is not str
                            or not event["reviewer_id"]
                            or event["report_id"] != self.report_id
                            or event["incident_id"] != snapshot["incident_id"]
                            or event["tenant_id"] != snapshot["tenant_id"]
                            or event["report_version"] != number - 1
                            or event["new_report_version"] != number
                            or event["previous_status"] != previous["review"]["status"]
                            or event["source_snapshot_sha256"] != _sha(canonical_bytes(previous))
                            or snapshot != self._transition(previous, event)):
                        raise ValueError("review_audit_snapshot_drift")
                previous = snapshot
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise ValueError("review_snapshot_or_audit_drift") from None
        return previous

    def version(self, number: int) -> dict:
        latest = self.latest()
        if type(number) is not int or not 1 <= number <= latest["report_version"]:
            raise ValueError("unknown_review_version")
        return json.loads(self._version_path(number).read_bytes())

    def act(self, payload: dict, reviewer_id: str) -> tuple[dict, dict]:
        if (type(payload) is not dict
                or set(payload) != {"action", "claim_id", "reason", "expected_version"}
                or type(payload["expected_version"]) is not int
                or type(payload["action"]) is not str
                or type(reviewer_id) is not str or not reviewer_id):
            raise ValueError("invalid_authenticated_review_action")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        lock_fd = os.open(self.lock_path, flags, 0o600)
        try:
            previous = self.latest(allow_lock=True)
            if payload["expected_version"] != previous["report_version"]:
                raise ValueError("stale_review_version")
            events = self.read()
            previous_hash = ("0" * 64 if not events else
                             _sha(canonical_bytes(events[-1])))
            now = _utc_now()
            action = payload["action"]
            new_status = {
                "start_review": "REVIEW_PENDING", "approve_report": "APPROVED",
                "reject_report": "REJECTED", "start_revision": "DRAFT",
            }.get(action, previous["review"]["status"])
            event = {
                "sequence": len(events) + 1,
                "report_sha256": self.report_hash,
                "previous_sha256": previous_hash,
                "recorded_at_utc": now,
                "reviewer_id": reviewer_id,
                "identity_status": "AUTHENTICATED_LOCAL",
                "incident_id": previous["incident_id"],
                "tenant_id": previous["tenant_id"],
                "report_id": self.report_id,
                "report_version": previous["report_version"],
                "new_report_version": previous["report_version"] + 1,
                "source_snapshot_sha256": _sha(canonical_bytes(previous)),
                "action": action, "claim_id": payload["claim_id"],
                "reason": payload["reason"],
                "expected_version": payload["expected_version"],
                "previous_status": previous["review"]["status"],
                "new_status": new_status,
            }
            event["audit_record_id"] = "W8A-" + _sha(canonical_bytes(event))[:24]
            snapshot = self._transition(previous, event)
            _write_new(self._version_path(snapshot["report_version"]),
                       canonical_bytes(snapshot))
            raw = canonical_bytes(event) + b"\n"
            append_flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
            if hasattr(os, "O_BINARY"):
                append_flags |= os.O_BINARY
            fd = os.open(self.path, append_flags, 0o600)
            try:
                if os.write(fd, raw) != len(raw):
                    raise OSError("review_audit_short_write")
                os.fsync(fd)
            finally:
                os.close(fd)
            return snapshot, event
        finally:
            os.close(lock_fd)
            if self.lock_path.exists():
                self.lock_path.unlink()
