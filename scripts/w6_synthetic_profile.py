"""Create/check a small W3 retrieval + W6 transformation profiling archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from egis_soc.development_data import DevelopmentData
from egis_soc.development_retrieval import DevelopmentRetriever
from egis_soc.integrity import canonical_bytes
from egis_soc.w6_environment_b import VERSION as B_VERSION, audit_environment_b
from egis_soc.w6_profiling import profile_stages
from egis_soc.w6_robustness import make_variant

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "w6_synthetic_workload_v1.json"
OUTPUT = ROOT / "experiments" / "w6_synthetic_engineering_v3"
FILES = ("report.json", "manifest.json")
CODE_FILES = ("scripts/w6_synthetic_profile.py", "src/egis_soc/w6_environment_b.py",
              "src/egis_soc/w6_robustness.py", "src/egis_soc/w6_profiling.py",
              "src/egis_soc/development_retrieval.py")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_fixture() -> tuple[DevelopmentData, str]:
    raw = FIXTURE.read_bytes()
    obj = json.loads(raw)
    if (obj.get("version") != "w6-synthetic-workload-1"
            or obj.get("partition") != "train"
            or obj.get("lineage_group") != "SYNTHETIC"
            or obj.get("source_dataset") != "synthetic"):
        raise ValueError("invalid_w6_fixture_scope")
    events = obj["events"]
    if not events or any(event.get("incident_id") != obj["incident_id"]
                         or event.get("tenant_id") != obj["tenant_id"]
                         or event.get("source_dataset") != "synthetic"
                         or not event.get("source_ref", "").startswith("synthetic:")
                         for event in events):
        raise ValueError("invalid_w6_fixture_evidence")
    return DevelopmentData(obj["incident_id"], obj["tenant_id"], "train", "SYNTHETIC",
                           "synthetic", None, tuple(events)), _sha(raw)


def _report() -> dict:
    data, fixture_hash = _load_fixture()

    def retrieval():
        hits = DevelopmentRetriever(data).search("logon", incident_id=data.incident_id,
                                                  tenant_id=data.tenant_id)
        if not hits or hits[0].evidence_id != "SYN-W6-E1":
            raise ValueError("synthetic_retrieval_drift")
        return None

    def transformations():
        for kind, options in (
            ("R1", {"substitutions": {"WS01": "WS02", "192.0.2.1": "198.51.100.2"}}),
            ("R2", {"field_names": {"host": "computer"}}),
            ("R3", {"utc_offset_minutes": 420}),
            ("R4", {"count": 1}),
            ("R5", {"remove_evidence_ids": ["SYN-W6-E1"]}),
            ("R6", {"remove_log_sources": ["sysmon"]}),
        ):
            variant = make_variant(data, kind, seed=14, options=options)
            if variant.partition != data.partition or variant.tenant_id != data.tenant_id:
                raise ValueError("variant_scope_drift")
        return None

    profile = profile_stages(
        [("w3_retrieval", retrieval), ("w6_r1_r6_transformations", transformations)],
        workload_ref=f"tests/fixtures/w6_synthetic_workload_v1.json#sha256={fixture_hash}",
        repetitions=3, context_config={"retrieval_query": "logon", "fixture_events": 2},
        model={"status": "NOT_MEASURED", "checkpoint": "cross-encoder/nli-distilroberta-base",
               "revision": "b14d131f9d32668a5e6a982729b57ff6ed5dfcbd",
               "quantization": "NOT_MEASURED", "reason": "no_model_inference_in_workload"})
    return {"status": "SYNTHETIC_ENGINEERING_ONLY", "fixture_sha256": fixture_hash,
            "environment_b": audit_environment_b({"version": B_VERSION}),
            "profiling": profile, "robustness": {"transformations": [f"R{i}" for i in range(1, 7)],
                                                "r5_r6_relabel": "HUMAN_REVIEW_REQUIRED"},
            "research_metrics": "NOT_MEASURED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output
    if args.check:
        if not output.is_dir() or output.is_symlink() or set(p.name for p in output.iterdir()) != set(FILES):
            raise ValueError("invalid_w6_archive")
        report_raw = (output / "report.json").read_bytes()
        manifest_raw = (output / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        if (manifest_raw != canonical_bytes(manifest)
                or report_raw != canonical_bytes(json.loads(report_raw))
                or manifest.get("report_sha256") != _sha(report_raw)
                or manifest.get("fixture_sha256") != _sha(FIXTURE.read_bytes())
                or manifest.get("code_sha256") != {
                    name: _sha((ROOT / name).read_bytes()) for name in CODE_FILES}):
            raise ValueError("w6_archive_hash_mismatch")
        print(json.dumps({"status": "PASS_ARCHIVE_INTEGRITY", "report_sha256": _sha(report_raw)}))
        return 0
    report = _report()
    output.mkdir(parents=True, exist_ok=False)
    report_raw = canonical_bytes(report)
    with (output / "report.json").open("xb") as stream:
        stream.write(report_raw)
    manifest_raw = canonical_bytes({"version": "w6-synthetic-archive-1",
                                    "fixture_sha256": report["fixture_sha256"],
                                    "code_sha256": {
                                        name: _sha((ROOT / name).read_bytes()) for name in CODE_FILES},
                                    "report_sha256": _sha(report_raw)})
    with (output / "manifest.json").open("xb") as stream:
        stream.write(manifest_raw)
    print(json.dumps({"status": "SYNTHETIC_PROFILE_CREATED", "report_sha256": _sha(report_raw),
                      "environment_b": report["environment_b"]["status"],
                      "profile_success": report["profiling"]["summary"]["success"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
