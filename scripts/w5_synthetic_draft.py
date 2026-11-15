"""Create/check one W5-01 local-model draft on authored synthetic evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, IncidentBundle
from egis_soc.summarization.contract import retrieve_synthetic_incident
from egis_soc.summarization.generation import (
    GenerationConfig, OllamaLocalBackend, generate_and_archive, verify_archive,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "experiments" / "w5_01_local_synthetic_v1"


def synthetic_context():
    raw = "synthetic record R1: alice logon success on WS01"
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    provenance = EvidenceProvenance(
        source="synthetic:w5-01-smoke", timestamp_utc=timestamp,
        raw_message=raw, raw_message_ref="synthetic:w5:E1",
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        acquisition_method="authored_synthetic_fixture")
    event = EvidenceEvent(
        evidence_id="E1", incident_id="SYN-W5", tenant_id="SYN-T",
        normalized_fields={"record_ref": "R1", "event_type": "logon",
                           "actor": "alice", "host": "WS01",
                           "outcome": "success"},
        provenance=provenance)
    bundle = IncidentBundle(
        incident_id="SYN-W5", tenant_id="SYN-T", environment_id="SYNTHETIC",
        source_dataset="synthetic", scenario_family="w5_01_authored_smoke",
        alert_ids=("SYN-A1",), evidence_ids=("E1",))
    return retrieve_synthetic_incident(bundle, (event,), query="logon")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    context = synthetic_context()
    config = GenerationConfig(args.model, args.digest, num_predict=256)
    if args.check:
        draft = verify_archive(context, config, args.output)
    else:
        draft = generate_and_archive(context, config, OllamaLocalBackend(),
                                     args.output)
    manifest = args.output / "manifest.json"
    print(json.dumps({
        "result": "PASS_SYNTHETIC_DRAFT_ONLY", "mode": "check" if args.check else "create",
        "archive": str(args.output), "draft_id": draft.draft_id,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "model_name": config.model_name, "model_digest": config.model_digest,
        "real_pilot_metric": "NOT_RUN_SYNTHETIC_DRAFT_ONLY",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
