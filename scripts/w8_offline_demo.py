"""Create or check a content-pinned W8 synthetic demo archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from egis_soc.integrity import canonical_bytes
from egis_soc.w8_demo import FIXTURES, ROOT, VERSION, run_case


DEFAULT_OUTPUT = ROOT / "experiments" / "w8_02_synthetic_demo_v5"
SOURCE_FILES = (
    "src/egis_soc/w8_demo.py", "src/egis_soc/w8_api.py",
    "src/egis_soc/w8_splunk.py", "src/egis_soc/w8_auth.py",
    "src/egis_soc/summarization/review_api.py",
    "src/egis_soc/summarization/review_v2.py",
    "src/egis_soc/schemas.py", "src/egis_soc/development_retrieval.py",
    "src/egis_soc/development/fusion.py", "src/egis_soc/development/rules.py",
    "src/egis_soc/summarization/contract.py",
    "src/egis_soc/summarization/atomization.py",
    "src/egis_soc/summarization/s1.py", "src/egis_soc/summarization/s2.py",
    "src/egis_soc/summarization/omission.py",
    "src/egis_soc/summarization/s3.py",
    "src/egis_soc/summarization/final_report.py",
    "scripts/w8_offline_demo.py", "scripts/w8_demo_server.py",
    "scripts/w8_review_password.py", "scripts/w8_review_dir.ps1",
    "dashboard/w8_demo.html", "dashboard/w8_demo.js", "dashboard/w8_demo.css",
    "tests/test_w8_demo.py", "tests/test_w8_review.py",
    "tests/test_w8_splunk.py", "requirements.txt",
    "requirements-w3.txt", "requirements-w6.txt", "requirements-w7.txt",
    "requirements-w8.txt", "requirements-w8-offline.txt", ".env.example",
    "README.md",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stable(report: dict) -> bytes:
    record = json.loads(canonical_bytes(report))
    for item in record["repair_verifications"]:
        item["v3_latency_ns"] = 0
    return canonical_bytes(record)


def _source_hashes() -> dict[str, str]:
    return {name: _sha((ROOT / name).read_bytes()) for name in SOURCE_FILES}


def _manifest(reports: dict[str, bytes]) -> dict:
    return {
        "version": VERSION, "mode": "SYNTHETIC_OFFLINE_NOT_GOLD",
        "fixture_sha256": {case: _sha(path.read_bytes())
                           for case, path in FIXTURES.items()},
        "source_sha256": _source_hashes(),
        "report_sha256": {case: _sha(raw) for case, raw in reports.items()},
        "stable_report_sha256": {case: _sha(_stable(json.loads(raw)))
                                 for case, raw in reports.items()},
        "real_splunk": "NOT_RUN", "research_evaluation": "NOT_RUN",
    }


def create(target: Path) -> dict:
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w8_archive_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w8_archive_parent_required")
    reports = {case: canonical_bytes(run_case(case)) for case in FIXTURES}
    manifest = _manifest(reports)
    target.mkdir(exist_ok=False)
    for name, raw in [(case + ".json", reports[case]) for case in FIXTURES] + [
            ("manifest.json", canonical_bytes(manifest))]:
        with (target / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return manifest


def check(target: Path) -> dict:
    target = Path(target)
    required = {case + ".json" for case in FIXTURES} | {"manifest.json"}
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} != required
            or any((target / name).is_symlink() for name in required)):
        raise ValueError("w8_archive_file_set_invalid")
    raw = {case: (target / (case + ".json")).read_bytes() for case in FIXTURES}
    manifest_raw = (target / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    if (manifest_raw != canonical_bytes(manifest)
            or any(value != canonical_bytes(json.loads(value)) for value in raw.values())
            or manifest != _manifest(raw)):
        raise ValueError("w8_archive_drift")
    rerun = {case: _sha(_stable(run_case(case))) for case in FIXTURES}
    if rerun != manifest["stable_report_sha256"]:
        raise ValueError("w8_replay_drift")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = check(args.output) if args.check else create(args.output)
    print(json.dumps({"archive": str(args.output), "check": args.check,
                      "report_sha256": result["report_sha256"],
                      "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
