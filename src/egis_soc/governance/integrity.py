"""Canonical W1-07 manifest bytes and integrity checks.

Hashes detect changed bytes; they do not provide write protection, identity
attestation, access control, or approval of a real dataset freeze.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal


SCHEMA_VERSION = "w1-07-manifest-2"


def _canonical_value(value: Any) -> Any:
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        return unicodedata.normalize("NFC", value)
    if type(value) in (tuple, list):
        return [_canonical_value(item) for item in value]
    if type(value) is dict:
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("manifest keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            if normalized in result:
                raise ValueError("manifest keys collide after NFC normalization")
            result[normalized] = _canonical_value(item)
        return result
    raise ValueError(f"unsupported manifest value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSON; record arrays must be sorted by their caller."""

    normalized = _canonical_value(value)
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class FreezeApproval:
    owner_ref: str
    independent_reviewer_ref: str
    access_audit_ref: str
    method_lock_ref: str

    def __post_init__(self) -> None:
        for value in (
            self.owner_ref, self.independent_reviewer_ref, self.access_audit_ref,
            self.method_lock_ref,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("freeze requires four nonblank approval/audit references")


@dataclass(frozen=True, slots=True)
class Manifest:
    """Immutable in-process bytes plus digest, with explicit proposed/frozen state."""

    content: bytes
    sha256: str

    @classmethod
    def proposed(
        cls, policy_version: str, entries: list[dict[str, Any]],
        *, metadata: dict[str, Any] | None = None,
    ) -> Manifest:
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("policy version is required")
        if any(not isinstance(item, dict) or not isinstance(item.get("component_id"), str)
               or not item["component_id"].strip() for item in entries):
            raise ValueError("manifest entries need stable component IDs")
        sorted_entries = sorted(entries, key=lambda item: item["component_id"])
        if len({item["component_id"] for item in sorted_entries}) != len(sorted_entries):
            raise ValueError("manifest component IDs must be unique")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": policy_version,
            "lifecycle": "proposed",
            "entries": sorted_entries,
            "metadata": {} if metadata is None else metadata,
            "approval": None,
        }
        content = canonical_bytes(payload)
        manifest = cls(content, hashlib.sha256(content).hexdigest())
        manifest.verify()
        return manifest

    @property
    def manifest_id(self) -> str:
        return f"sha256:{self.sha256}"

    @property
    def data(self) -> dict[str, Any]:
        """Return a detached view; callers cannot mutate the stored bytes."""

        self.verify()
        return json.loads(self.content)

    @property
    def lifecycle(self) -> Literal["proposed", "frozen"]:
        return self.data["lifecycle"]

    def verify(self) -> None:
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("manifest SHA-256 mismatch")
        try:
            decoded = json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest JSON is invalid") from exc
        if canonical_bytes(decoded) != self.content:
            raise ValueError("manifest is not canonical JSON")
        if not isinstance(decoded, dict) or set(decoded) != {
            "schema_version", "policy_version", "lifecycle", "entries", "metadata", "approval"
        }:
            raise ValueError("manifest payload fields are invalid")
        if decoded.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported manifest schema version")
        if decoded.get("lifecycle") not in ("proposed", "frozen"):
            raise ValueError("invalid manifest lifecycle")
        if not isinstance(decoded.get("entries"), list):
            raise ValueError("manifest entries are missing")
        if not isinstance(decoded.get("metadata"), dict):
            raise ValueError("manifest metadata is missing")
        entries = decoded["entries"]
        ids = [item.get("component_id") for item in entries if isinstance(item, dict)]
        if len(ids) != len(entries) or any(not isinstance(item, str) or not item for item in ids):
            raise ValueError("manifest entry IDs are invalid")
        if ids != sorted(set(ids)):
            raise ValueError("manifest entries must be sorted and unique")
        if any(item.get("partition") not in {
            "train", "validation", "heldout_a", "heldout_b", "reserved", "quarantine"
        } for item in entries):
            raise ValueError("manifest partition is invalid")
        if decoded["lifecycle"] == "frozen" and not isinstance(decoded["approval"], dict):
            raise ValueError("frozen manifest requires approval references")

    def serialize(self) -> bytes:
        self.verify()
        return canonical_bytes({"content": self.data, "sha256": self.sha256})

    @classmethod
    def deserialize(cls, serialized: bytes) -> Manifest:
        try:
            envelope = json.loads(serialized)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest envelope is invalid") from exc
        if (not isinstance(envelope, dict) or canonical_bytes(envelope) != serialized
                or set(envelope) != {"content", "sha256"}):
            raise ValueError("manifest envelope is not canonical")
        if not isinstance(envelope["sha256"], str):
            raise ValueError("manifest digest is invalid")
        manifest = cls(canonical_bytes(envelope["content"]), envelope["sha256"])
        manifest.verify()
        return manifest

    def freeze(self, approval: FreezeApproval, *, gates_passed: bool) -> Manifest:
        """Reject direct lifecycle changes; use the W1-07 split gate."""

        raise ValueError("direct manifest freeze is disabled; use freeze_split_manifest")

    def _freeze_after_verified_gates(self, approval: FreezeApproval) -> Manifest:
        """Internal record transition after split/audit recomputation.

        Python privacy is advisory; external custody still authenticates the
        approval references and protects the persisted bytes.
        """

        if self.lifecycle != "proposed":
            raise ValueError("freeze requires a proposed manifest")
        payload = self.data
        payload["lifecycle"] = "frozen"
        payload["approval"] = {
            "owner_ref": approval.owner_ref,
            "independent_reviewer_ref": approval.independent_reviewer_ref,
            "access_audit_ref": approval.access_audit_ref,
            "method_lock_ref": approval.method_lock_ref,
        }
        content = canonical_bytes(payload)
        frozen = Manifest(content, hashlib.sha256(content).hexdigest())
        frozen.verify()
        return frozen
