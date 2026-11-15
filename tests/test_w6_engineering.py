"""Synthetic W6 guardrails and integration tests."""

import unittest

from egis_soc.development_data import DevelopmentData
from egis_soc.development_retrieval import DevelopmentRetriever
from egis_soc.w6_environment_b import FINDINGS, REQUIRED, VERSION, audit_environment_b
from egis_soc.w6_profiling import profile_stages
from egis_soc.w6_robustness import make_variant


def fixture():
    events = tuple({"evidence_id": f"E{i}", "incident_id": "SYN-W6",
                    "tenant_id": "SYN-T", "source_ref": f"synthetic:E{i}",
                    "raw_sha256": str(i) * 64, "raw_message_ref": f"synthetic:raw:{i}",
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "source_dataset": "synthetic",
                    "event_data": {"host": "WS01", "peer": "WS01",
                                   "ip": "192.0.2.1", "log_source": "sysmon" if i == 1 else "security",
                                   "action": "logon"}}
                   for i in (1, 2))
    return DevelopmentData("SYN-W6", "SYN-T", "train", "SYNTHETIC",
                           "synthetic", None, events)


class EnvironmentBTests(unittest.TestCase):
    def test_blinded_missing_and_complete_dispositions(self):
        blank = audit_environment_b({"version": VERSION})
        self.assertEqual(blank["status"], "UNKNOWN")
        self.assertEqual(blank["qualification"], "NOT_APPROVED_FOR_EVALUATION")
        candidate = {"version": VERSION, **{name: f"audit:{name}" for name in REQUIRED},
                     **{name: {"status": "PASS", "reason": "reviewed_synthetic",
                               "evidence_ref": f"audit:{name}"} for name in FINDINGS},
                     "reviewer_decision": {"status": "PASS", "reason": "synthetic_example",
                                           "evidence_ref": "audit:review"}}
        self.assertEqual(audit_environment_b(candidate)["status"], "PASS")
        self.assertEqual(audit_environment_b(candidate)["qualification"],
                         "NOT_APPROVED_FOR_EVALUATION")
        candidate["cross_partition_duplicates"] = {"status": "FAIL", "reason": "shared_run",
                                                    "evidence_ref": "audit:duplicate"}
        with self.assertRaisesRegex(ValueError, "exclusion_reason"):
            audit_environment_b(candidate)
        candidate["exclusion_reason"] = "shared_run"
        self.assertEqual(audit_environment_b(candidate)["status"], "FAIL")

    def test_sealed_content_rejected(self):
        for field in ("labels", "scores", "event_hashes", "gold_status"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "sealed"):
                audit_environment_b({"version": VERSION, field: []})
        with self.assertRaisesRegex(ValueError, "unexpected_b_metadata_field"):
            audit_environment_b({"version": VERSION, "incident_narrative": "untrusted"})


