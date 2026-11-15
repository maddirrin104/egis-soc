"""Create/check the W5-06 synthetic S3 repair archive from verified parents."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import (
    MODEL_ID, MODEL_REVISION, DevelopmentV2, TransformersNLIBackend,
)
from egis_soc.summarization.generation import GenerationConfig
from egis_soc.summarization.s2 import ReviewBatch
from egis_soc.summarization.s3 import (
    RepairPlan, create_s3_archive, verify_s3_archive,
)
from w5_model_binding import pinned_binding
from w5_synthetic_draft import synthetic_context
from w5_synthetic_omission import DEFAULT_OUTPUT as DEFAULT_OMISSION
from w5_synthetic_s2 import (
    DEFAULT_CLAIMS, DEFAULT_DRAFT, DEFAULT_REVIEW, DEFAULT_S1,
    DEFAULT_OUTPUT as DEFAULT_S2, _read_unique_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "tests" / "fixtures" / "w5_06_synthetic_repair_plan_v1.json"
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_06_synthetic_s3_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--s1", type=Path, default=DEFAULT_S1)
    parser.add_argument("--s2", type=Path, default=DEFAULT_S2)
    parser.add_argument("--omission", type=Path, default=DEFAULT_OMISSION)
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
    if args.check:
        report = verify_s3_archive(
            context, config, args.draft, args.claims, args.s1, review,
            binding, args.s2, args.omission, plan, args.output)
    else:
        needs_v3 = any(action.action in {"add", "qualify", "rewrite"}
                       for repair_round in plan.rounds
                       for action in repair_round.actions)
        verifier = (SyntheticV3Verifier(DevelopmentV2(TransformersNLIBackend()))
                    if needs_v3 else None)
        report = create_s3_archive(
            context, config, args.draft, args.claims, args.s1, review,
            binding, args.s2, args.omission, plan, verifier, args.output)
    print(json.dumps({
        "result": "PASS_SYNTHETIC_S3_ONLY",
        "mode": "check" if args.check else "create",
        "archive": str(args.output),
        "executed_rounds": report["executed_rounds"],
        "stop_reason": report["stop_reason"],
        "s3_v3_calls": report["s3_only_cost"]["v3_calls"],
        "s3_nli_input_tokens": report["s3_only_cost"]["nli_input_tokens"],
        "s3_v3_latency_ns": report["s3_only_cost"]["v3_latency_ns"],
        "final_claim_count": len(report["final_claims"]),
        "review_queue_count": len(report["review_queue"]),
        "fork_sha256": report["fork_sha256"],
        "manifest_sha256": hashlib.sha256(
            (args.output / "manifest.json").read_bytes()).hexdigest(),
        "gold_status": report["gold_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
