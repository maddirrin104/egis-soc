"""Create/check a matched, offline V0/V2/V3 synthetic diagnostic.

No PDS-01 event, weak label, accepted pilot, or held-out artifact is opened.
The create path is exclusive and never overwrites an existing result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

from egis_soc.development.w4_diagnostic import (
    result_bytes, run_fixture, verify_result,
)
from egis_soc.development.fusion import FusionPolicy
from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION
from egis_soc.integrity import canonical_bytes
from egis_soc.public_pilot_intake import _assert_no_links
from w3_development_smoke import (
    ROOT as SMOKE_ROOT, SMOKE_MANIFEST_SHA256, _model_cache_hashes,
)
from w3_v2_batch_qa import CACHE


WORKSPACE = Path(__file__).resolve().parents[1]
FIXTURE = WORKSPACE / "tests/fixtures/w4_matched_synthetic_v1.json"
ROOT = WORKSPACE / "experiments/w4_matched_synthetic_v1"
VERSION = "w4-matched-synthetic-run-1"
CODE_PATHS = (
    "src/egis_soc/development/contract.py",
    "src/egis_soc/development/rules.py",
    "src/egis_soc/development/fusion.py",
    "src/egis_soc/development/w4_diagnostic.py",
    "src/egis_soc/development_data.py",
    "src/egis_soc/development_retrieval.py",
    "src/egis_soc/development_v2.py",
    "scripts/w4_synthetic_diagnostic.py",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _pinned_model() -> dict[str, str]:
    # Set offline mode before constructing the Transformers backend.
    os.environ["HF_HOME"] = str(CACHE)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    _assert_no_links(SMOKE_ROOT / "manifest.json")
    if _sha(SMOKE_ROOT / "manifest.json") != SMOKE_MANIFEST_SHA256:
        raise ValueError("w4_pinned_smoke_manifest_changed")
    smoke = json.loads((SMOKE_ROOT / "manifest.json").read_bytes())
    for name, digest in smoke["output_sha256"].items():
        if _sha(SMOKE_ROOT / name) != digest:
            raise ValueError("w4_pinned_smoke_output_changed")
    technical = json.loads((SMOKE_ROOT / "technical_smoke.json").read_bytes())
    synthetic = json.loads((SMOKE_ROOT / "synthetic_experiment.json").read_bytes())
    v2_path = "src/egis_soc/development_v2.py"
    if (technical["v2"]["model_id"] != MODEL_ID
            or technical["v2"]["revision"] != MODEL_REVISION
            or _sha(WORKSPACE / v2_path) != synthetic["code_sha256"][v2_path]):
        raise ValueError("w4_v2_checkpoint_changed")
    hashes = _model_cache_hashes()
    if hashes != technical["v2"]["model_cache_file_sha256"]:
        raise ValueError("w4_model_cache_changed")
    return hashes


def _inputs() -> tuple[dict, dict[str, str], dict[str, str], dict[str, str]]:
    _assert_no_links(FIXTURE)
    fixture = json.loads(FIXTURE.read_bytes())
    model_hashes = _pinned_model()
    code_hashes = {name: _sha(WORKSPACE / name) for name in CODE_PATHS}
    dependencies = {name: version(name) for name in ("torch", "transformers")}
    return fixture, model_hashes, code_hashes, dependencies


def _manifest(result: dict, model_hashes: dict[str, str],
              code_hashes: dict[str, str], dependencies: dict[str, str]) -> dict:
    policy = FusionPolicy()
    return {
        "version": VERSION, "dataset_kind": "authored_synthetic_train",
        "label_provenance": "SYNTHETIC_KNOWN_ANSWER",
        "gold_status": "NOT_GOLD", "real_pilot_metric": result["real_pilot_metric"],
        "rq1_claim": result["rq1_claim"],
        "fixture_sha256": _sha(FIXTURE), "code_sha256": code_hashes,
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "model_cache_file_sha256": model_hashes,
        "smoke_manifest_sha256": SMOKE_MANIFEST_SHA256,
        "policy_version": policy.version, "policy_sha256": policy.sha256,
        "policy_calibration_status": policy.calibration_status,
        "python_dependencies": dependencies,
        "case_count": result["case_count"],
        "result_sha256": hashlib.sha256(result_bytes(result)).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify saved hashes and cases")
    parser.add_argument("--replay", action="store_true",
                        help="With --check, rerun the pinned model and compare exact outputs")
    args = parser.parse_args()
    if args.replay and not args.check:
        parser.error("--replay requires --check")
    _assert_no_links(ROOT)
    fixture, model_hashes, code_hashes, dependencies = _inputs()
    if args.check:
        if not ROOT.is_dir() or {path.name for path in ROOT.iterdir()} != {
                "result.json", "manifest.json"}:
            raise ValueError("w4_diagnostic_output_set_changed")
        manifest = json.loads((ROOT / "manifest.json").read_bytes())
        if _sha(ROOT / "result.json") != manifest.get("result_sha256"):
            raise ValueError("w4_diagnostic_result_hash_changed")
        result = json.loads((ROOT / "result.json").read_bytes())
        verify_result(fixture, result)
        if manifest != _manifest(result, model_hashes, code_hashes, dependencies):
            raise ValueError("w4_diagnostic_manifest_changed")
        if args.replay and result_bytes(run_fixture(fixture)) != (ROOT / "result.json").read_bytes():
            raise ValueError("w4_diagnostic_model_replay_changed")
    else:
        if ROOT.exists():
            raise FileExistsError("w4_diagnostic_exists; use --check")
        result = run_fixture(fixture)
        verify_result(fixture, result)
        manifest = _manifest(result, model_hashes, code_hashes, dependencies)
        ROOT.mkdir(parents=True, exist_ok=False)
        with (ROOT / "result.json").open("xb") as stream:
            stream.write(result_bytes(result))
        with (ROOT / "manifest.json").open("xb") as stream:
            stream.write(canonical_bytes(manifest))
    print(json.dumps({
        "result": "PASS_SYNTHETIC_DEV_ONLY", "cases": result["case_count"],
        "manifest_sha256": _sha(ROOT / "manifest.json"),
        "errors": {arm: result["summary"]["arms"][arm]["error_counts"]
                   for arm in ("V0", "V2", "V3")},
        "review_counts": {arm: result["summary"]["arms"][arm]["review_count"]
                          for arm in ("V0", "V2", "V3")},
        "real_pilot_metric": result["real_pilot_metric"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
