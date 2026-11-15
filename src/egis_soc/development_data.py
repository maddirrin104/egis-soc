"""Read-only W3 input contract for synthetic and pinned private development data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .pds01_provisional import VERSION, load_bundle
from .public_pilot_intake import _canonical
from .schemas import EvidenceEvent, IncidentBundle


PDS01_MANIFEST_SHA256 = "e6fc191d4984458fdd936d73b9b44554e9652486cbc4f63a47ecc3eac37e1d65"
PDS01_GROUPS = frozenset({"S01", "S02", "S03", "S05", "S06", "S07", "S08", "S10", "S11", "S12"})
_S07_FIELDS = frozenset({"CommandLine", "ParentCommandLine", "Details", "User"})


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _required(row: Mapping[str, Any], *names: str) -> None:
    if any(not isinstance(row.get(name), str) or not row[name].strip() for name in names):
        raise ValueError("missing_development_identity_or_provenance")


@dataclass(frozen=True)
class DevelopmentData:
    """Detached, immutable records; resolves only within the declared scope."""

    incident_id: str
    tenant_id: str
    partition: str
    lineage_group: str
    source_dataset: str
    manifest_sha256: str | None
    events: tuple[Mapping[str, Any], ...]

    def resolve(self, evidence_id: str, *, incident_id: str, tenant_id: str) -> Mapping[str, Any]:
        if incident_id != self.incident_id or tenant_id != self.tenant_id:
            raise PermissionError("foreign_incident_or_tenant")
        for event in self.events:
            if event["evidence_id"] == evidence_id:
                return event
        raise KeyError("unknown_evidence_id")


def load_private_pds01_group(root: Path, group: str) -> DevelopmentData:
    """Read one group only after checking the fixed manifest and its output hash."""
    if group not in PDS01_GROUPS:
        raise ValueError("unapproved_pds01_group")
    root = Path(root)
    manifest_path = root / "manifest.json"
    if root.is_symlink() or manifest_path.is_symlink():
        raise ValueError("linked_development_path")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != PDS01_MANIFEST_SHA256:
        raise ValueError("unverified_development_manifest")
    manifest = json.loads(manifest_bytes)
    if (manifest.get("version") != VERSION
            or manifest.get("status") != "UNREVIEWED_DEVELOPMENT"
            or manifest.get("accepted_pilot_count") != 0
            or manifest.get("human_reviewed_label_count") != 0
            or manifest.get("production_real_id_count") != 0
            or set(manifest.get("output_hashes", {})) != PDS01_GROUPS):
        raise ValueError("invalid_development_manifest")
    folder = root / group
    names = ("bundle.json", "events.jsonl", "pairs.jsonl", "facts.jsonl")
    if folder.is_symlink() or any((folder / name).is_symlink() for name in names):
        raise ValueError("linked_development_path")
    file_hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in names}
    if hashlib.sha256(_canonical(file_hashes)).hexdigest() != manifest["output_hashes"][group]:
        raise ValueError("unverified_development_output")
    bundle, events = load_bundle(folder)
    if (bundle.get("scenario") != group
            or bundle.get("incident_id") != f"PDS01-DEV-{group}-v1"
            or bundle.get("tenant_id") != "UNKNOWN"
            or bundle.get("environment_id") != "PDS01_PRIVATE_DEVELOPMENT"
            or bundle.get("source_dataset") != "PDS-01"
            or bundle.get("partition") != "train_designated_grouped"
            or bundle.get("lineage_group") != "PDS01_ALL"
            or bundle.get("upstream_original_run_id") != "UNKNOWN"
            or bundle.get("annotation_status") != "AI_PROPOSED_UNREVIEWED_NOT_GOLD"
            or bundle.get("boundary_status") != "AI_PROPOSED_NOT_OWNER_REVIEWED"):
        raise ValueError("invalid_development_scope")
    for name in ("pairs.jsonl", "facts.jsonl"):
        for line in (folder / name).read_bytes().splitlines():
            row = json.loads(line)
            if (row.get("annotation_source") != "AI_PROPOSED"
                    or row.get("gold_status") != "NOT_GOLD"
                    or row.get("human_label", row.get("human_status")) != "UNREVIEWED"):
                raise ValueError("reviewed_or_gold_annotation_forbidden")
    for event in events:
        _required(event, "evidence_id", "source_ref", "source_key", "repository_path",
                  "timestamp_utc", "timestamp_original", "artifact_sha256", "raw_sha256",
                  "raw_message_ref", "incident_id", "tenant_id")
        if (event.get("version") != VERSION
                or event.get("membership_status") != "AI_PROPOSED_INCLUDE_UNREVIEWED"
                or not isinstance(event.get("event_data"), dict)
                or event.get("source_dataset") != "PDS-01"):
            raise ValueError("invalid_development_event")
        if group == "S07" and any(
                event["event_data"].get(field) not in (None, "[REDACTED]")
                for field in _S07_FIELDS):
            raise ValueError("s07_redaction_failed")
    return DevelopmentData(bundle["incident_id"], "UNKNOWN", "train_designated_grouped",
                           "PDS01_ALL", "PDS-01", PDS01_MANIFEST_SHA256,
                           tuple(_freeze(event) for event in events))


def from_synthetic_fixture(bundle: IncidentBundle,
                           events: Sequence[EvidenceEvent]) -> DevelopmentData:
    """Adapt explicit synthetic W1 fixtures; never import their evaluation gold."""
    if bundle.source_dataset != "synthetic" or bundle.environment_id != "SYNTHETIC":
        raise ValueError("non_synthetic_development_input")
    if not events or len(events) != len(bundle.evidence_ids):
        raise ValueError("synthetic_evidence_index_mismatch")
    result: list[Mapping[str, Any]] = []
    for event in events:
        bundle.check_scope(event)
        if event.evidence_id not in bundle.evidence_ids or not event.provenance.source.startswith("synthetic:"):
            raise ValueError("non_synthetic_development_event")
        result.append(_freeze({
            "evidence_id": event.evidence_id,
            "incident_id": event.incident_id,
            "tenant_id": event.tenant_id,
            "source_ref": event.provenance.raw_message_ref,
            "timestamp_utc": event.provenance.timestamp_utc.isoformat(),
            "timestamp_original": event.provenance.timestamp_utc.isoformat(),
            "source_dataset": "synthetic",
            "raw_sha256": event.provenance.sha256,
            "raw_message_ref": event.provenance.raw_message_ref,
            "event_data": dict(event.normalized_fields),
        }))
    if tuple(event["evidence_id"] for event in result) != bundle.evidence_ids:
        raise ValueError("synthetic_evidence_index_mismatch")
    return DevelopmentData(bundle.incident_id, bundle.tenant_id, "train", "SYNTHETIC",
                           "synthetic", None, tuple(result))
