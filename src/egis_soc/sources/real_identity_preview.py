"""Offline D-021 identity preimages. No source access, allocation, or persistence.

These functions validate supplied metadata and compute deterministic preview IDs.
They do not verify artifact/member/record bytes, source authorization, reviewed
incident scope, uniqueness, custody, or an audit head. Never use them to accept
real evidence or expose a real source to Environment A.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from typing import Any

from egis_soc.governance.integrity import canonical_bytes


POLICY_VERSION = "real-evidence-identity-v1"
_SOURCE_FIELDS = frozenset({
    "policy_version", "candidate_id", "repository", "artifact_path",
    "upstream_revision", "artifact_sha256", "member_name", "member_sha256",
    "record_kind", "ordinal", "byte_offset", "byte_length", "raw_sha256",
})
_SCOPED_FIELDS = frozenset({
    "policy_version", "source_event_key", "tenant_id", "incident_id",
})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SOURCE_ID = re.compile(r"REAL-SRC1-[A-Z2-7]{52}\Z")
_INTEGER_FIELDS = frozenset({"ordinal", "byte_offset", "byte_length"})


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("identity text must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if (not normalized or normalized != normalized.strip()
            or any(0xD800 <= ord(character) <= 0xDFFF
                   for character in normalized)):
        raise ValueError("identity text is empty, padded or contains a surrogate")
    return normalized


def _path(value: object) -> str:
    path = _text(value)
    if (path.startswith("/") or "\\" in path or "%" in path
            or any(character in path for character in ":?#")
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or any(component in ("", ".", "..") for component in path.split("/"))):
        raise ValueError("unsafe OTRF repository/member path")
    return path


def _digest(value: object) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError("identity digest must be lowercase full SHA-256")
    return value


def _strict_payload(payload: object, expected: frozenset[str],
                    version: str = POLICY_VERSION) -> dict[str, Any]:
    if type(payload) is not dict:
        raise ValueError("identity fields differ from the approved flat schema")
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if type(key) is not str:
            raise ValueError("identity keys must be strings")
        name = unicodedata.normalize("NFC", key)
        if name in normalized:
            raise ValueError("identity keys collide after NFC normalization")
        if type(value) is str:
            normalized[name] = _text(value)
        elif type(value) is int:
            if name not in _INTEGER_FIELDS:
                raise ValueError("integer in an identity text field")
            normalized[name] = value
        elif value is None and name in {"member_name", "member_sha256"}:
            normalized[name] = None
        else:
            raise ValueError("identity values must be text, exact integers or member nulls")
    if set(normalized) != expected:
        raise ValueError("identity fields differ from the approved flat schema")
    if normalized["policy_version"] != version:
        raise ValueError("unknown identity policy version")
    return normalized


def canonical_source_preimage(payload: object) -> bytes:
    """Validate the exact D-021 source fields and return canonical UTF-8 bytes."""

    data = _strict_payload(payload, _SOURCE_FIELDS)
    if data["repository"] != "github.com/otrf/security-datasets":
        raise ValueError("unsupported source repository profile")
    if not _REVISION.fullmatch(data["upstream_revision"]):
        raise ValueError("upstream revision must be a pinned lowercase commit")
    data["artifact_path"] = _path(data["artifact_path"])
    if (data["member_name"] is None) != (data["member_sha256"] is None):
        raise ValueError("member name and digest must both be present or null")
    if data["member_name"] is not None:
        data["member_name"] = _path(data["member_name"])
        _digest(data["member_sha256"])
    if data["record_kind"] not in {"jsonl_line", "xml_record", "pcap_packet"}:
        raise ValueError("unsupported record kind")
    for field, minimum in (("ordinal", 1), ("byte_offset", 0), ("byte_length", 1)):
        if type(data[field]) is not int or data[field] < minimum:
            raise ValueError(f"invalid {field}")
    _digest(data["artifact_sha256"])
    _digest(data["raw_sha256"])
    return canonical_bytes(data)


def canonical_scoped_preimage(payload: object) -> bytes:
    """Validate an already reviewed scope's supplied fields; do not approve it."""

    data = _strict_payload(payload, _SCOPED_FIELDS)
    source_key = data["source_event_key"]
    if not _SOURCE_ID.fullmatch(source_key):
        raise ValueError("scoped identity requires a full source key")
    encoded = source_key.removeprefix("REAL-SRC1-")
    decoded = base64.b32decode(encoded + "====")
    if len(decoded) != 32 or base64.b32encode(decoded).decode("ascii").rstrip("=") != encoded:
        raise ValueError("source key has noncanonical base32 padding bits")
    return canonical_bytes(data)


