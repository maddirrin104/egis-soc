"""Create/check an S1 display packet from the saved synthetic W5-01/02 archives."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from egis_soc.summarization.generation import GenerationConfig
from egis_soc.summarization.s1 import create_s1_archive, verify_s1_archive
from w5_synthetic_draft import synthetic_context


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT = ROOT / "experiments" / "w5_01_local_synthetic_v1"
DEFAULT_CLAIMS = ROOT / "experiments" / "w5_02_synthetic_claims_v2"
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_03_synthetic_s1_v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    context = synthetic_context()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    operation = verify_s1_archive if args.check else create_s1_archive
    report = operation(context, config, args.draft, args.claims, args.output)
    print(json.dumps({
        "result": "PASS_SYNTHETIC_S1_ONLY",
        "mode": "check" if args.check else "create",
        "archive": str(args.output), "draft_id": report.draft_id,
        "claim_count": len(report.claims),
        "review_count": sum(bool(claim.review_reasons) for claim in report.claims),
        "manifest_sha256": hashlib.sha256(
            (args.output / "manifest.json").read_bytes()).hexdigest(),
        "verification_status": report.verification_status,
        "gold_status": "NOT_GOLD",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
