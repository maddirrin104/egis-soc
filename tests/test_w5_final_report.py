"""W5-07 report and review-surface boundary tests."""

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from egis_soc.integrity import canonical_bytes
from egis_soc.summarization.final_report import (
    build_final_report, create_final_archive, verify_final_archive,
)
from egis_soc.summarization.omission import check_operational_omissions
from egis_soc.summarization.review_api import ReviewApp, ReviewStore
from egis_soc.summarization.s2 import run_s2
from egis_soc.summarization.s3 import run_s3
from test_w5_contract import CLAIM
from test_w5_omission import fork_for
from test_w5_s2 import prepared, verifier
from test_w5_s3 import plan_for


def packet(text="Exfiltration occurred [E1].", *, relevance=("relevant",),
           cited_support="supported"):
    source, draft, s1, review = prepared(
        text, relevance=relevance, cited_support=cited_support)
    s2 = run_s2(source, draft, s1, review, verifier())
    fork = fork_for(source, s2)
    inventory, omission = check_operational_omissions(source, s2, fork)
    s3 = run_s3(source, s2, fork, inventory, omission,
                plan_for(fork, omission))
    return s1, review, s2, s3, inventory, omission, fork


def call(app, method, path, token=None, payload=None):
    statuses = []
    body = b"" if payload is None else json.dumps(payload).encode()
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path,
               "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body),
               "HTTP_AUTHORIZATION": "" if token is None else "Bearer " + token}
    result = b"".join(app(environ, lambda status, headers: statuses.append(status)))
    return statuses[0], result


class W5FinalReportTests(unittest.TestCase):
    def test_empty_s3_packet_retains_uncertainty_and_trace(self):
        values = packet()
        report = build_final_report(*values)
        self.assertEqual(report["final_claims"], [])
        self.assertIn("EMPTY_FINAL_REPORT_REQUIRES_ANALYST_REVIEW", report["warnings"])
        self.assertEqual(report["draft_candidates"][0]["prediction"], "insufficient")
        self.assertEqual(report["draft_candidates"][0]["s2_action"], "abstain")
        self.assertEqual(len(report["evidence"]), 1)
        self.assertEqual(len(report["omission_findings"]), 1)
        self.assertEqual(report["analyst_review_status"], "SEPARATE_RECORD_REQUIRED")
        self.assertEqual(report["structured_report"]["claims"], [])
        self.assertEqual(report["structured_report"]["analyst_notes"], [])
        self.assertNotIn("gold_facts", json.dumps(report))

    def test_supported_final_claim_has_separate_citation_checks(self):
        report = build_final_report(*packet(f"{CLAIM} [E1]."))
        self.assertEqual(len(report["final_claims"]), 1)
        claim = report["final_claims"][0]
        self.assertTrue(claim["citation_validity"][0]["valid"])
        self.assertEqual(claim["citation_support_review"], "reviewed_supported")
        self.assertEqual(claim["prediction"], "supported")
        self.assertIn(claim["claim_id"], report["structured_report"]["claims"])

    def test_failed_s3_no_citation_and_scope_rejection(self):
        values = packet("Exfiltration occurred.", relevance=(),
                        cited_support="not_assessed")
        s1, review, s2, s3, inventory, omission, fork = values
        failed = build_final_report(s1, review, s2, None, None, None, fork)
        self.assertEqual(failed["final_claims"], [])
        self.assertIn("S3_STAGE_FAILED_OR_MISSING", failed["warnings"])
        self.assertIn("UNCITED_DRAFT_CLAIM", failed["warnings"])
        with self.assertRaisesRegex(ValueError, "w5_07_s3_scope_mismatch"):
            build_final_report(s1, review, s2, {**s3, "tenant_id": "OTHER"},
                               inventory, omission, fork)
        with self.assertRaisesRegex(ValueError, "w5_07_parent_scope_mismatch"):
            build_final_report(replace(s1, tenant_id="OTHER"), review, s2,
                               s3, inventory, omission, fork)

    def test_archive_and_explicit_review_are_separate(self):
        report = build_final_report(*packet())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "packet"
            parents = {"s2": b"verified-parent"}
            create_final_archive(report, parents, target)
            verify_final_archive(report, parents, target)
            with self.assertRaisesRegex(FileExistsError, "w5_07_archive_exists"):
                create_final_archive(report, parents, target)
            store = ReviewStore(root, report)
            self.assertEqual(store.read(), [])
            token = "t" * 40
            app = ReviewApp(report, store, token, b"<html></html>", b"const x = 1;")
            self.assertEqual(call(app, "GET", "/api/report")[0], "403 Forbidden")
            self.assertEqual(call(app, "GET", "/api/report", token)[0], "200 OK")
            self.assertEqual(call(app, "GET", "/api/reviews", token)[0], "200 OK")
            correction = {"reviewer_id": "analyst-test", "action": "correction",
                          "claim_id": report["draft_candidates"][0]["claim_id"],
                          "text": "Corrected draft assertion", "confirm_approval": False}
            self.assertEqual(call(app, "POST", "/api/reviews", token,
                                  correction)[0], "201 Created")
            foreign = {**correction, "claim_id": "FOREIGN"}
            self.assertEqual(call(app, "POST", "/api/reviews", token,
                                  foreign)[0], "400 Bad Request")
            approval = {"reviewer_id": "analyst-test", "action": "approve",
                        "claim_id": None, "text": "Reviewed this synthetic packet",
                        "confirm_approval": False}
            self.assertEqual(call(app, "POST", "/api/reviews", token,
                                  approval)[0], "400 Bad Request")
            self.assertEqual(len(store.read()), 1)
            approval["confirm_approval"] = True
            self.assertEqual(call(app, "POST", "/api/reviews", token,
                                  approval)[0], "201 Created")
            self.assertEqual(len(store.read()), 2)
            self.assertFalse(store.read()[0]["explicit_approval"])
            self.assertTrue(store.read()[1]["explicit_approval"])
            self.assertEqual(report["analyst_review_status"],
                             "SEPARATE_RECORD_REQUIRED")
            self.assertEqual((target / "report.json").read_bytes(),
                             canonical_bytes(report))
            self.assertEqual(call(app, "GET", "/unknown", token)[0],
                             "404 Not Found")
            with store.path.open("ab") as stream:
                stream.write(b"tamper\n")
            with self.assertRaisesRegex(ValueError, "review_log_drift"):
                store.read()


if __name__ == "__main__":
    unittest.main()
