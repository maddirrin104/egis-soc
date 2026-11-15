"""Synthetic D-021 v2/v3 direct-XML manifest preflight and replay.

Only caller-supplied bytes are accepted. This module has no file reader, real
allocator, audit writer, or Environment A authorization path. Preview IDs
computed here are test vectors, never issued production identities.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Mapping

from egis_soc.governance.integrity import canonical_bytes
from egis_soc.sources.public_xml_boundary_preview import (
    ParsedXmlEvent, XmlBoundaryPreviewError, parse_xml_event,
    preview_direct_xml_lines,
)
from egis_soc.sources.real_identity_preview import (
    V2_POLICY_VERSION, V2_REPOSITORY, V2_REVISION, V3_POLICY_VERSION,
    canonical_source_preimage_v2, preview_scoped_id_v2, preview_source_id_v2,
    canonical_source_preimage_v3, preview_scoped_id_v3, preview_source_id_v3,
)


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = frozenset({
    "version", "candidate_id", "repository", "artifact_path",
    "upstream_revision", "artifact_sha256", "member_name", "member_sha256",
    "record_kind", "records",
})
_ROW_FIELDS = frozenset({
    "ordinal", "byte_offset", "byte_length", "raw_sha256", "event_record_id",
    "event_time_utc", "event_code", "channel",
})


class XmlReplayError(ValueError):
    """Manifest, byte replay, or synthetic binding failed closed."""


@dataclass(frozen=True, slots=True)
class PreparedXmlOccurrence:
    source_id: str
    source_payload: bytes
    raw_bytes: bytes
    parsed: ParsedXmlEvent
    ordinal: int
    byte_offset: int


@dataclass(frozen=True, slots=True)
class SyntheticXmlBinding:
    source_id: str
    evidence_id: str
    tenant_id: str
    incident_id: str
    source_payload: bytes
    raw_sha256: str
    raw_message_ref: str


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise XmlReplayError("duplicate_manifest_key")
        value[key] = item
    return value


def _reject_number(_value: str) -> object:
    raise XmlReplayError("invalid_manifest_number")


def _prepare_xml_profile(
    artifact: bytes, manifest_bytes: bytes, *, trusted_manifest_sha256: str,
    expected_candidate_id: str, expected_artifact_path: str,
    expected_artifact_sha256: str,
    boundary_version: str, policy_version: str,
    canonical_source: Callable[[object], bytes],
    preview_source: Callable[[object], str],
) -> tuple[PreparedXmlOccurrence, ...]:
    """Compare a separately supplied complete manifest to exact supplied bytes.

    The expected fields and digest must come from an independent trusted caller.
    This preflight cannot establish that a real owner reviewed or pinned them.
    """
    if (type(artifact) is not bytes or type(manifest_bytes) is not bytes
            or type(trusted_manifest_sha256) is not str
            or not _SHA.fullmatch(trusted_manifest_sha256)
            or hashlib.sha256(manifest_bytes).hexdigest() != trusted_manifest_sha256):
        raise XmlReplayError("manifest_hash_mismatch")
    try:
        data = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_unique,
                          parse_float=_reject_number, parse_constant=_reject_number)
        if type(data) is not dict or canonical_bytes(data) != manifest_bytes:
            raise XmlReplayError("noncanonical_manifest")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, XmlReplayError):
            raise
        raise XmlReplayError("malformed_manifest") from exc
    if (set(data) != _MANIFEST_FIELDS or data["version"] != boundary_version
            or data["repository"] != V2_REPOSITORY
            or data["upstream_revision"] != V2_REVISION
            or data["record_kind"] != "xml_record"
            or data["member_name"] is not None or data["member_sha256"] is not None
            or data["candidate_id"] != expected_candidate_id
            or data["artifact_path"] != expected_artifact_path
            or data["artifact_sha256"] != expected_artifact_sha256):
        raise XmlReplayError("manifest_source_mismatch")
    if (type(expected_artifact_sha256) is not str
            or not _SHA.fullmatch(expected_artifact_sha256)
            or hashlib.sha256(artifact).hexdigest() != expected_artifact_sha256):
        raise XmlReplayError("artifact_hash_mismatch")
    if type(data["records"]) is not list:
        raise XmlReplayError("manifest_records_invalid")
    try:
        observed = preview_direct_xml_lines(artifact)
    except XmlBoundaryPreviewError as exc:
        raise XmlReplayError("unsafe_or_ambiguous_xml_boundaries") from exc
    if len(data["records"]) != len(observed):
        raise XmlReplayError("incomplete_boundary_manifest")
    prepared: list[PreparedXmlOccurrence] = []
    source_ids: set[str] = set()
    for row, actual in zip(data["records"], observed, strict=True):
        if (type(row) is not dict or set(row) != _ROW_FIELDS
                or any(type(row[name]) is not int for name in
                       ("ordinal", "byte_offset", "byte_length", "event_code"))
                or any(type(row[name]) is not str for name in
                       ("raw_sha256", "event_record_id", "event_time_utc", "channel"))
                or any(row[name] != getattr(actual, name) for name in _ROW_FIELDS)):
            raise XmlReplayError("boundary_manifest_mismatch")
        raw = artifact[actual.byte_offset:actual.byte_offset + actual.byte_length]
        payload = {
            "policy_version": policy_version,
            "candidate_id": data["candidate_id"],
            "repository": data["repository"],
            "artifact_path": data["artifact_path"],
            "upstream_revision": data["upstream_revision"],
            "artifact_sha256": data["artifact_sha256"],
            "member_name": None, "member_sha256": None,
            "record_kind": "xml_record", "ordinal": actual.ordinal,
            "byte_offset": actual.byte_offset, "byte_length": actual.byte_length,
            "raw_sha256": actual.raw_sha256,
        }
        try:
            source_payload = canonical_source(payload)
            source_id = preview_source(payload)
            parsed = parse_xml_event(raw)
        except (ValueError, XmlBoundaryPreviewError) as exc:
            raise XmlReplayError("invalid_source_occurrence") from exc
        if source_id in source_ids:
            raise XmlReplayError("source_digest_collision")
        source_ids.add(source_id)
        prepared.append(PreparedXmlOccurrence(
            source_id, source_payload, raw, parsed,
            actual.ordinal, actual.byte_offset))
    return tuple(prepared)


def prepare_synthetic_xml_replay(
    artifact: bytes, manifest_bytes: bytes, *, trusted_manifest_sha256: str,
    expected_candidate_id: str, expected_artifact_path: str,
    expected_artifact_sha256: str,
) -> tuple[PreparedXmlOccurrence, ...]:
    """D-026 v2 synthetic preflight; existing behavior and namespace preserved."""
    return _prepare_xml_profile(
        artifact, manifest_bytes, trusted_manifest_sha256=trusted_manifest_sha256,
        expected_candidate_id=expected_candidate_id,
        expected_artifact_path=expected_artifact_path,
        expected_artifact_sha256=expected_artifact_sha256,
        boundary_version="d021-v2-xml-boundaries-1",
        policy_version=V2_POLICY_VERSION,
        canonical_source=canonical_source_preimage_v2,
        preview_source=preview_source_id_v2,
    )


def prepare_synthetic_pds01_xml_replay(
    artifact: bytes, manifest_bytes: bytes, *, trusted_manifest_sha256: str,
    expected_candidate_id: str, expected_artifact_path: str,
    expected_artifact_sha256: str,
) -> tuple[PreparedXmlOccurrence, ...]:
    """PDS-01 v3 synthetic preflight; does not issue a real ID or A grant."""
    return _prepare_xml_profile(
        artifact, manifest_bytes, trusted_manifest_sha256=trusted_manifest_sha256,
        expected_candidate_id=expected_candidate_id,
        expected_artifact_path=expected_artifact_path,
        expected_artifact_sha256=expected_artifact_sha256,
        boundary_version="d021-v3-xml-boundaries-1",
        policy_version=V3_POLICY_VERSION,
        canonical_source=canonical_source_preimage_v3,
        preview_source=preview_source_id_v3,
    )


class SyntheticXmlReplayIndex:
    """Atomic fixture-only binding index; durable real allocation is absent."""

    def __init__(self, *, policy_version: str = V2_POLICY_VERSION) -> None:
        if policy_version == V2_POLICY_VERSION:
            self._canonical_source = canonical_source_preimage_v2
            self._preview_source = preview_source_id_v2
            self._preview_scoped = preview_scoped_id_v2
        elif policy_version == V3_POLICY_VERSION:
            self._canonical_source = canonical_source_preimage_v3
            self._preview_source = preview_source_id_v3
            self._preview_scoped = preview_scoped_id_v3
        else:
            raise XmlReplayError("unknown_synthetic_identity_policy")
        self.policy_version = policy_version
        self._by_source: dict[str, SyntheticXmlBinding] = {}
        self._by_evidence: dict[str, SyntheticXmlBinding] = {}
        self._by_locator: dict[tuple[str, str, int, int], str] = {}

    def snapshot(self) -> tuple[SyntheticXmlBinding, ...]:
        return tuple(self._by_source.values())

    def snapshot_bytes(self) -> bytes:
        """Portable fixture checkpoint; caller must independently pin its hash."""
        rows = [
            {"source_id": item.source_id, "evidence_id": item.evidence_id,
             "tenant_id": item.tenant_id, "incident_id": item.incident_id,
             "source_payload": item.source_payload.decode("utf-8"),
             "raw_sha256": item.raw_sha256,
             "raw_message_ref": item.raw_message_ref}
            for item in self._by_source.values()
        ]
        return canonical_bytes({"version": "synthetic-xml-index-1",
                                "policy_version": self.policy_version,
                                "bindings": rows})

    @classmethod
    def from_snapshot_bytes(cls, content: bytes, *, trusted_sha256: str,
                            policy_version: str) -> SyntheticXmlReplayIndex:
        """Fail closed on corrupted or cross-policy fixture restart state."""
        if (type(content) is not bytes or type(trusted_sha256) is not str
                or hashlib.sha256(content).hexdigest() != trusted_sha256):
            raise XmlReplayError("snapshot_hash_mismatch")
        try:
            data = json.loads(content.decode("utf-8"), object_pairs_hook=_unique,
                              parse_float=_reject_number, parse_constant=_reject_number)
            if (type(data) is not dict or set(data) != {
                    "version", "policy_version", "bindings"}
                    or data["version"] != "synthetic-xml-index-1"
                    or data["policy_version"] != policy_version
                    or type(data["bindings"]) is not list
                    or canonical_bytes(data) != content):
                raise XmlReplayError("invalid_snapshot")
            index = cls(policy_version=policy_version)
            for row in data["bindings"]:
                if type(row) is not dict or set(row) != {
                        "source_id", "evidence_id", "tenant_id", "incident_id",
                        "source_payload", "raw_sha256", "raw_message_ref"}:
                    raise XmlReplayError("invalid_snapshot_binding")
                payload_bytes = row["source_payload"].encode("utf-8")
                payload = json.loads(payload_bytes, object_pairs_hook=_unique)
                source_id = index._preview_source(payload)
                evidence_id = index._preview_scoped({
                    "policy_version": policy_version,
                    "source_event_key": source_id,
                    "tenant_id": row["tenant_id"],
                    "incident_id": row["incident_id"],
                })
                if (index._canonical_source(payload) != payload_bytes
                        or row["source_id"] != source_id
                        or row["evidence_id"] != evidence_id
                        or not _SHA.fullmatch(row["raw_sha256"])
                        or row["raw_sha256"] != payload["raw_sha256"]
                        or row["raw_message_ref"] != "real-occurrence:" + source_id):
                    raise XmlReplayError("invalid_snapshot_binding")
                locator = (payload["candidate_id"], payload["artifact_sha256"],
                           payload["ordinal"], payload["byte_offset"])
                if (source_id in index._by_source or evidence_id in index._by_evidence
                        or locator in index._by_locator):
                    raise XmlReplayError("duplicate_snapshot_binding")
                binding = SyntheticXmlBinding(
                    source_id, evidence_id, row["tenant_id"],
                    row["incident_id"], payload_bytes,
                    row["raw_sha256"], row["raw_message_ref"])
                index._by_source[source_id] = binding
                index._by_evidence[evidence_id] = binding
                index._by_locator[locator] = source_id
            return index
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
                AttributeError, ValueError) as exc:
            if isinstance(exc, XmlReplayError):
                raise
            raise XmlReplayError("invalid_snapshot") from exc

    def bind_batch(
        self, occurrences: tuple[PreparedXmlOccurrence, ...],
        scopes: Mapping[int, tuple[str, str]],
    ) -> tuple[SyntheticXmlBinding, ...]:
        """Validate the entire fixture batch before changing any index state."""
        if set(scopes) != {item.ordinal for item in occurrences}:
            raise XmlReplayError("missing_or_extra_scope")
        by_source = self._by_source.copy()
        by_evidence = self._by_evidence.copy()
        by_locator = self._by_locator.copy()
        result: list[SyntheticXmlBinding] = []
        seen_batch: set[str] = set()
        for item in occurrences:
            if item.source_id in seen_batch:
                raise XmlReplayError("duplicate_batch_occurrence")
            seen_batch.add(item.source_id)
            tenant_id, incident_id = scopes[item.ordinal]
            try:
                payload = json.loads(item.source_payload)
                if (type(tenant_id) is not str or type(incident_id) is not str
                        or not tenant_id or not incident_id):
                    raise ValueError("invalid scope")
                evidence_id = self._preview_scoped({
                    "policy_version": self.policy_version,
                    "source_event_key": item.source_id,
                    "tenant_id": tenant_id, "incident_id": incident_id,
                })
                if (self._canonical_source(payload) != item.source_payload
                        or self._preview_source(payload) != item.source_id
                        or payload["ordinal"] != item.ordinal
                        or payload["byte_offset"] != item.byte_offset
                        or payload["byte_length"] != len(item.raw_bytes)
                        or payload["raw_sha256"] != hashlib.sha256(item.raw_bytes).hexdigest()
                        or parse_xml_event(item.raw_bytes) != item.parsed):
                    raise ValueError("source key changed")
            except (ValueError, TypeError, KeyError, XmlBoundaryPreviewError) as exc:
                raise XmlReplayError("invalid_synthetic_binding") from exc
            locator = (payload["candidate_id"], payload["artifact_sha256"],
                       item.ordinal, item.byte_offset)
            binding = SyntheticXmlBinding(
                item.source_id, evidence_id, tenant_id, incident_id,
                item.source_payload, hashlib.sha256(item.raw_bytes).hexdigest(),
                "real-occurrence:" + item.source_id)
            previous = by_source.get(item.source_id)
            if previous is not None and previous != binding:
                raise XmlReplayError("source_already_bound_or_collision")
            if by_evidence.get(evidence_id, binding) != binding:
                raise XmlReplayError("evidence_digest_collision")
            if by_locator.get(locator, item.source_id) != item.source_id:
                raise XmlReplayError("duplicate_locator")
            by_source[item.source_id] = binding
            by_evidence[evidence_id] = binding
            by_locator[locator] = item.source_id
            result.append(binding)
        self._by_source, self._by_evidence, self._by_locator = (
            by_source, by_evidence, by_locator)
        return tuple(result)

    def resolve(self, evidence_id: str, *, tenant_id: str,
                incident_id: str) -> SyntheticXmlBinding:
        binding = self._by_evidence.get(evidence_id)
        if (binding is None or binding.tenant_id != tenant_id
                or binding.incident_id != incident_id):
            raise XmlReplayError("unknown_or_cross_scope_evidence")
        return binding
