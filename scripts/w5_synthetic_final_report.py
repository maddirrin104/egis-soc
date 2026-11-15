"""Create/check the W5-07 synthetic final report from verified W5 parents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION
from egis_soc.summarization.final_report import (
    build_final_report, create_final_archive, verify_final_archive,
)
from egis_soc.summarization.generation import GenerationConfig
from egis_soc.summarization.omission import verify_omission_archive
from egis_soc.summarization.s1 import verify_s1_archive
from egis_soc.summarization.s2 import ReviewBatch, verify_s2_archive
from egis_soc.summarization.s3 import RepairPlan, verify_s3_archive
from w5_model_binding import pinned_binding
from w5_synthetic_draft import synthetic_context
from w5_synthetic_s2 import (
    DEFAULT_CLAIMS, DEFAULT_DRAFT, DEFAULT_REVIEW, DEFAULT_S1,
    DEFAULT_OUTPUT as DEFAULT_S2, _read_unique_json,
)
from w5_synthetic_omission import DEFAULT_OUTPUT as DEFAULT_OMISSION
from w5_synthetic_s3 import DEFAULT_OUTPUT as DEFAULT_S3, DEFAULT_PLAN


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_07_synthetic_final_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--s1", type=Path, default=DEFAULT_S1)
    parser.add_argument("--s2", type=Path, default=DEFAULT_S2)
    parser.add_argument("--omission", type=Path, default=DEFAULT_OMISSION)
    parser.add_argument("--s3", type=Path, default=DEFAULT_S3)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    context = synthetic_context()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    review = ReviewBatch.from_record(_read_unique_json(args.review))
    plan = RepairPlan.from_record(_read_unique_json(args.plan))
    binding = pinned_binding()
    s1 = verify_s1_archive(context, config, args.draft, args.claims, args.s1)
    s2 = verify_s2_archive(context, config, args.draft, args.claims, args.s1,
                           review, binding, args.s2)
    omission = verify_omission_archive(
        context, config, args.draft, args.claims, args.s1,
        review, binding, args.s2, args.omission)
    s3 = verify_s3_archive(
        context, config, args.draft, args.claims, args.s1, review,
        binding, args.s2, args.omission, plan, args.s3)
    inventory = _read_unique_json(args.omission / "inventory.json")
    fork = (args.s2 / "fork.json").read_bytes()
    report = build_final_report(s1, review, s2, s3, inventory, omission, fork)
    parents = {name: (path / "manifest.json").read_bytes()
               for name, path in (("s1", args.s1), ("s2", args.s2),
                                  ("omission", args.omission), ("s3", args.s3))}
    if args.check:
        verify_final_archive(report, parents, args.output)
    else:
        create_final_archive(report, parents, args.output)
    print(json.dumps({"result": "PASS_SYNTHETIC_FINAL_ONLY",
                      "mode": "check" if args.check else "create",
                      "final_claim_count": len(report["final_claims"]),
                      "warning_count": len(report["warnings"]),
                      "analyst_review_status": report["analyst_review_status"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