def parse_identity_json(raw: bytes, *, source: bool) -> dict[str, Any]:
    """Reject duplicate JSON keys, including keys that collide after NFC."""

    if type(raw) is not bytes:
        raise ValueError("identity JSON must be UTF-8 bytes")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            name = unicodedata.normalize("NFC", key)
            if name in result:
                raise ValueError("duplicate identity JSON key")
            result[name] = value
        return result

    def reject_number(value: str) -> Any:
        raise ValueError(f"non-integer identity number: {value}")

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                             parse_float=reject_number, parse_constant=reject_number)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid UTF-8 identity JSON") from exc
    canonical = (canonical_source_preimage(payload) if source
                 else canonical_scoped_preimage(payload))
    return json.loads(canonical)


def preview_source_id(payload: object) -> str:
    """Compute an offline vector only; this is not durable real allocation."""

    digest = hashlib.sha256(canonical_source_preimage(payload)).digest()
    return "REAL-SRC1-" + base64.b32encode(digest).decode("ascii").rstrip("=")


def preview_scoped_id(payload: object) -> str:
    """Compute an offline vector only; this is not scoped source authorization."""

    digest = hashlib.sha256(canonical_scoped_preimage(payload)).digest()
    return "REAL-EV1-" + base64.b32encode(digest).decode("ascii").rstrip("=")


V2_POLICY_VERSION = "real-evidence-identity-v2"
V2_REPOSITORY = "github.com/splunk/attack_data"
V2_REVISION = "eac2f8f675ec31a6618003399dcc53641524e673"
_V2_SOURCE_ID = re.compile(r"REAL-SRC2-[A-Z2-7]{52}\Z")
_V2_CANDIDATE = re.compile(r"A(?:0[1-9]|1[0-8])\Z")
_D026_PATHS = {
    "A01": "datasets/malware/conti/conti_leak/windows-sysmon_7z.log",
    "A02": "datasets/malware/conti/conti_leak/windows-sysmon.log",
    "A03": "datasets/malware/conti/conti_leak/windows-security.log",
    "A04": "datasets/malware/ryuk/windows-sysmon.log",
    "A05": "datasets/malware/snakemalware/snake-service-windows-system.log",
    "A06": "datasets/malware/snakemalware/snake_crmlog-windows-sysmon.log",
    "A07": "datasets/malware/snakemalware/comadmin_windows-sysmon.log",
    "A08": "datasets/malware/snakemalware/snake_malware_regblob-windows-sysmon.log",
    "A09": "datasets/malware/trickbot/spear_phish/windows-sysmon.log",
    "A10": "datasets/malware/icedid/phish_icedid/windows-sysmon.log",
    "A11": "datasets/malware/remcos/remcos/windows-sysmon.log",
    "A12": "datasets/malware/hermetic_wiper/sysmon.log",
    "A13": "datasets/malware/doublezero_wiper/sysmon.log",
    "A14": "datasets/malware/prestige_ransomware/sysmon.log",
    "A15": "datasets/malware/chaos_ransomware/sysmon.log",
    "A16": "datasets/malware/industroyer2/sysmon.log",
    "A17": "datasets/malware/azorult/sysmon.log",
    "A18": "datasets/malware/swift_slicer/sysmon.log",
}


def canonical_source_preimage_v2(payload: object) -> bytes:
    """Validate the approved direct-XML preimage; compute bytes only."""
    data = _strict_payload(payload, _SOURCE_FIELDS, V2_POLICY_VERSION)
    if (not _V2_CANDIDATE.fullmatch(data["candidate_id"])
            or data["repository"] != V2_REPOSITORY
            or data["upstream_revision"] != V2_REVISION
            or data["member_name"] is not None
            or data["member_sha256"] is not None
            or data["record_kind"] != "xml_record"):
        raise ValueError("unsupported D-026 direct-XML source profile")
    data["artifact_path"] = _path(data["artifact_path"])
    if data["artifact_path"] != _D026_PATHS[data["candidate_id"]]:
        raise ValueError("artifact path is outside the D-026 allowlist")
    for field, minimum in (("ordinal", 1), ("byte_offset", 0), ("byte_length", 1)):
        if type(data[field]) is not int or data[field] < minimum:
            raise ValueError(f"invalid {field}")
    _digest(data["artifact_sha256"])
    _digest(data["raw_sha256"])
    return canonical_bytes(data)


def canonical_scoped_preimage_v2(payload: object) -> bytes:
    data = _strict_payload(payload, _SCOPED_FIELDS, V2_POLICY_VERSION)
    source_key = data["source_event_key"]
    if not _V2_SOURCE_ID.fullmatch(source_key):
        raise ValueError("v2 scope requires a full v2 source key")
    encoded = source_key.removeprefix("REAL-SRC2-")
    decoded = base64.b32decode(encoded + "====")
    if len(decoded) != 32 or base64.b32encode(decoded).decode("ascii").rstrip("=") != encoded:
        raise ValueError("source key has noncanonical base32 padding bits")
    return canonical_bytes(data)


