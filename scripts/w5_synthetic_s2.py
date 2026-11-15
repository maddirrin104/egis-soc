"""Create/check the synthetic reviewed S2 archive and identical S2/S3 fork."""

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
from egis_soc.summarization.s2 import (
    ReviewBatch, create_s2_archive, read_common_fork, verify_s2_archive,
)
from w5_model_binding import pinned_binding
from w5_synthetic_draft import synthetic_context


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT = ROOT / "experiments" / "w5_01_local_synthetic_v1"
DEFAULT_CLAIMS = ROOT / "experiments" / "w5_02_synthetic_claims_v2"
DEFAULT_S1 = ROOT / "experiments" / "w5_03_synthetic_s1_v1"
DEFAULT_REVIEW = ROOT / "tests" / "fixtures" / "w5_04_synthetic_review_v1.json"
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_04_synthetic_s2_v2"


def _read_unique_json(path: Path) -> dict:
    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_s2_review_key")
            result[key] = value
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--s1", type=Path, default=DEFAULT_S1)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    context = synthetic_context()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    review = ReviewBatch.from_record(_read_unique_json(args.review))
    binding = pinned_binding()
    if args.check:
        report = verify_s2_archive(context, config, args.draft, args.claims,
                                   args.s1, review, binding, args.output)
    else:
        verifier = SyntheticV3Verifier(DevelopmentV2(TransformersNLIBackend()))
        report = create_s2_archive(context, config, args.draft, args.claims,
                                   args.s1, review, verifier, binding,
                                   args.output)
    s2_fork = read_common_fork(context, config, args.draft, args.claims,
                               args.s1, review, binding, args.output, arm="S2")
    s3_fork = read_common_fork(context, config, args.draft, args.claims,
                               args.s1, review, binding, args.output, arm="S3")
    if s2_fork != s3_fork:
        raise ValueError("s2_s3_fork_mismatch")
    print(json.dumps({
        "result": "PASS_SYNTHETIC_S2_ONLY",
        "mode": "check" if args.check else "create",
        "archive": str(args.output),
        "draft_id": report["draft_id"],
        "initial_verification_count": sum(item["variant"] == "initial"
                                          for item in report["verification"]),
        "final_claim_count": len(report["final_claims"]),
        "review_queue_count": sum(item["review_required"]
                                  for item in report["decisions"]),
        "fork_sha256": hashlib.sha256(s2_fork).hexdigest(),
        "manifest_sha256": hashlib.sha256(
            (args.output / "manifest.json").read_bytes()).hexdigest(),
        "gold_status": "NOT_GOLD",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
