"""Authenticated local review, immutable versions and W5 audit-chain reuse."""

import tempfile
import unittest
import io
import json
from pathlib import Path

from egis_soc.summarization.review_v2 import AuthenticatedReviewStore
from egis_soc.w8_api import DemoApp
from egis_soc.w8_auth import ReviewIdentity, ReviewSessions, make_password_hash
from egis_soc.w8_demo import run_case


def action(name, version, claim_id=None, reason="Explicit synthetic analyst rationale"):
    return {"action": name, "claim_id": claim_id, "reason": reason,
            "expected_version": version}


class W8ReviewTests(unittest.TestCase):
    def test_password_session_expiry_and_logout(self):
        password_hash = make_password_hash("correct-horse-battery", salt=b"a" * 16)
        identity = ReviewIdentity("analyst-one", password_hash, 60)
        now = [100.0]
        sessions = ReviewSessions(identity, lambda: now[0])
        with self.assertRaises(PermissionError):
            sessions.login("wrong-password")
        token = sessions.login("correct-horse-battery")
        self.assertEqual(sessions.reviewer(token), "analyst-one")
        sessions.logout(token)
        with self.assertRaises(PermissionError):
            sessions.reviewer(token)
        token = sessions.login("correct-horse-battery")
        now[0] += 60
        with self.assertRaises(PermissionError):
            sessions.reviewer(token)

    def test_approval_versions_audit_and_recovery(self):
        report = run_case("positive")
        cid = report["final_claims"][0]["claim_id"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthenticatedReviewStore(root, report)
            self.assertEqual(store.latest()["review"]["status"], "DRAFT")
            two, first = store.act(action("start_review", 1), "analyst-one")
            self.assertEqual(two["review"]["status"], "REVIEW_PENDING")
            three, second = store.act(action("accept_claim", 2, cid), "analyst-one")
            self.assertEqual(three["review"]["claim_decisions"][cid]["status"],
                             "accepted")
            four, third = store.act(action("approve_report", 3), "analyst-one")
            self.assertEqual(four["review"]["status"], "APPROVED")
            self.assertEqual(four["parent_version"], 3)
            self.assertEqual(third["reviewer_id"], "analyst-one")
            self.assertEqual(third["identity_status"], "AUTHENTICATED_LOCAL")
            self.assertEqual(third["incident_id"], report["incident_id"])
            self.assertEqual(third["report_id"], store.report_id)
            self.assertEqual(third["previous_status"], "REVIEW_PENDING")
            self.assertEqual(third["new_status"], "APPROVED")
            self.assertTrue(third["audit_record_id"].startswith("W8A-"))
            self.assertEqual(len(store.read()), 3)
            with self.assertRaises(ValueError):
                store.act(action("note", 4), "analyst-one")
            approved_bytes = store._version_path(4).read_bytes()
            five, _ = store.act(action("start_revision", 4), "analyst-one")
            self.assertEqual(five["review"]["status"], "DRAFT")
            self.assertEqual(five["parent_version"], 4)
            self.assertEqual(store._version_path(4).read_bytes(), approved_bytes)
            reopened = AuthenticatedReviewStore(root, report)
            self.assertEqual(reopened.latest(), five)
            self.assertEqual(reopened._version_path(4).exists(), True)

    def test_invalid_actions_and_tamper_fail_closed(self):
        report = run_case("negative")
        draft_id = report["draft_candidates"][0]["claim_id"]
        with tempfile.TemporaryDirectory() as temporary:
            store = AuthenticatedReviewStore(Path(temporary), report)
            with self.assertRaises(ValueError):
                store.act(action("approve_report", 1), "analyst-one")
            store.act(action("start_review", 1), "analyst-one")
            with self.assertRaises(ValueError):
                store.act(action("accept_claim", 2, draft_id), "analyst-one")
            with self.assertRaises(ValueError):
                store.act(action("approve_report", 2), "analyst-one")
            with self.assertRaises(ValueError):
                store.act(action("note", 1), "analyst-one")
            with self.assertRaises(ValueError):
                store.act(action([], 2), "analyst-one")
            with self.assertRaises(ValueError):
                store.act({**action("note", 2), "reviewer_id": "attacker"},
                          "analyst-one")
            store.act(action("note", 2, reason="Observed synthetic evidence"),
                      "analyst-one")
            self.assertEqual(store.latest()["review"]["notes"][0]["text"],
                             "Observed synthetic evidence")
            snapshot = store._version_path(3)
            snapshot.write_bytes(snapshot.read_bytes().replace(b"REVIEW_PENDING",
                                                              b"APPROVED", 1))
            with self.assertRaises(ValueError):
                store.latest()

    def test_audit_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = AuthenticatedReviewStore(Path(temporary), run_case("positive"))
            store.act(action("start_review", 1), "analyst-one")
            store.path.write_bytes(store.path.read_bytes().replace(
                b"AUTHENTICATED_LOCAL", b"SELF_ATTESTED_LOCAL"))
            with self.assertRaises(ValueError):
                store.latest()

    def test_reject_report_then_revision_and_foreign_source(self):
        report = run_case("positive")
        with tempfile.TemporaryDirectory() as temporary:
            store = AuthenticatedReviewStore(Path(temporary), report)
            store.act(action("start_review", 1), "analyst-one")
            rejected, _ = store.act(action("reject_report", 2), "analyst-one")
            self.assertEqual(rejected["review"]["status"], "REJECTED")
            revised, _ = store.act(action("start_revision", 3), "analyst-one")
            self.assertEqual(revised["review"]["status"], "DRAFT")
            changed = {**report, "tenant_id": "SYN-OTHER"}
            with self.assertRaises(ValueError):
                AuthenticatedReviewStore(Path(temporary), changed)

    def test_api_login_authorized_review_and_scope(self):
        password_hash = make_password_hash("correct-horse-battery", salt=b"b" * 16)
        now = [100.0]
        sessions = ReviewSessions(ReviewIdentity("analyst-one", password_hash, 60),
                                  lambda: now[0])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports = {case: run_case(case) for case in ("positive", "negative")}
            stores = {report["incident_id"]: AuthenticatedReviewStore(root, report)
                      for report in reports.values()}
            app = DemoApp(b"html", b"js", sessions=sessions, stores=stores)

            def call(method, path, payload=None, token=None):
                body = b"" if payload is None else json.dumps(payload).encode("utf-8")
                result = {}
                def start(status, headers):
                    result["status"], result["headers"] = status, dict(headers)
                raw = b"".join(app({
                    "REQUEST_METHOD": method, "PATH_INFO": path,
                    "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json",
                    "HTTP_AUTHORIZATION": "" if token is None else "Bearer " + token,
                    "wsgi.input": io.BytesIO(body),
                }, start))
                return result["status"], json.loads(raw)

            incident = reports["positive"]["incident_id"]
            review_path = "/api/reviews/" + incident
            self.assertTrue(call("GET", review_path)[0].startswith("401"))
            self.assertTrue(call("POST", review_path + "/actions",
                                 action("start_review", 1))[0].startswith("401"))
            self.assertTrue(call("POST", "/api/login",
                                 {"password": "wrong-password"})[0].startswith("401"))
            status, login = call("POST", "/api/login",
                                 {"password": "correct-horse-battery"})
            self.assertTrue(status.startswith("200"))
            token = login["token"]
            self.assertEqual(call("GET", review_path, token=token)[1]
                             ["review"]["status"], "DRAFT")
            self.assertTrue(call("POST", review_path + "/actions",
                                 {**action("start_review", 1),
                                  "reviewer_id": "attacker"}, token)[0].startswith("409"))
            status, first = call("POST", review_path + "/actions",
                                 action("start_review", 1), token)
            self.assertTrue(status.startswith("201"))
            self.assertEqual(first["audit_record"]["reviewer_id"], "analyst-one")
            cid = reports["positive"]["final_claims"][0]["claim_id"]
            self.assertTrue(call("POST", review_path + "/actions",
                                 action("accept_claim", 2, cid), token)[0].startswith("201"))
            self.assertTrue(call("POST", review_path + "/actions",
                                 action("approve_report", 3), token)[0].startswith("201"))
            self.assertEqual(call("GET", review_path + "/versions/1", token=token)[1]
                             ["review"]["status"], "DRAFT")
            exported = call("GET", review_path + "/export", token=token)[1]
            self.assertEqual(exported["review"]["status"], "APPROVED")
            self.assertEqual(exported["gold_status"], "NOT_GOLD")
            self.assertNotIn("E-N1", {item["evidence_id"]
                                       for item in exported["report"]["evidence"]})
            self.assertTrue(call("GET", "/api/reviews/SYN-OTHER", token=token)[0]
                            .startswith("404"))
            self.assertTrue(call("GET", "/api/evidence/SYN-W8-NEGATIVE/E-P2")[0]
                            .startswith("404"))
            self.assertTrue(call("POST", "/api/logout", token=token)[0]
                            .startswith("200"))
            self.assertTrue(call("GET", review_path, token=token)[0].startswith("401"))
            token = call("POST", "/api/login",
                         {"password": "correct-horse-battery"})[1]["token"]
            now[0] += 60
            self.assertTrue(call("GET", review_path, token=token)[0].startswith("401"))


if __name__ == "__main__":
    unittest.main()
