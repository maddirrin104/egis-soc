"""W5-08 offline chain replay and failure-propagation tests."""

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from egis_soc.integrity import canonical_bytes
from egis_soc.summarization.atomization import create_claim_archive
from egis_soc.summarization.final_report import build_final_report, create_final_archive
from egis_soc.summarization.generation import GenerationConfig, generate_and_archive
from egis_soc.summarization.omission import create_omission_archive
from egis_soc.summarization.qa import (
    ReplaySources, create_qa_archive, replay_synthetic_chain, verify_qa_archive,
)
from egis_soc.summarization.s1 import create_s1_archive
from egis_soc.summarization.s2 import ReviewBatch, ReviewedCandidate, create_s2_archive
from egis_soc.summarization.s3 import create_s3_archive
from test_w5_atomization import context
from test_w5_generation import FakeBackend
from test_w5_s2 import verifier
from test_w5_s3 import plan_for


def chain(root):
    source = context()
    config = GenerationConfig("synthetic-model", "a" * 64)
    binding = {"kind": "synthetic_fake_backend"}
    paths = ReplaySources(*(root / name for name in
                            ("w5_01", "w5_02", "w5_03", "w5_04",
                             "w5_05", "w5_06", "w5_07")))
    generate_and_archive(source, config, FakeBackend(
        '{"draft_text":"Alice logged on [E1]."}'), paths.generation)
    claims = create_claim_archive(source, config, paths.generation, paths.claims)
    s1 = create_s1_archive(source, config, paths.generation, paths.claims, paths.s1)
    claim = claims.draft.claims[0]
    review = ReviewBatch(
        claims.draft.sha256,
        hashlib.sha256(canonical_bytes(s1.to_record())).hexdigest(),
        (ReviewedCandidate(claim.claim_id, claim.text,
                           "authored-synthetic-review", "one event",
                           "atomic_factual", ("relevant",), "supported"),))
    s2 = create_s2_archive(source, config, paths.generation, paths.claims,
                           paths.s1, review, verifier(), binding, paths.s2)
    omission = create_omission_archive(
        source, config, paths.generation, paths.claims, paths.s1,
        review, binding, paths.s2, paths.omission)
    fork = (paths.s2 / "fork.json").read_bytes()
    inventory = json.loads((paths.omission / "inventory.json").read_bytes())
    plan = plan_for(fork, omission)
    s3 = create_s3_archive(
        source, config, paths.generation, paths.claims, paths.s1,
        review, binding, paths.s2, paths.omission, plan, None, paths.s3)
    final = build_final_report(s1, review, s2, s3, inventory, omission, fork)
    parents = {name: (getattr(paths, name) / "manifest.json").read_bytes()
               for name in ("s1", "s2", "omission", "s3")}
    create_final_archive(final, parents, paths.final)
    return source, config, review, plan, binding, paths


class W5QATests(unittest.TestCase):
    def test_full_synthetic_replay_identity_and_create_only_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = chain(root)
            report = replay_synthetic_chain(*inputs)
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual([item["status"] for item in report["stage_checks"]],
                             ["PASS"] * 9)
            self.assertEqual(report["identity"]["status"], "VERIFIED")
            self.assertTrue(report["identity"]["s2_s3_same_fork_bytes"])
            self.assertEqual(report["rq2_metrics_status"], "NOT_SCORED")
            self.assertEqual(report["gold_status"], "NOT_GOLD")
            target = root / "w5_08"
            create_qa_archive(report, target)
            self.assertEqual(verify_qa_archive(replay_synthetic_chain(*inputs),
                                               target), report)
            with self.assertRaisesRegex(FileExistsError, "w5_08_archive_exists"):
                create_qa_archive(report, target)
            (target / "qa_report.json").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "w5_08_archive_drift"):
                verify_qa_archive(report, target)

    def test_upstream_drift_blocks_all_descendants(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, config, review, plan, binding, paths = chain(root)
            copy = root / "bad_generation"
            shutil.copytree(paths.generation, copy)
            response = copy / "response.json"
            response.write_bytes(response.read_bytes() + b" ")
            bad = replace(paths, generation=copy)
            report = replay_synthetic_chain(source, config, review, plan,
                                            binding, bad)
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(report["stage_checks"][0]["status"], "PASS")
            self.assertEqual(report["stage_checks"][1]["status"], "FAIL")
            self.assertTrue(all(item["status"] == "BLOCKED" for item in
                                report["stage_checks"][2:]))
            self.assertEqual(report["identity"]["status"], "NOT_VERIFIED")
            self.assertEqual(report["rq2_metrics_status"], "NOT_SCORED")

    def test_s3_drift_blocks_final_without_changing_s2_fork(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, config, review, plan, binding, paths = chain(root)
            original_fork = (paths.s2 / "fork.json").read_bytes()
            copy = root / "bad_s3"
            shutil.copytree(paths.s3, copy)
            report_file = copy / "s3_report.json"
            report_file.write_bytes(report_file.read_bytes() + b" ")
            report = replay_synthetic_chain(
                source, config, review, plan, binding, replace(paths, s3=copy))
            self.assertEqual([item["status"] for item in report["stage_checks"]],
                             ["PASS"] * 7 + ["FAIL", "BLOCKED"])
            self.assertEqual((paths.s2 / "fork.json").read_bytes(), original_fork)
            self.assertEqual(report["identity"]["status"], "NOT_VERIFIED")

    def test_unexpected_exception_is_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs = chain(Path(temporary))
            with patch("egis_soc.summarization.qa.verify_archive",
                       side_effect=RuntimeError("private backend detail")):
                report = replay_synthetic_chain(*inputs)
            self.assertEqual(report["stage_checks"][1]["error_code"],
                             "UNSPECIFIED_CHECK_FAILURE")
            self.assertNotIn("private backend detail", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