class RobustnessTests(unittest.TestCase):
    def test_r1_relations_and_original_bytes(self):
        parent = fixture()
        variant = make_variant(parent, "R1", seed=7,
                               options={"substitutions": {"WS01": "WS02", "192.0.2.1": "198.51.100.2"}})
        self.assertEqual(variant.events[0]["event_data"]["host"], variant.events[0]["event_data"]["peer"])
        self.assertEqual(variant.events[0]["event_data"]["host"], "WS02")
        self.assertEqual(parent.events[0]["event_data"]["host"], "WS01")
        self.assertEqual(variant.events[0]["raw_sha256"], parent.events[0]["raw_sha256"])
        self.assertEqual(variant.partition, parent.partition)
        self.assertEqual(variant.lineage_group, parent.lineage_group)
        self.assertEqual(variant.events[0]["parent_evidence_id"], "E1")
        hits = DevelopmentRetriever(variant.development_view()).search(
            "WS02", incident_id="SYN-W6", tenant_id="SYN-T")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].provenance["raw_sha256"], parent.events[0]["raw_sha256"])
        self.assertEqual(variant.variant_id, make_variant(parent, "R1", seed=7,
                         options={"substitutions": {"WS01": "WS02", "192.0.2.1": "198.51.100.2"}}).variant_id)
        with self.assertRaises(PermissionError):
            variant.resolve("E1", incident_id="OTHER", tenant_id="SYN-T")
        with self.assertRaises(KeyError):
            variant.resolve("MISSING", incident_id="SYN-W6", tenant_id="SYN-T")
        with self.assertRaises(TypeError):
            variant.events[0]["event_data"]["host"] = "mutated"

    def test_r2_r3_r4_invariants(self):
        parent = fixture()
        renamed = make_variant(parent, "R2", seed=1, options={"field_names": {"host": "computer"}})
        self.assertEqual(renamed.events[0]["event_data"]["computer"], "WS01")
        self.assertNotIn("host", renamed.events[0]["event_data"])
        shifted = make_variant(parent, "R3", seed=1, options={"utc_offset_minutes": 420})
        self.assertEqual(shifted.events[0]["timestamp_display"], "2026-01-01T07:00:00+07:00")
        self.assertEqual(shifted.events[0]["timestamp_utc"], parent.events[0]["timestamp_utc"])
        noisy = make_variant(parent, "R4", seed=1, options={"count": 2})
        self.assertEqual(len(noisy.events), 4)
        self.assertTrue(noisy.events[-1]["synthetic_noise"])
        self.assertEqual(noisy.events[-1]["tenant_id"], parent.tenant_id)
        self.assertEqual(noisy.events[-1]["parent_evidence_id"], None)
        self.assertEqual(len(parent.events), 2)
        self.assertEqual(len(DevelopmentRetriever(parent).search("logon", incident_id="SYN-W6", tenant_id="SYN-T")), 2)

    def test_r5_r6_review_and_failures(self):
        parent = fixture()
        for kind, options in (("R5", {"remove_evidence_ids": ["E1"]}),
                              ("R6", {"remove_log_sources": ["sysmon"]})):
            with self.subTest(kind=kind):
                variant = make_variant(parent, kind, seed=3, options=options)
                self.assertEqual([event["evidence_id"] for event in variant.events], ["E2"])
                self.assertEqual(variant.relabel_status, "HUMAN_REVIEW_REQUIRED")
                self.assertEqual(len(DevelopmentRetriever(variant.development_view()).search(
                    "logon", incident_id="SYN-W6", tenant_id="SYN-T")), 1)
                self.assertEqual(len(parent.events), 2)
        for kind, options in (("R1", {"substitutions": {"WS01": "X", "WS02": "X"}}),
                              ("R2", {"field_names": {"host": "peer"}}),
                              ("R5", {"remove_evidence_ids": ["FOREIGN"]}),
                              ("R6", {"remove_log_sources": ["missing"]})):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                make_variant(parent, kind, seed=0, options=options)
        contaminated = DevelopmentData("SYN-W6", "SYN-T", "train", "SYNTHETIC",
                                       "synthetic", None,
                                       ({**parent.events[0], "gold_status": "supported"}, parent.events[1]))
        with self.assertRaisesRegex(ValueError, "evaluation_content_forbidden"):
            make_variant(contaminated, "R3", seed=0, options={"utc_offset_minutes": 0})
        wrong = DevelopmentData("SYN-W6", "SYN-T", "heldout_b", "SYNTHETIC",
                                "synthetic", None, parent.events)
        with self.assertRaisesRegex(ValueError, "protected_partition"):
            make_variant(wrong, "R3", seed=0, options={"utc_offset_minutes": 0})


class ProfilingTests(unittest.TestCase):
    def test_success_failure_timeout_and_units(self):
        def fail():
            raise RuntimeError("synthetic_failure")
        result = profile_stages([("retrieval", lambda: {"input_tokens": 4, "output_tokens": 2}),
                                 ("failure", fail)], workload_ref="synthetic:test", repetitions=2,
                                model={"status": "BLOCKED", "checkpoint": "pinned_missing",
                                       "revision": "NOT_MEASURED", "quantization": "NOT_MEASURED"})
        self.assertEqual(result["summary"]["success"], 2)
        self.assertEqual(result["summary"]["failed"], 2)
        self.assertEqual(result["summary"]["timeout"], 0)
        self.assertGreater(result["summary"]["peak_process_tree_rss_bytes"], 0)
        self.assertIsNone(result["summary"]["inference_cost"])
        self.assertEqual(result["attempts"][0]["start_kind"], "cold")
        self.assertEqual(result["attempts"][2]["start_kind"], "warm")
        timed = profile_stages([("slow", lambda: None)], workload_ref="synthetic:timeout",
                               timeout_s=1e-12)
        self.assertEqual(timed["summary"]["timeout"], 1)


if __name__ == "__main__":
    unittest.main()
