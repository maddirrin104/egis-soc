"""Local synthetic report API with opt-in authenticated W5-derived review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from egis_soc.integrity import canonical_bytes
from egis_soc.summarization.review_v2 import AuthenticatedReviewStore

from .w8_auth import ReviewSessions
from .w8_demo import FIXTURES, run_case


INCIDENTS = {"SYN-W8-POSITIVE": "positive", "SYN-W8-NEGATIVE": "negative"}


class DemoApp:
    def __init__(self, html: bytes, javascript: bytes, css: bytes = b"",
                 sessions: ReviewSessions | None = None,
                 stores: dict[str, AuthenticatedReviewStore] | None = None):
        if (sessions is None) != (stores is None):
            raise ValueError("review_sessions_and_stores_required_together")
        self.html = html
        self.javascript = javascript
        self.css = css
        self.sessions = sessions
        self.stores = stores

    def __call__(self, environ: dict, start_response: Callable):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")

        def respond(status: str, body: bytes, kind="application/json", extra=()):
            start_response(status, [
                ("Content-Type", kind), ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'"),
                *extra,
            ])
            return [body]

        def request_body(maximum: int) -> dict:
            try:
                length = int(environ.get("CONTENT_LENGTH", "0"))
                if (not 0 < length <= maximum
                        or environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json"):
                    raise ValueError("invalid_body")
                body = environ["wsgi.input"].read(length)
                if len(body) != length:
                    raise ValueError("incomplete_body")
                value = json.loads(body)
                if type(value) is not dict:
                    raise ValueError("json_object_required")
                return value
            except (KeyError, TypeError, UnicodeError, json.JSONDecodeError):
                raise ValueError("invalid_body") from None

        def reviewer_session() -> tuple[str, str]:
            if self.sessions is None:
                raise PermissionError("review_auth_unavailable")
            header = environ.get("HTTP_AUTHORIZATION", "")
            if type(header) is not str or not header.startswith("Bearer "):
                raise PermissionError("review_session_required")
            token = header[7:]
            return self.sessions.reviewer(token), token

        if method == "GET" and path in {"/", "/w8.js", "/w8.css"}:
            content, kind = ({"/": (self.html, "text/html; charset=utf-8"),
                              "/w8.js": (self.javascript, "application/javascript; charset=utf-8"),
                              "/w8.css": (self.css, "text/css; charset=utf-8")})[path]
            return respond("200 OK", content, kind)
        if method == "GET" and path == "/api/health":
            return respond("200 OK", canonical_bytes({
                "status": "SYNTHETIC_OFFLINE_ONLY",
                "review_mutations": ("AUTHENTICATED_LOCAL" if self.sessions else "DISABLED"),
                "real_splunk": "NOT_CONNECTED"}))
        if method == "GET" and path == "/api/incidents":
            return respond("200 OK", canonical_bytes([
                {"incident_id": incident, "case": case, "mode": "SYNTHETIC_OFFLINE"}
                for incident, case in INCIDENTS.items()]))
        if path == "/api/login" and method == "POST":
            if self.sessions is None:
                return respond("403 Forbidden", b'{"error":"review_auth_unavailable"}')
            try:
                payload = request_body(2048)
                if set(payload) != {"password"}:
                    raise ValueError("invalid_login_body")
                token = self.sessions.login(payload["password"])
                return respond("200 OK", canonical_bytes({
                    "token": token, "reviewer_id": self.sessions.identity.reviewer_id,
                    "expires_in_seconds": self.sessions.identity.session_seconds,
                }))
            except PermissionError:
                return respond("401 Unauthorized", b'{"error":"invalid_credentials"}')
            except ValueError:
                return respond("400 Bad Request", b'{"error":"invalid_login_request"}')
        if path in {"/api/session", "/api/logout"}:
            if self.sessions is None:
                return respond("403 Forbidden", b'{"error":"review_auth_unavailable"}')
            try:
                reviewer, token = reviewer_session()
                if method == "GET" and path == "/api/session":
                    return respond("200 OK", canonical_bytes({"reviewer_id": reviewer,
                                                               "status": "AUTHENTICATED_LOCAL"}))
                if method == "POST" and path == "/api/logout":
                    self.sessions.logout(token)
                    return respond("200 OK", b'{"status":"LOGGED_OUT"}')
                return respond("405 Method Not Allowed", b'{"error":"method_not_allowed"}')
            except PermissionError:
                return respond("401 Unauthorized", b'{"error":"review_session_required"}')
        if path.startswith("/api/reviews"):
            if self.sessions is None or self.stores is None:
                return respond("403 Forbidden", b'{"error":"authenticated_review_unavailable"}')
            try:
                reviewer, _ = reviewer_session()
            except PermissionError:
                return respond("401 Unauthorized", b'{"error":"review_session_required"}')
            parts = path.strip("/").split("/")
            if len(parts) < 3 or parts[:2] != ["api", "reviews"]:
                return respond("404 Not Found", b'{"error":"not_found"}')
            store = self.stores.get(parts[2])
            if store is None:
                return respond("404 Not Found", b'{"error":"not_found"}')
            try:
                if method == "GET" and len(parts) == 3:
                    return respond("200 OK", canonical_bytes(store.latest()))
                if method == "GET" and len(parts) == 4 and parts[3] == "audit":
                    store.latest()
                    return respond("200 OK", canonical_bytes(store.read()))
                if method == "GET" and len(parts) == 4 and parts[3] == "export":
                    return respond("200 OK", canonical_bytes(store.latest()), extra=((
                        "Content-Disposition", "attachment; filename=" + parts[2] +
                        "-reviewed-synthetic.json"),))
                if method == "GET" and len(parts) == 5 and parts[3] == "versions":
                    if not parts[4].isdigit() or len(parts[4]) > 6:
                        raise ValueError("unknown_review_version")
                    return respond("200 OK", canonical_bytes(store.version(int(parts[4]))))
                if method == "POST" and len(parts) == 4 and parts[3] == "actions":
                    payload = request_body(6000)
                    snapshot, audit = store.act(payload, reviewer)
                    return respond("201 Created", canonical_bytes({
                        "snapshot": snapshot, "audit_record": audit}))
                return respond("405 Method Not Allowed", b'{"error":"method_not_allowed"}')
            except FileExistsError:
                return respond("409 Conflict", b'{"error":"review_write_conflict"}')
            except (ValueError, OSError, KeyError, TypeError):
                return respond("409 Conflict", b'{"error":"invalid_or_stale_review"}')
        if method == "POST" and path == "/api/run":
            try:
                request = request_body(256)
                if type(request) is not dict or set(request) != {"case"} or request["case"] not in FIXTURES:
                    raise ValueError("invalid_case")
                return respond("200 OK", canonical_bytes(run_case(request["case"])))
            except (ValueError, TypeError, KeyError, UnicodeError):
                return respond("400 Bad Request", b'{"error":"invalid_synthetic_request"}')
        if method == "GET":
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "reports"]:
                case = INCIDENTS.get(parts[2])
                if case:
                    return respond("200 OK", canonical_bytes(run_case(case)))
            if len(parts) == 4 and parts[:2] == ["api", "evidence"]:
                case = INCIDENTS.get(parts[2])
                if case:
                    report = run_case(case)
                    evidence = next((item for item in report["evidence"]
                                     if item["evidence_id"] == parts[3]
                                     and item["incident_id"] == parts[2]), None)
                    if evidence:
                        return respond("200 OK", canonical_bytes(evidence))
            if len(parts) == 3 and parts[:2] == ["api", "export"]:
                case = INCIDENTS.get(parts[2])
                if case:
                    return respond("200 OK", canonical_bytes(run_case(case)),
                                   extra=(("Content-Disposition", "attachment; filename=w8-" +
                                           case + "-synthetic-report.json"),))
        return respond("404 Not Found", b'{"error":"not_found"}')


def create_app(root: Path, *, sessions: ReviewSessions | None = None,
               review_directory: Path | None = None) -> DemoApp:
    stores = None
    if sessions is not None:
        if review_directory is None:
            raise ValueError("review_directory_required")
        candidate = Path(review_directory)
        if candidate.is_symlink():
            raise ValueError("review_directory_symlink")
        directory = candidate.resolve()
        workspace = Path(root).resolve()
        if (not directory.is_dir() or directory.is_symlink()
                or directory == workspace or workspace in directory.parents):
            raise ValueError("review_directory_must_be_external")
        stores = {incident: AuthenticatedReviewStore(directory, run_case(case))
                  for incident, case in INCIDENTS.items()}
    return DemoApp((root / "dashboard" / "w8_demo.html").read_bytes(),
                   (root / "dashboard" / "w8_demo.js").read_bytes(),
                   (root / "dashboard" / "w8_demo.css").read_bytes(),
                   sessions, stores)
