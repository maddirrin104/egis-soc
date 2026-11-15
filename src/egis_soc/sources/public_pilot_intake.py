"""D-026 acquisition-only intake for the exact approved public pilot objects.

This module does not grant Environment A use, parse incident semantics, allocate
evidence IDs, or make pilot acceptance decisions. Payload bytes remain private.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import ntpath
import os
import re
import subprocess
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterator


PROPOSAL_SHA256 = "ca6eb301ab48fe70107e6a0b6f6532efeedbb8cc4d19face7b94784a582720f0"
REVISION = "eac2f8f675ec31a6618003399dcc53641524e673"
_ROW = re.compile(
    r"^\| (A\d{2}) \| `(datasets/malware/[^`]+)` \| `([0-9a-f]{64})` \| ([0-9,]+) \|$"
)
_EVENT_NAME = re.compile(r"^(\d{6})-([0-9a-f]{64})\.json$")
_HEAD_NAME = re.compile(r"^(\d{6})-([0-9a-f]{64})\.head$")
_PIN_NAME = re.compile(r"^(\d{6})-([0-9a-f]{64})\.pin\.json$")
_EXECUTABLE_SIGNALS = {
    "ryuk": "scenario_named_binary", "conti": "scenario_named_binary",
    "7z": "archive_tool", "vssadmin": "shadow_copy_tool",
    "bcdedit": "boot_config_tool", "wbadmin": "backup_tool",
    "regsvr32": "living_off_land_binary", "mshta": "living_off_land_binary",
    "rundll32": "living_off_land_binary", "winword": "office_process",
    "excel": "office_process", "outlook": "office_process",
}


class PublicPilotIntakeError(RuntimeError):
    """The public intake or its metadata history cannot be trusted."""


@dataclass(frozen=True)
class Artifact:
    key: str
    path: str
    sha256: str
    size: int


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_no_links(path: Path) -> None:
    cursor = path.absolute()
    while True:
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise PublicPilotIntakeError("reparse_or_symlink_path")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent


def load_approved_manifest(proposal: Path, expected_sha256: str = PROPOSAL_SHA256,
                           expected_count: int = 18) -> dict[str, Artifact]:
    _assert_no_links(proposal)
    content = proposal.read_bytes()
    if _sha(content) != expected_sha256:
        raise PublicPilotIntakeError("approved_proposal_sha256_mismatch")
    entries: dict[str, Artifact] = {}
    paths: set[str] = set()
    for line in content.decode("utf-8").splitlines():
        match = _ROW.fullmatch(line)
        if not match:
            continue
        key, path, digest, size_text = match.groups()
        parts = path.split("/")
        if (key in entries or path in paths or any(part in {"", ".", ".."} for part in parts)
                or "\\" in path or ":" in path):
            raise PublicPilotIntakeError("invalid_or_duplicate_manifest_row")
        entries[key] = Artifact(key, path, digest, int(size_text.replace(",", "")))
        paths.add(path)
    wanted = {f"A{index:02d}" for index in range(1, expected_count + 1)}
    if set(entries) != wanted or any(item.size <= 0 for item in entries.values()):
        raise PublicPilotIntakeError("incomplete_approved_allowlist")
    return entries


def verify_windows_custody(workspace: Path) -> None:
    script = workspace / "scripts" / "w2_public_pilot_custody.ps1"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script),
         "-Phase", "Verify"], capture_output=True, text=True, check=False,
    )
    if result.returncode or "PUBLIC_PILOT_CUSTODY=PASS" not in result.stdout:
        raise PublicPilotIntakeError("public_pilot_custody_not_verified")


def _create_new(path: Path, payload: bytes) -> None:
    _assert_no_links(path.parent)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


class PublicPilotIntake:
    """No-overwrite acquisition with a replayed metadata event/head pair."""

    def __init__(self, workspace: Path, *, proposal: Path | None = None,
                 expected_proposal_sha256: str = PROPOSAL_SHA256,
                 expected_count: int = 18,
                 custody_check: Callable[[Path], None] = verify_windows_custody):
        self.workspace = workspace.absolute()
        self._expected_proposal_sha256 = expected_proposal_sha256
        self.proposal = proposal or (self.workspace / "docs" / "datasets" /
            "w2-public-pilot-fast-track-proposal-2026-10-25.md")
        self.manifest = load_approved_manifest(
            self.proposal, expected_proposal_sha256, expected_count)
        self.raw = self.workspace / "data" / "public-pilot-raw"
        self.audit = self.workspace / "data" / "public-pilot-audit"
        self.heads = self.workspace / "data" / "public-pilot-heads"
        self.pins = self.workspace / "data" / "public-pilot-pins"
        self.custody_check = custody_check
        self.audit_version = "public-pilot-intake-1"
        self.pin_version = "public-pilot-pin-1"

    def _preflight(self) -> None:
        if _sha(self.proposal.read_bytes()) != self._proposal_digest:
            raise PublicPilotIntakeError("approved_proposal_changed_after_load")
        for root in (self.raw, self.audit, self.heads, self.pins):
            _assert_no_links(root)
            if not root.is_dir():
                raise PublicPilotIntakeError("public_pilot_root_missing")
        self.custody_check(self.workspace)

    @property
    def _proposal_digest(self) -> str:
        # The approved document is rechecked on every operation.
        return self._expected_proposal_sha256

    @staticmethod
    def _require_external_head(sequence: int, actual: str | None,
                               expected: str | None) -> None:
        if sequence == 0:
            if expected is not None:
                raise PublicPilotIntakeError("nonempty_head_for_empty_store")
        elif expected != actual:
            raise PublicPilotIntakeError("missing_or_stale_external_head")

    def _require_local_pin(self, sequence: int, head: str | None) -> None:
        files = list(self.pins.iterdir())
        if sequence == 0:
            if files:
                raise PublicPilotIntakeError("pin_without_audit_event")
            return
        expected_name = f"{sequence:06d}-{head}.pin.json"
        if not any(path.name == expected_name for path in files):
            raise PublicPilotIntakeError("current_head_not_separately_pinned")
        for path in files:
            match = _PIN_NAME.fullmatch(path.name)
            if match is None or path.is_symlink() or not path.is_file():
                raise PublicPilotIntakeError("unsafe_or_unexpected_pin_file")
            try:
                raw = path.read_bytes()
                pin = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicPilotIntakeError("pin_json_invalid") from exc
            if (type(pin) is not dict or _canonical(pin) != raw
                    or pin.get("version") != self.pin_version
                    or pin.get("sequence") != int(match[1])
                    or pin.get("head_sha256") != match[2]
                    or pin.get("proposal_sha256") != self._proposal_digest
                    or pin.get("capture_time_pin") is not False
                    or not isinstance(pin.get("pinned_at_utc"), str)):
                raise PublicPilotIntakeError("pin_content_mismatch")

    def pin_current_head(self, *, observed_head_sha256: str) -> dict[str, object]:
        """Prospectively copy a previously observed head into a separate root."""
        self._preflight()
        sequence, head, _ = self._replay(allow_pending=True)
        if sequence == 0 or head != observed_head_sha256:
            raise PublicPilotIntakeError("observed_head_does_not_match_chain")
        name = f"{sequence:06d}-{head}.pin.json"
        path = self.pins / name
        if path.exists() or path.is_symlink():
            self._require_local_pin(sequence, head)
            return {"sequence": sequence, "head_sha256": head,
                    "pin_sha256": _file_sha(path), "already_pinned": True}
        pin = {"version": self.pin_version, "sequence": sequence,
               "head_sha256": head, "proposal_sha256": self._proposal_digest,
               "pinned_at_utc": datetime.now(timezone.utc).isoformat(),
               "capture_time_pin": False}
        _create_new(path, _canonical(pin))
        self.custody_check(self.workspace)
        return {"sequence": sequence, "head_sha256": head,
                "pin_sha256": _file_sha(path), "already_pinned": False}

    def _replay(self, *, allow_lock: bool = False,
                allow_pending: bool = False) -> tuple[int, str | None, dict[str, str]]:
        audit_files = sorted(self.audit.iterdir(), key=lambda p: p.name)
        head_files = sorted(self.heads.iterdir(), key=lambda p: p.name)
        if allow_lock:
            audit_files = [path for path in audit_files if path.name != "active.lock"]
        if any(not _EVENT_NAME.fullmatch(path.name) or not path.is_file()
               or path.is_symlink() for path in audit_files):
            raise PublicPilotIntakeError("audit_orphan_or_unsafe_file")
        if any(not _HEAD_NAME.fullmatch(path.name) or not path.is_file()
               or path.is_symlink() for path in head_files):
            raise PublicPilotIntakeError("head_orphan_or_unsafe_file")
        if len(audit_files) != len(head_files):
            raise PublicPilotIntakeError("audit_head_count_mismatch")
        previous: str | None = None
        states: dict[str, str] = {}
        event_fields = {"action", "actor", "artifact_key", "at_utc", "details",
                        "previous_sha256", "proposal_sha256", "sequence", "version"}
        for sequence, (event_path, head_path) in enumerate(zip(audit_files, head_files), 1):
            event_match = _EVENT_NAME.fullmatch(event_path.name)
            head_match = _HEAD_NAME.fullmatch(head_path.name)
            assert event_match is not None and head_match is not None
            if int(event_match[1]) != sequence or int(head_match[1]) != sequence:
                raise PublicPilotIntakeError("audit_sequence_mismatch")
            content = event_path.read_bytes()
            digest = _sha(content)
            try:
                event = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicPilotIntakeError("audit_json_invalid") from exc
            if type(event) is not dict:
                raise PublicPilotIntakeError("audit_fields_or_artifact_invalid")
            if (_canonical(event) != content or digest != event_match[2]
                    or digest != head_match[2]
                    or head_path.read_bytes() != (digest + "\n").encode("ascii")
                    or event.get("sequence") != sequence
                    or event.get("previous_sha256") != previous
                    or event.get("proposal_sha256") != self._proposal_digest):
                raise PublicPilotIntakeError("audit_chain_or_head_mismatch")
            key, action = event.get("artifact_key"), event.get("action")
            if (set(event) != event_fields or key not in self.manifest
                    or event.get("version") != self.audit_version
                    or not isinstance(event.get("actor"), str)
                    or not event["actor"].strip()
                    or not isinstance(event.get("details"), dict)):
                raise PublicPilotIntakeError("audit_fields_or_artifact_invalid")
            try:
                action_time = datetime.fromisoformat(event["at_utc"])
            except (TypeError, ValueError) as exc:
                raise PublicPilotIntakeError("audit_time_invalid") from exc
            offset = action_time.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise PublicPilotIntakeError("audit_time_invalid")
            spec = self.manifest[key]
            details = event["details"]
            if action == "acquire_started":
                if details != {"expected_sha256": spec.sha256,
                               "expected_size": spec.size,
                               "repository_path": spec.path, "revision": REVISION}:
                    raise PublicPilotIntakeError("audit_source_binding_mismatch")
                if key in states:
                    raise PublicPilotIntakeError("duplicate_acquisition_attempt")
                states[key] = "pending"
            elif action in {"acquired", "acquire_failed"}:
                if states.get(key) != "pending":
                    raise PublicPilotIntakeError("invalid_acquisition_transition")
                if action == "acquired" and details != {"sha256": spec.sha256,
                                                        "size": spec.size}:
                    raise PublicPilotIntakeError("audit_payload_binding_mismatch")
                if action == "acquire_failed" and (set(details) != {"reason", "retained"}
                        or not isinstance(details["reason"], str)
                        or type(details["retained"]) is not bool):
                    raise PublicPilotIntakeError("audit_failure_record_invalid")
                states[key] = action
            elif action in {"format_read", "integrity_read", "xml_inventory_read",
                            "review_read", "v3_replay_read"}:
                if states.get(key) != "acquired":
                    raise PublicPilotIntakeError("read_before_acquisition")
                if action == "format_read" and (set(details) != {"max_bytes"}
                        or type(details["max_bytes"]) is not int
                        or not 1 <= details["max_bytes"] <= 256 * 1024):
                    raise PublicPilotIntakeError("audit_read_record_invalid")
                if action == "integrity_read" and details != {
                        "purpose": "payload_sha256_replay"}:
                    raise PublicPilotIntakeError("audit_read_record_invalid")
                if action == "xml_inventory_read" and details != {
                        "parser_revision": "public-xml-structure-1",
                        "max_records": 250000, "max_line_bytes": 1048576} and details != {
                        "parser_revision": "public-xml-structure-2",
                        "max_records": 250000, "max_line_bytes": 1048576} and details != {
                        "parser_revision": "public-xml-structure-3",
                        "max_records": 250000, "max_line_bytes": 1048576} and details != {
                        "parser_revision": "public-xml-structure-4",
                        "max_records": 250000, "max_line_bytes": 1048576}:
                    raise PublicPilotIntakeError("audit_read_record_invalid")
                if action == "review_read" and (
                        self.audit_version != "public-dev-intake-1" or details != {
                            "purpose": "scenario_review_worklist_v1",
                            "max_records": 250000, "max_line_bytes": 1048576}):
                    raise PublicPilotIntakeError("audit_read_record_invalid")
                if action == "v3_replay_read" and (
                        self.audit_version != "public-dev-intake-1"
                        or set(details) != {"purpose", "owner_grant_sha256",
                                            "boundary_manifest_sha256",
                                            "membership_manifest_sha256"}
                        or details["purpose"] != "owner_authorized_v3_replay"
                        or any(type(details[name]) is not str
                               or not re.fullmatch(r"[0-9a-f]{64}", details[name]) for name in (
                                   "owner_grant_sha256", "boundary_manifest_sha256",
                                   "membership_manifest_sha256"))):
                    raise PublicPilotIntakeError("audit_read_record_invalid")
            else:
                raise PublicPilotIntakeError("unknown_audit_action")
            previous = digest
        if not allow_pending and "pending" in states.values():
            raise PublicPilotIntakeError("interrupted_acquisition_requires_owner_review")
        return len(audit_files), previous, states

    @contextmanager
    def _lock(self) -> Iterator[None]:
        path = self.audit / "active.lock"
        _create_new(path, _canonical({"owner": getpass.getuser(),
                                      "at_utc": datetime.now(timezone.utc).isoformat()}))
        try:
            yield
        finally:
            path.unlink()

    def _append(self, action: str, artifact_key: str, details: dict[str, object]) -> str:
        sequence, previous, _ = self._replay(allow_lock=True, allow_pending=True)
        event = {
            "action": action, "actor": getpass.getuser(),
            "artifact_key": artifact_key,
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "details": details,
            "previous_sha256": previous,
            "proposal_sha256": self._proposal_digest,
            "sequence": sequence + 1,
            "version": self.audit_version,
        }
        payload = _canonical(event)
        digest = _sha(payload)
        stem = f"{sequence + 1:06d}-{digest}"
        _create_new(self.audit / (stem + ".json"), payload)
        _create_new(self.heads / (stem + ".head"), (digest + "\n").encode("ascii"))
        return digest

    def verify(self, *, trusted_head_sha256: str | None = None) -> dict[str, object]:
        self._preflight()
        sequence, head, states = self._replay()
        self._require_external_head(sequence, head, trusted_head_sha256)
        self._require_local_pin(sequence, head)
        expected_files = {f"{key}.log" for key in states}
        actual_files = {path.name for path in self.raw.iterdir()}
        if actual_files != expected_files:
            raise PublicPilotIntakeError("unexpected_or_missing_payload_path")
        verified: list[str] = []
        if states:
            with self._lock():
                sequence, head, states = self._replay(allow_lock=True)
                self._require_external_head(sequence, head, trusted_head_sha256)
                self._require_local_pin(sequence, head)
                for key, status in states.items():
                    path = self.raw / f"{key}.log"
                    _assert_no_links(path)
                    if not path.is_file():
                        raise PublicPilotIntakeError("payload_missing_or_unsafe")
                    if status == "acquired":
                        head = self._append("integrity_read", key,
                                            {"purpose": "payload_sha256_replay"})
                        spec = self.manifest[key]
                        if path.stat().st_size != spec.size or _file_sha(path) != spec.sha256:
                            raise PublicPilotIntakeError("persisted_payload_hash_mismatch")
                        verified.append(key)
        self.custody_check(self.workspace)
        final_sequence, final_head, _ = self._replay()
        return {"events": final_sequence, "head_sha256": final_head,
                "acquired_keys": sorted(verified), "failed_keys": sorted(
                    key for key, status in states.items() if status == "acquire_failed")}

    def verify_one(self, key: str, *, trusted_head_sha256: str) -> dict[str, object]:
        """Log one exact payload read before replaying its pinned digest."""
        self._preflight()
        if key not in self.manifest:
            raise PublicPilotIntakeError("artifact_not_approved")
        with self._lock():
            sequence, head, states = self._replay(allow_lock=True)
            self._require_external_head(sequence, head, trusted_head_sha256)
            self._require_local_pin(sequence, head)
            if states.get(key) != "acquired":
                raise PublicPilotIntakeError("artifact_not_acquired")
            path = self.raw / f"{key}.log"
            _assert_no_links(path)
            if not path.is_file():
                raise PublicPilotIntakeError("payload_missing_or_unsafe")
            new_head = self._append("integrity_read", key,
                                    {"purpose": "payload_sha256_replay"})
            artifact = self.manifest[key]
            if path.stat().st_size != artifact.size or _file_sha(path) != artifact.sha256:
                raise PublicPilotIntakeError("persisted_payload_hash_mismatch")
            self.custody_check(self.workspace)
            return {"artifact_key": key, "sha256": artifact.sha256,
                    "size": artifact.size, "audit_head_sha256": new_head}

    def acquire_stream(self, key: str, source: BinaryIO, *,
                       trusted_head_sha256: str | None = None) -> dict[str, object]:
        self._preflight()
        if key not in self.manifest:
            raise PublicPilotIntakeError("artifact_not_approved")
        spec = self.manifest[key]
        destination = self.raw / f"{key}.log"
        with self._lock():
            sequence, head, states = self._replay(allow_lock=True)
            self._require_external_head(sequence, head, trusted_head_sha256)
            self._require_local_pin(sequence, head)
            if key in states or destination.exists() or destination.is_symlink():
                raise PublicPilotIntakeError("artifact_already_attempted_or_present")
            self._append("acquire_started", key, {
                "expected_sha256": spec.sha256, "expected_size": spec.size,
                "repository_path": spec.path, "revision": REVISION,
            })
            try:
                digest = hashlib.sha256()
                total = 0
                with destination.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > spec.size:
                            raise PublicPilotIntakeError("download_exceeds_pinned_size")
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if total != spec.size or digest.hexdigest() != spec.sha256:
                    raise PublicPilotIntakeError("download_digest_or_size_mismatch")
                if _file_sha(destination) != spec.sha256:
                    raise PublicPilotIntakeError("persisted_payload_hash_mismatch")
                self.custody_check(self.workspace)
                head = self._append("acquired", key, {"sha256": spec.sha256,
                                                       "size": total})
                return {"artifact_key": key, "size": total,
                        "sha256": spec.sha256, "audit_head_sha256": head}
            except Exception as exc:
                # A partial file is deliberately retained; no retry overwrites it.
                self._append("acquire_failed", key, {"reason": type(exc).__name__,
                                                           "retained": destination.exists()})
                raise

    def acquire_https(self, key: str, *,
                      trusted_head_sha256: str | None = None) -> dict[str, object]:
        self._preflight()
        if key not in self.manifest:
            raise PublicPilotIntakeError("artifact_not_approved")
        spec = self.manifest[key]
        url = ("https://media.githubusercontent.com/media/splunk/attack_data/"
               + REVISION + "/" + urllib.parse.quote(spec.path, safe="/"))
        request = urllib.request.Request(url, headers={"User-Agent": "EGIS-SOC-D026"})
        opener = urllib.request.build_opener(_GitHubRedirectHandler())
        with opener.open(request, timeout=90) as response:
            final = urllib.parse.urlparse(response.url)
            if not _approved_host(final):
                raise PublicPilotIntakeError("unapproved_download_host")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != spec.size:
                raise PublicPilotIntakeError("remote_content_length_mismatch")
            return self.acquire_stream(key, response,
                                       trusted_head_sha256=trusted_head_sha256)

    def probe_format(self, key: str, *, trusted_head_sha256: str,
                     prefix_limit: int = 256 * 1024) -> dict[str, object]:
        """Audit one bounded read and return structure only, never event values."""
        if prefix_limit < 1 or prefix_limit > 256 * 1024:
            raise ValueError("format probe limit must be bounded")
        self._preflight()
        if key not in self.manifest:
            raise PublicPilotIntakeError("artifact_not_approved")
        with self._lock():
            sequence, head, states = self._replay(allow_lock=True)
            self._require_external_head(sequence, head, trusted_head_sha256)
            self._require_local_pin(sequence, head)
            if states.get(key) != "acquired":
                raise PublicPilotIntakeError("format_probe_requires_acquired_artifact")
            new_head = self._append("format_read", key, {"max_bytes": prefix_limit})
            artifact_path = self.raw / f"{key}.log"
            _assert_no_links(artifact_path)
            spec = self.manifest[key]
            if (artifact_path.stat().st_size != spec.size or
                    _file_sha(artifact_path) != spec.sha256):
                raise PublicPilotIntakeError("persisted_payload_hash_mismatch")
            with artifact_path.open("rb") as stream:
                prefix = stream.read(prefix_limit)
            lines = prefix.splitlines(keepends=True)
            complete = [line for line in lines[:-1] if line.strip()]
            if lines and lines[-1].endswith((b"\n", b"\r")) and lines[-1].strip():
                complete.append(lines[-1])
            kinds: list[str] = []
            shapes: list[dict[str, object]] = []
            for line in complete[:3]:
                stripped = line.lstrip()
                shapes.append({"bytes": len(line), "leading_space_bytes": len(line) - len(stripped),
                               "open_brace": stripped.startswith(b"{"),
                               "open_angle": stripped.startswith(b"<"),
                               "open_bracket": stripped.startswith(b"["),
                               "timestamp_prefix": bool(re.match(
                                   rb"\d{4}[-/]\d{2}[-/]\d{2}[ T]", stripped))})
                try:
                    item = json.loads(line.decode("utf-8"))
                    kinds.append("json_object" if isinstance(item, dict) else "json_other")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    kinds.append("not_json")
            known_object_keys: list[str] = []
            object_key_count = 0
            try:
                decoded = prefix.decode("utf-8-sig")
                first_object, _ = json.JSONDecoder().raw_decode(decoded.lstrip())
                if isinstance(first_object, dict):
                    object_key_count = len(first_object)
                    known = {"Event", "EventTime", "Message", "source", "sourcetype",
                             "host", "_raw", "_time", "result", "EventID",
                             "EventData", "TimeCreated", "Computer", "Provider", "Channel"}
                    known_object_keys = sorted(known.intersection(first_object))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            self.custody_check(self.workspace)
            return {"artifact_key": key, "sampled_prefix_bytes": len(prefix),
                    "complete_lines_in_prefix": len(complete),
                    "first_three_record_kinds": kinds,
                    "first_three_line_shapes": shapes,
                    "prefix_byte_classes": {"null": prefix.count(b"\x00"),
                                            "tab": prefix.count(b"\t"),
                                            "lf": prefix.count(b"\n"),
                                            "open_brace": prefix.count(b"{")},
                    "first_json_object_key_count": object_key_count,
                    "known_json_keys_present": known_object_keys,
                    "audit_head_sha256": new_head}

    def inspect_xml_structure(self, key: str, *,
                              trusted_head_sha256: str) -> dict[str, object]:
        """Audit a bounded full-file XML structure review; emit no event values."""
        self._preflight()
        if key not in self.manifest:
            raise PublicPilotIntakeError("artifact_not_approved")
        with self._lock():
            sequence, head, states = self._replay(allow_lock=True)
            self._require_external_head(sequence, head, trusted_head_sha256)
            self._require_local_pin(sequence, head)
            if states.get(key) != "acquired":
                raise PublicPilotIntakeError("xml_review_requires_acquired_artifact")
            new_head = self._append("xml_inventory_read", key, {
                "parser_revision": "public-xml-structure-4",
                "max_records": 250000, "max_line_bytes": 1048576,
            })
            path = self.raw / f"{key}.log"
            _assert_no_links(path)
            spec = self.manifest[key]
            if path.stat().st_size != spec.size or _file_sha(path) != spec.sha256:
                raise PublicPilotIntakeError("persisted_payload_hash_mismatch")
            events: Counter[int] = Counter()
            channels: Counter[str] = Counter()
            field_presence: Counter[str] = Counter()
            minute_bins: Counter[str] = Counter()
            hosts: set[str] = set()
            users: set[str] = set()
            record_keys: set[tuple[str, str, str]] = set()
            process_guids: set[str] = set()
            process_starts: dict[str, tuple[int, str, str]] = {}
            parent_guids: list[str] = []
            child_guid_counts: Counter[str] = Counter()
            candidate_signals: list[dict[str, object]] = []
            candidate_signal_count = 0
            file_signals: list[dict[str, object]] = []
            file_signal_count = 0
            duplicate_record_ids = 0
            invalid_lines: list[int] = []
            event1_lines: list[int] = []
            times: list[datetime] = []
            total = parsed = 0
            bytes_seen = 0
            with path.open("rb") as stream:
                for number, line in enumerate(stream, 1):
                    total = number
                    bytes_seen += len(line)
                    if number > 250000 or len(line) > 1048576:
                        raise PublicPilotIntakeError("xml_inventory_bound_exceeded")
                    if b"<!DOCTYPE" in line or b"<!ENTITY" in line:
                        if len(invalid_lines) < 20:
                            invalid_lines.append(number)
                        continue
                    try:
                        event = _xml_event_structure(line)
                    except (ET.ParseError, ValueError, UnicodeDecodeError, KeyError):
                        if len(invalid_lines) < 20:
                            invalid_lines.append(number)
                        continue
                    parsed += 1
                    code, channel, host, record_id, timestamp, data = event
                    events[code] += 1
                    channels[channel if channel in {
                        "Microsoft-Windows-Sysmon/Operational", "Security", "System"}
                        else "other"] += 1
                    hosts.add(host)
                    if data.get("User"):
                        users.add(data["User"])
                    record_key = (host, channel, record_id)
                    if record_key in record_keys:
                        duplicate_record_ids += 1
                    record_keys.add(record_key)
                    times.append(timestamp)
                    minute_bins[timestamp.strftime("%Y-%m-%dT%H:%MZ")] += 1
                    for name in ("Image", "CommandLine", "User", "ParentImage",
                                 "ProcessGuid", "ParentProcessGuid"):
                        if data.get(name):
                            field_presence[name] += 1
                    if code == 1:
                        if len(event1_lines) < 12:
                            event1_lines.append(number)
                        if data.get("ProcessGuid"):
                            process_guids.add(data["ProcessGuid"])
                            process_starts[data["ProcessGuid"]] = (
                                number, record_id, timestamp.isoformat())
                        if data.get("ParentProcessGuid"):
                            parent_guids.append(data["ParentProcessGuid"])
                            child_guid_counts[data["ParentProcessGuid"]] += 1
                        basename = ntpath.basename(data.get("Image", "")).casefold()
                        category = next((label for term, label in _EXECUTABLE_SIGNALS.items()
                                         if term in basename), None)
                        if category is None and any(term in data.get("CommandLine", "").casefold()
                                                    for term in ("ryuk", "conti")):
                            category = "scenario_term_in_command_line"
                        if category is not None:
                            candidate_signal_count += 1
                            if len(candidate_signals) < 20:
                                candidate_signals.append({
                                    "physical_line": number, "event_record_id": record_id,
                                    "event_time_utc": timestamp.isoformat(),
                                    "signal_category": category,
                                    "process_guid": data.get("ProcessGuid"),
                                    "parent_guid": data.get("ParentProcessGuid"),
                                })
                    if code in {11, 23}:
                        file_name = ntpath.basename(data.get("TargetFilename", "")).casefold()
                        if any(term in file_name for term in ("ryuk", "readme", "decrypt", "recover")):
                            file_signal_count += 1
                            if len(file_signals) < 20:
                                file_signals.append({
                                    "physical_line": number, "event_record_id": record_id,
                                    "event_time_utc": timestamp.isoformat(),
                                    "event_code": code,
                                    "signal_category": "scenario_term_in_filename",
                                    "process_guid": data.get("ProcessGuid"),
                                })
            if bytes_seen != spec.size:
                raise PublicPilotIntakeError("xml_inventory_byte_count_mismatch")
            for signal in candidate_signals:
                guid = signal.pop("process_guid")
                parent = signal.pop("parent_guid")
                signal["captured_child_process_starts"] = child_guid_counts[guid] if guid else 0
                signal["parent_start_in_capture"] = parent in process_guids if parent else False
            for signal in file_signals:
                guid = signal.pop("process_guid")
                linked = process_starts.get(guid) if guid else None
                signal["source_process_start_line"] = linked[0] if linked else None
                signal["source_process_start_record_id"] = linked[1] if linked else None
                signal["source_process_start_utc"] = linked[2] if linked else None
            self.custody_check(self.workspace)
            return {
                "artifact_key": key, "audit_head_sha256": new_head,
                "review_revision": "public-xml-structure-4",
                "physical_lines": total, "parsed_xml_events": parsed,
                "quarantined_lines": total - parsed,
                "first_quarantined_line_numbers": invalid_lines,
                "event_code_counts": dict(sorted(events.items())),
                "channel_counts": dict(sorted(channels.items())),
                "first_event_1_line_numbers": event1_lines,
                "first_event_utc": min(times).isoformat() if times else None,
                "last_event_utc": max(times).isoformat() if times else None,
                "largest_minute_bins": minute_bins.most_common(8),
                "unique_host_count": len(hosts), "unique_user_count": len(users),
                "duplicate_host_channel_record_ids": duplicate_record_ids,
                "event_data_presence": dict(sorted(field_presence.items())),
                "unique_process_guids": len(process_guids),
                "parent_guid_links_in_capture": sum(
                    parent in process_guids for parent in parent_guids),
                "parent_guid_refs": len(parent_guids),
                "candidate_execution_signal_count": candidate_signal_count,
                "candidate_execution_signals_first_20": candidate_signals,
                "candidate_file_signal_count": file_signal_count,
                "candidate_file_signals_first_20": file_signals,
            }


def _xml_event_structure(raw: bytes) -> tuple[int, str, str, str, datetime,
                                                   dict[str, str]]:
    root = ET.fromstring(raw)
    if _local_xml_name(root.tag) != "Event":
        raise ValueError("not_event_xml")
    system = next((child for child in root if _local_xml_name(child.tag) == "System"), None)
    if system is None:
        raise ValueError("missing_system")
    children = {_local_xml_name(child.tag): child for child in system}
    code = int((children["EventID"].text or "").strip())
    channel = (children["Channel"].text or "").strip()
    host = (children["Computer"].text or "").strip()
    record_id = (children["EventRecordID"].text or "").strip()
    raw_time = children["TimeCreated"].attrib["SystemTime"]
    timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    if (code <= 0 or not channel or not host or not record_id
            or timestamp.utcoffset() is None):
        raise ValueError("incomplete_event_system")
    timestamp = timestamp.astimezone(timezone.utc)
    data: dict[str, str] = {}
    event_data = next((child for child in root if _local_xml_name(child.tag) == "EventData"), None)
    if event_data is not None:
        for child in event_data:
            if _local_xml_name(child.tag) == "Data":
                name = child.attrib.get("Name", "")
                if name and name not in data:
                    data[name] = (child.text or "").strip()
    return code, channel, host, record_id, timestamp, data


def _local_xml_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _approved_host(parsed: urllib.parse.ParseResult) -> bool:
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == "github.com" or
        host.endswith(".githubusercontent.com"))


class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _approved_host(urllib.parse.urlparse(newurl)):
            raise PublicPilotIntakeError("unapproved_download_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)
