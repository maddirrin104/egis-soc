"""Create/check W5-02 claim candidates from the saved W5-01 synthetic draft."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from egis_soc.summarization.atomization import (
    create_claim_archive, verify_claim_archive,
)
from egis_soc.summarization.generation import GenerationConfig
from w5_synthetic_draft import synthetic_context


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "experiments" / "w5_01_local_synthetic_v1"
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_02_synthetic_claims_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    context = synthetic_context()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    if args.check:
        result = verify_claim_archive(context, config, args.source, args.output)
    else:
        result = create_claim_archive(context, config, args.source, args.output)
    print(json.dumps({
        "result": "PASS_SYNTHETIC_CANDIDATES_ONLY",
        "mode": "check" if args.check else "create",
        "archive": str(args.output),
        "source_draft_id": result.draft.draft_id,
        "claim_count": len(result.draft.claims),
        "review_count": result.review_count,
        "manifest_sha256": hashlib.sha256(
            (args.output / "manifest.json").read_bytes()).hexdigest(),
        "verification_status": "NOT_RUN_PRE_VERIFICATION",
        "gold_status": "NOT_GOLD",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
