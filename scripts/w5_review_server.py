"""Serve the fixed W5-07 synthetic packet on localhost for explicit review."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from wsgiref.simple_server import make_server

from egis_soc.integrity import canonical_bytes
from egis_soc.summarization.final_report import STATUS, VERSION, _surface_hashes
from egis_soc.summarization.review_api import ReviewApp, ReviewStore
from w5_synthetic_final_report import DEFAULT_OUTPUT


ROOT = Path(__file__).resolve().parents[1]
PARENTS = {
    "s1": ROOT / "experiments" / "w5_03_synthetic_s1_v1",
    "s2": ROOT / "experiments" / "w5_04_synthetic_s2_v2",
    "omission": ROOT / "experiments" / "w5_05_synthetic_omission_v1",
    "s3": ROOT / "experiments" / "w5_06_synthetic_s3_v2",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_packet() -> dict:
    """Check fixed archive bytes and current parents before serving anything."""
    target = DEFAULT_OUTPUT
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} !=
            {"report.json", "manifest.json"}
            or any((target / name).is_symlink() for name in
                   ("report.json", "manifest.json"))):
        raise ValueError("invalid_w5_07_packet")
    raw = (target / "report.json").read_bytes()
    report = json.loads(raw)
    manifest_raw = (target / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    code_path = ROOT / "src" / "egis_soc" / "summarization" / "final_report.py"
    expected = {"version": VERSION, "status": STATUS,
                "report_sha256": _sha(raw),
                "source_manifest_sha256": {
                    key: _sha((path / "manifest.json").read_bytes())
                    for key, path in PARENTS.items()},
                "code_sha256": _sha(code_path.read_bytes()),
                "surface_sha256": _surface_hashes(),
                "gold_status": "NOT_GOLD"}
    if (raw != canonical_bytes(report) or manifest_raw != canonical_bytes(manifest)
            or manifest != expected or report.get("version") != VERSION
            or report.get("status") != STATUS):
        raise ValueError("w5_07_packet_drift")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", required=True, type=Path,
                        help="Existing private directory outside the Git workspace")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    review_dir = args.review_dir.resolve()
    if review_dir == ROOT or ROOT in review_dir.parents:
        raise ValueError("review_log_must_be_outside_repository")
    report = load_packet()
    store = ReviewStore(review_dir, report)
    token = secrets.token_urlsafe(32)
    app = ReviewApp(report, store, token,
                    (ROOT / "dashboard" / "w5_review.html").read_bytes(),
                    (ROOT / "dashboard" / "w5_review.js").read_bytes())
    with make_server("127.0.0.1", args.port, app) as server:
        print(f"Local synthetic review: http://127.0.0.1:{server.server_port}/", flush=True)
        print(f"Session token: {token}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
