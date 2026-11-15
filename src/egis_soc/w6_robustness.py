"""Deterministic, synthetic development perturbations; never evaluation gold."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .development_data import DevelopmentData

VERSION = "w6-robustness-1"
KINDS = frozenset({"R1", "R2", "R3", "R4", "R5", "R6"})
_DENIED = frozenset({"gold", "gold_status", "label", "human_label", "prediction",
                     "score", "test_ids", "ood_ids", "split_id"})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _replace(value: Any, substitutions: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        # Whole literals only: partial replacements can corrupt IDs and source references.
        return substitutions.get(value, value)
    if isinstance(value, Mapping):
        return {key: _replace(item, substitutions) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_replace(item, substitutions) for item in value]
    return value


def _check_unsealed(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.casefold() in _DENIED or "gold" in key.casefold():
                raise ValueError("evaluation_content_forbidden")
            _check_unsealed(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_unsealed(item)


@dataclass(frozen=True)
class Variant:
    variant_id: str
    parent_incident_id: str
    tenant_id: str
    partition: str
    lineage_group: str
    transformation_id: str
    seed: int
    events: tuple[Mapping[str, Any], ...]
    relabel_status: str

    def development_view(self) -> DevelopmentData:
        """Pass an explicit variant view to the existing scoped W3 retriever."""
        return DevelopmentData(self.parent_incident_id, self.tenant_id,
                               self.partition, self.lineage_group, "synthetic", None,
                               self.events)

    def resolve(self, evidence_id: str, *, incident_id: str, tenant_id: str) -> Mapping[str, Any]:
        if incident_id != self.parent_incident_id or tenant_id != self.tenant_id:
            raise PermissionError("foreign_incident_or_tenant")
        for event in self.events:
            if event["evidence_id"] == evidence_id:
                return event
        raise KeyError("unknown_variant_evidence_id")


def make_variant(parent: DevelopmentData, kind: str, *, seed: int,
                 options: Mapping[str, Any]) -> Variant:
    """Build a detached view. R5/R6 always require fresh human support review."""
    if not isinstance(parent, DevelopmentData) or parent.source_dataset != "synthetic":
        raise ValueError("synthetic_development_only")
    if parent.partition not in {"train", "validation", "designated_pilot"}:
        raise ValueError("protected_partition")
    if kind not in KINDS or type(seed) is not int or seed < 0:
        raise ValueError("invalid_transformation")
    if not isinstance(options, Mapping):
        raise ValueError("invalid_options")
    rows = [dict(event) for event in parent.events]
    if not rows or len({row["evidence_id"] for row in rows}) != len(rows):
        raise ValueError("invalid_parent_evidence")
    for row in rows:
        _check_unsealed(row)
        if row.get("incident_id") != parent.incident_id or row.get("tenant_id") != parent.tenant_id:
            raise ValueError("foreign_parent_evidence")
        if not all(isinstance(row.get(key), str) and row[key] for key in
                   ("evidence_id", "source_ref", "raw_sha256", "raw_message_ref")):
            raise ValueError("missing_source_provenance")
    if kind == "R1":
        mapping = options.get("substitutions")
        if (not isinstance(mapping, Mapping) or not mapping
                or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                       for k, v in mapping.items())
                or len(set(mapping.values())) != len(mapping)):
            raise ValueError("invalid_entity_mapping")
        existing = {value for row in rows for value in row["event_data"].values()
                    if isinstance(value, str)}
        if set(mapping.values()) & (existing - set(mapping)):
            raise ValueError("entity_mapping_collision")
        for row in rows:
            row["event_data"] = _replace(row["event_data"], mapping)
    elif kind == "R2":
        mapping = options.get("field_names")
        if (not isinstance(mapping, Mapping) or not mapping
                or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                       for k, v in mapping.items())):
            raise ValueError("invalid_field_mapping")
        for row in rows:
            data = dict(row["event_data"])
            names = [mapping.get(key, key) for key in data]
            if len(names) != len(set(names)):
                raise ValueError("field_name_collision")
            row["event_data"] = {mapping.get(k, k): v for k, v in data.items()}
    elif kind == "R3":
        minutes = options.get("utc_offset_minutes")
        if type(minutes) is not int or not -840 <= minutes <= 840:
            raise ValueError("invalid_utc_offset")
        offset = timezone(timedelta(minutes=minutes))
        for row in rows:
            stamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("naive_source_timestamp")
            row["timestamp_display"] = stamp.astimezone(offset).isoformat()
    elif kind == "R4":
        count = options.get("count")
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("invalid_noise_count")
        for index in range(count):
            digest = hashlib.sha256(f"{parent.incident_id}:{seed}:{index}".encode()).hexdigest()
            raw = f"synthetic benign noise {digest}"
            rows.append({"evidence_id": f"SYN-W6-NOISE-{digest[:16]}",
                         "incident_id": parent.incident_id, "tenant_id": parent.tenant_id,
                         "source_ref": f"synthetic:w6-noise:{digest}",
                         "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                         "raw_message_ref": f"synthetic:w6-noise:{digest}",
                         "source_dataset": "synthetic", "timestamp_utc": rows[0]["timestamp_utc"],
                         "event_data": {"log_source": "synthetic_benign_noise", "event": "benign"},
                         "synthetic_noise": True})
    elif kind == "R5":
        remove = options.get("remove_evidence_ids")
        known = {row["evidence_id"] for row in rows}
        if not isinstance(remove, (list, tuple)) or not remove or len(remove) != len(set(remove)) or not set(remove) <= known:
            raise ValueError("invalid_removal_set")
        rows = [row for row in rows if row["evidence_id"] not in remove]
    else:
        remove = options.get("remove_log_sources")
        sources = {row["event_data"].get("log_source") for row in rows}
        if (not isinstance(remove, (list, tuple)) or not remove
                or any(not isinstance(source, str) or not source for source in remove)
                or len(remove) != len(set(remove)) or not set(remove) <= sources):
            raise ValueError("invalid_source_mix")
        rows = [row for row in rows if row["event_data"].get("log_source") not in remove]
    if kind in {"R5", "R6"} and len(rows) == len(parent.events):
        raise ValueError("no_telemetry_removed")
    config = json.dumps({"kind": kind, "seed": seed, "options": options}, sort_keys=True,
                        separators=(",", ":"), ensure_ascii=True)
    transformation_id = hashlib.sha256(config.encode()).hexdigest()
    variant_id = f"{parent.incident_id}:W6:{transformation_id[:16]}"
    for row in rows:
        row["parent_evidence_id"] = None if row.get("synthetic_noise") else row["evidence_id"]
        row["variant_id"] = variant_id
    return Variant(variant_id, parent.incident_id, parent.tenant_id, parent.partition,
                   parent.lineage_group, transformation_id, seed,
                   tuple(_freeze(row) for row in rows),
                   "HUMAN_REVIEW_REQUIRED" if kind in {"R5", "R6"} else "INVARIANT_CHECK_REQUIRED")
