"""Replay/check W5-01 through W5-07 synthetic archives without model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION
from egis_soc.summarization.generation import GenerationConfig
from egis_soc.summarization.qa import (
    ReplaySources, create_qa_archive, replay_synthetic_chain,
    verify_qa_archive,
)
from egis_soc.summarization.s2 import ReviewBatch
from egis_soc.summarization.s3 import RepairPlan
from w5_model_binding import pinned_binding
from w5_synthetic_draft import DEFAULT_OUTPUT as DEFAULT_GENERATION, synthetic_context
from w5_synthetic_claims import DEFAULT_OUTPUT as DEFAULT_CLAIMS
from w5_synthetic_s1 import DEFAULT_OUTPUT as DEFAULT_S1
from w5_synthetic_s2 import DEFAULT_OUTPUT as DEFAULT_S2, DEFAULT_REVIEW, _read_unique_json
from w5_synthetic_omission import DEFAULT_OUTPUT as DEFAULT_OMISSION
from w5_synthetic_s3 import DEFAULT_OUTPUT as DEFAULT_S3, DEFAULT_PLAN
from w5_synthetic_final_report import DEFAULT_OUTPUT as DEFAULT_FINAL


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_08_synthetic_qa_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--generation", type=Path, default=DEFAULT_GENERATION)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--s1", type=Path, default=DEFAULT_S1)
    parser.add_argument("--s2", type=Path, default=DEFAULT_S2)
    parser.add_argument("--omission", type=Path, default=DEFAULT_OMISSION)
    parser.add_argument("--s3", type=Path, default=DEFAULT_S3)
    parser.add_argument("--final", type=Path, default=DEFAULT_FINAL)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    review = ReviewBatch.from_record(_read_unique_json(args.review))
    plan = RepairPlan.from_record(_read_unique_json(args.plan))
    binding = pinned_binding()
    sources = ReplaySources(args.generation, args.claims, args.s1, args.s2,
                            args.omission, args.s3, args.final)
    report = replay_synthetic_chain(
        synthetic_context(), config, review, plan, binding, sources)
    if args.check:
        verify_qa_archive(report, args.output)
    else:
        create_qa_archive(report, args.output)
    print(json.dumps({
        "result": "PASS_SYNTHETIC_QA" if report["overall"] == "PASS"
                  else "FAIL_SYNTHETIC_QA",
        "mode": "check" if args.check else "create",
        "overall": report["overall"],
        "stages": {item["stage"]: item["status"]
                   for item in report["stage_checks"]},
        "negative_findings": report["negative_findings"],
        "fork_sha256": report["identity"].get("fork_sha256"),
        "manifest_sha256": hashlib.sha256(
            (args.output / "manifest.json").read_bytes()).hexdigest(),
        "rq2_metrics_status": report["rq2_metrics_status"],
    }, sort_keys=True))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
