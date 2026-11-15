"""Create/check the W5-05 synthetic operational inventory and S2 omission screen."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION
from egis_soc.summarization.generation import GenerationConfig
from egis_soc.summarization.omission import (
    create_omission_archive, verify_omission_archive,
)
from egis_soc.summarization.s2 import ReviewBatch
from w5_model_binding import pinned_binding
from w5_synthetic_draft import synthetic_context
from w5_synthetic_s2 import (
    DEFAULT_CLAIMS, DEFAULT_DRAFT, DEFAULT_REVIEW, DEFAULT_S1,
    DEFAULT_OUTPUT as DEFAULT_S2, _read_unique_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_05_synthetic_omission_v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--s1", type=Path, default=DEFAULT_S1)
    parser.add_argument("--s2", type=Path, default=DEFAULT_S2)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    context = synthetic_context()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    review = ReviewBatch.from_record(_read_unique_json(args.review))
    binding = pinned_binding()
    run = verify_omission_archive if args.check else create_omission_archive
    report = run(context, config, args.draft, args.claims, args.s1,
                 review, binding, args.s2, args.output)
    print(json.dumps({
        "result": "PASS_SYNTHETIC_OPERATIONAL_OMISSION_ONLY",
        "mode": "check" if args.check else "create",
        "archive": str(args.output),
        "source_fork_sha256": report["fork_sha256"],
        "inventory_fact_count": len(report["findings"]),
        "candidate_unmentioned_count": sum(
            item["outcome"] == "candidate_unmentioned"
            for item in report["findings"]),
        "unknown_count": sum(item["outcome"] == "unknown"
                             for item in report["findings"]),
        "manifest_sha256": hashlib.sha256(
            (args.output / "manifest.json").read_bytes()).hexdigest(),
        "gold_status": report["gold_status"],
        "cfr_status": report["cfr_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
