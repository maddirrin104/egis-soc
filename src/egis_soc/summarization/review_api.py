"""Local W5-07 synthetic review API with separate, explicit review events."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from egis_soc.integrity import canonical_bytes

from .final_report import STATUS, VERSION


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ReviewStore:
    """Append-only hash chain for self-attested local review actions."""

    def __init__(self, directory: Path, report: dict):
        self.directory = Path(directory)
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise ValueError("review_directory_must_exist")
        if report.get("version") != VERSION or report.get("status") != STATUS:
            raise ValueError("synthetic_report_required")
        self.report = report
        self.report_hash = _sha(canonical_bytes(report))
        self.path = self.directory / ("review-" + self.report_hash + ".jsonl")

    def read(self) -> list[dict]:
        if self.path.is_symlink():
            raise ValueError("review_log_symlink")
        if not self.path.exists():
            return []
        content = self.path.read_bytes()
        if content and not content.endswith(b"\n"):
            raise ValueError("review_log_drift")
        events = []
        previous = "0" * 64
        for raw in content.splitlines():
            try:
                event = json.loads(raw)
                if (raw != canonical_bytes(event).rstrip(b"\n")
                        or event["report_sha256"] != self.report_hash
                        or event["previous_sha256"] != previous
                        or event["sequence"] != len(events) + 1):
                    raise ValueError("review_log_drift")
                previous = _sha(raw)
                events.append(event)
            except (ValueError, KeyError, TypeError):
                raise ValueError("review_log_drift") from None
        return events

    def append(self, payload: dict) -> dict:
        if type(payload) is not dict or set(payload) != {
                "reviewer_id", "action", "claim_id", "text", "confirm_approval"}:
            raise ValueError("invalid_review_action")
        reviewer = payload["reviewer_id"]
        action = payload["action"]
        claim_id = payload["claim_id"]
        value = payload["text"]
        confirm = payload["confirm_approval"]
        ids = {item["claim_id"] for item in self.report["final_claims"]}
        ids.update(item["claim_id"] for item in self.report["draft_candidates"])
        if (type(reviewer) is not str or not 1 <= len(reviewer.strip()) <= 100
                or reviewer != reviewer.strip() or type(value) is not str
                or len(value) > 4000 or type(confirm) is not bool
                or action not in {"note", "correction", "approve", "request_changes"}
                or (action == "correction" and
                    (claim_id not in ids or not value.strip() or confirm))
                or (action in {"note", "request_changes"} and
                    (claim_id is not None or not value.strip() or confirm))
                or (action == "approve" and
                    (claim_id is not None or not confirm or not value.strip()))):
            raise ValueError("invalid_review_action")
        events = self.read()
        previous = "0" * 64 if not events else _sha(
            canonical_bytes(events[-1]).rstrip(b"\n"))
        event = {"sequence": len(events) + 1,
                 "report_sha256": self.report_hash,
                 "previous_sha256": previous,
                 "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                 "reviewer_id": reviewer, "identity_status": "SELF_ATTESTED_LOCAL",
                 "action": action, "claim_id": claim_id, "text": value,
                 "explicit_approval": action == "approve" and confirm}
        raw = canonical_bytes(event) + b"\n"
        if self.path.is_symlink():
            raise ValueError("review_log_symlink")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(self.path, flags, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        return event


class ReviewApp:
    def __init__(self, report: dict, store: ReviewStore, token: str,
                 html: bytes, javascript: bytes):
        if (store.report_hash != _sha(canonical_bytes(report))
                or type(token) is not str or len(token) < 32):
            raise ValueError("invalid_review_app_binding")
        self.report = report
        self.store = store
        self.token = token
        self.html = html
        self.javascript = javascript

    def __call__(self, environ: dict, start_response: Callable):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")

        def respond(status: str, body: bytes, content_type: str):
            start_response(status, [("Content-Type", content_type),
                                    ("Content-Length", str(len(body))),
                                    ("Cache-Control", "no-store"),
                                    ("X-Content-Type-Options", "nosniff")])
            return [body]

        if method == "GET" and path in {"/", "/review.js"}:
            content = self.html if path == "/" else self.javascript
            kind = "text/html; charset=utf-8" if path == "/" else \
                   "application/javascript; charset=utf-8"
            return respond("200 OK", content, kind)
        if path not in {"/api/report", "/api/reviews"}:
            return respond("404 Not Found", b"not found", "text/plain")
        header = environ.get("HTTP_AUTHORIZATION", "")
        if not hmac.compare_digest(header, "Bearer " + self.token):
            return respond("403 Forbidden", b"forbidden", "text/plain")
        try:
            if method == "GET" and path == "/api/report":
                return respond("200 OK", canonical_bytes(self.report), "application/json")
            if method == "GET" and path == "/api/reviews":
                return respond("200 OK", canonical_bytes(self.store.read()),
                               "application/json")
            if method == "POST" and path == "/api/reviews":
                length = int(environ.get("CONTENT_LENGTH", "0"))
                if length <= 0 or length > 6000:
                    raise ValueError("invalid_body_length")
                body = environ["wsgi.input"].read(length)
                payload = json.loads(body)
                event = self.store.append(payload)
                return respond("201 Created", canonical_bytes(event),
                               "application/json")
            return respond("405 Method Not Allowed", b"method not allowed",
                           "text/plain")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return respond("400 Bad Request", b"invalid review request",
                           "text/plain")