def preview_source_id_v2(payload: object) -> str:
    """Synthetic conformance preview, never a persistent REAL allocation."""
    digest = hashlib.sha256(canonical_source_preimage_v2(payload)).digest()
    return "REAL-SRC2-" + base64.b32encode(digest).decode("ascii").rstrip("=")


def preview_scoped_id_v2(payload: object) -> str:
    """Synthetic conformance preview, never a scoped authorization."""
    digest = hashlib.sha256(canonical_scoped_preimage_v2(payload)).digest()
    return "REAL-EV2-" + base64.b32encode(digest).decode("ascii").rstrip("=")


V3_POLICY_VERSION = "real-evidence-identity-v3"
_V3_SOURCE_ID = re.compile(r"REAL-SRC3-[A-Z2-7]{52}\Z")
_PDS01_PATHS = {
    "S01": {"datasets/malware/agent_tesla/agent_tesla_ftp/sysmon.log"},
    "S02": {"datasets/malware/agent_tesla/agent_tesla_smtp/sysmon.log"},
    "S03": {"datasets/malware/brute_ratel/iso_version_dll_campaign/sysmon.log"},
    "S04": {"datasets/malware/clop/clop_a/windows-xml.log",
            "datasets/malware/clop/clop_a/windows-sysmon.log"},
    "S05": {"datasets/malware/dcrat/dcrat_explorer_url/sysmon.log"},
    "S06": {"datasets/malware/fin7/fin7_js_2/wmi_module_loaded_sysmon.log",
            "datasets/malware/fin7/fin7_js_2/ldap_module_loaded_sysmon.log",
            "datasets/malware/fin7/fin7_js_2/sysmon.log"},
    "S07": {"datasets/malware/olympic_destroyer/sysmon.log"},
    "S08": {"datasets/malware/redline/modify_registry/sysmon.log"},
    "S09": {"datasets/malware/vilsel/windows-xml.log",
            "datasets/malware/vilsel/sysmon.log"},
    "S10": {"datasets/malware/winpeas/sysmon.log"},
    "S11": {"datasets/malware/winter-vivern/scheduledtask/sysmon.log"},
    "S12": {"datasets/malware/revil/msmpeng_side/windows-sysmon.log"},
}


def canonical_source_preimage_v3(payload: object) -> bytes:
    """PDS-01 direct-XML preimage preview; no artifact reader or allocation."""
    data = _strict_payload(payload, _SOURCE_FIELDS, V3_POLICY_VERSION)
    if (data["repository"] != V2_REPOSITORY
            or data["upstream_revision"] != V2_REVISION
            or data["member_name"] is not None
            or data["member_sha256"] is not None
            or data["record_kind"] != "xml_record"):
        raise ValueError("unsupported PDS-01 source profile")
    path = _path(data["artifact_path"])
    if path not in _PDS01_PATHS.get(data["candidate_id"], ()):
        raise ValueError("artifact path is outside the PDS-01 allowlist")
    for field, minimum in (("ordinal", 1), ("byte_offset", 0), ("byte_length", 1)):
        if type(data[field]) is not int or data[field] < minimum:
            raise ValueError(f"invalid {field}")
    _digest(data["artifact_sha256"])
    _digest(data["raw_sha256"])
    return canonical_bytes(data)


def canonical_scoped_preimage_v3(payload: object) -> bytes:
    data = _strict_payload(payload, _SCOPED_FIELDS, V3_POLICY_VERSION)
    source_key = data["source_event_key"]
    if not _V3_SOURCE_ID.fullmatch(source_key):
        raise ValueError("v3 scope requires a full v3 source key")
    encoded = source_key.removeprefix("REAL-SRC3-")
    decoded = base64.b32decode(encoded + "====")
    if len(decoded) != 32 or base64.b32encode(decoded).decode("ascii").rstrip("=") != encoded:
        raise ValueError("source key has noncanonical base32 padding bits")
    return canonical_bytes(data)


def preview_source_id_v3(payload: object) -> str:
    digest = hashlib.sha256(canonical_source_preimage_v3(payload)).digest()
    return "REAL-SRC3-" + base64.b32encode(digest).decode("ascii").rstrip("=")


def preview_scoped_id_v3(payload: object) -> str:
    digest = hashlib.sha256(canonical_scoped_preimage_v3(payload)).digest()
    return "REAL-EV3-" + base64.b32encode(digest).decode("ascii").rstrip("=")
