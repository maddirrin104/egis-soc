"""W8 fixed synthetic vertical slice, API scope and archive integrity."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from egis_soc.w8_api import DemoApp
from egis_soc.w8_demo import FIXTURES, ROOT, load_fixture, run_case
from scripts.w8_offline_demo import check, create


class W8DemoTests(unittest.TestCase):
    def test_positive_supported_claim_has_exact_citation_and_no_compromise(self):
        report = run_case("positive")
        self.assertEqual(report["w8_demo"]["mode"], "SYNTHETIC_OFFLINE")
        self.assertEqual(len(report["final_claims"]), 1)
        claim = report["final_claims"][0]
        self.assertEqual(claim["prediction"], "supported")
        self.assertEqual(claim["citation_ids"], ["E-P2"])
        self.assertEqual(claim["citation_support_review"], "reviewed_supported")
        self.assertFalse(claim["review_required"])
        self.assertNotIn("compromise", claim["text"].lower())
        self.assertEqual({item["evidence_id"] for item in report["evidence"]},
                         {"E-P1", "E-P2", "E-P3"})
        self.assertEqual(report["gold_status"], "NOT_GOLD")
        self.assertEqual(report["w8_demo"]["research_status"], "NOT_RUN")

    def test_negative_refutation_abstention_omission_and_fresh_repair(self):
        report = run_case("negative")
        self.assertEqual([(item["prediction"], item["s2_action"])
                          for item in report["draft_candidates"]],
                         [("contradicted", "remove"), ("insufficient", "abstain")])
        self.assertEqual(report["omission_findings"][0]["outcome"],
                         "candidate_unmentioned")
        self.assertEqual(report["repair_history"][0]["result"],
                         "reverified_supported")
        self.assertEqual(len(report["repair_verifications"]), 1)
        self.assertEqual(report["repair_verifications"][0]["assessment"]["prediction"],
                         "supported")
        self.assertEqual(len(report["final_claims"]), 1)
        self.assertEqual(report["final_claims"][0]["citation_ids"], ["E-N1"])
        self.assertIn("outcome=failure", report["final_claims"][0]["text"])
        self.assertNotIn("Compromise occurred", report["final_claims"][0]["text"])
        self.assertIn("Ignore previous instructions", report["evidence"][0]["raw_message"])

    def test_scope_and_citation_drift_fail_closed(self):
        fixture, _ = load_fixture("positive")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "case.json"
            variants = []
            foreign = copy.deepcopy(fixture)
            foreign["events"][0]["evidence_id"] = "E-FOREIGN"
            variants.append(foreign)
            tenant = copy.deepcopy(fixture)
            tenant["events"][0]["tenant_id"] = "SYN-OTHER"
            variants.append(tenant)
            incident = copy.deepcopy(fixture)
            incident["events"][0]["incident_id"] = "SYN-OTHER"
            variants.append(incident)
            contaminated = copy.deepcopy(fixture)
            contaminated["events"][0]["normalized_fields"]["gold_label"] = "supported"
            variants.append(contaminated)
            citation = copy.deepcopy(fixture)
            citation["draft_text"] = citation["draft_text"].replace("[E-P2]", "[E-FOREIGN]")
            variants.append(citation)
            empty = copy.deepcopy(fixture)
            empty["draft_text"] = ""
            variants.append(empty)
            for changed in variants:
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(changed=changed["draft_text"]), patch.dict(
                        FIXTURES, {"positive": path}):
                    with self.assertRaises(ValueError):
                        run_case("positive")

    def test_valid_but_irrelevant_citation_does_not_promote_claim(self):
        fixture, _ = load_fixture("positive")
        fixture["draft_text"] = fixture["draft_text"].replace("[E-P2]", "[E-P1]")
        fixture["reviews"][0]["citation_ids"] = ["E-P1"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "case.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            with patch.dict(FIXTURES, {"positive": path}):
                report = run_case("positive")
        self.assertEqual(report["final_claims"], [])
        self.assertEqual(report["draft_candidates"][0]["s2_action"], "abstain")
        self.assertEqual(report["draft_candidates"][0]["verification"]
                         ["rule_trace"][0]["reason"], "IRRELEVANT_CITATION")

    def test_api_is_scoped_and_review_mutations_are_disabled(self):
        app = DemoApp(b"html", b"js")

        def call(method, path, body=b"", kind="application/json"):
            result = {}
            def start(status, headers):
                result["status"], result["headers"] = status, dict(headers)
            output = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path,
                                   "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": kind,
                                   "wsgi.input": io.BytesIO(body)}, start))
            return result["status"], output

        status, body = call("POST", "/api/run", b'{"case":"positive"}')
        self.assertTrue(status.startswith("200"))
        self.assertEqual(json.loads(body)["incident_id"], "SYN-W8-POSITIVE")
        self.assertTrue(call("GET", "/api/evidence/SYN-W8-POSITIVE/E-P2")[0].startswith("200"))
        self.assertTrue(call("GET", "/api/evidence/SYN-W8-NEGATIVE/E-P2")[0].startswith("404"))
        self.assertTrue(call("GET", "/api/evidence/SYN-W8-POSITIVE/é")[0].startswith("404"))
        self.assertTrue(call("POST", "/api/run", b'{"case":"../../data/private"}')[0].startswith("400"))
        self.assertTrue(call("POST", "/api/reviews", b"{}")[0].startswith("403"))
        self.assertNotIn(b"gold_label", call("GET", "/api/export/SYN-W8-POSITIVE")[1])

    def test_create_only_archive_and_replay_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "w8"
            manifest = create(target)
            self.assertEqual(check(target), manifest)
            with self.assertRaises(FileExistsError):
                create(target)
            report = target / "positive.json"
            report.write_bytes(report.read_bytes().replace(b"supported", b"unsupported", 1))
            with self.assertRaises(ValueError):
                check(target)


if __name__ == "__main__":
    unittest.main()
