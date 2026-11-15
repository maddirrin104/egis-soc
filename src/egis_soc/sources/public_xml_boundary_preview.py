"""Synthetic-only byte-boundary preview for D-026 direct XML log candidates.

Physical LF lines are observations, not owner-approved D-021 XML boundaries.
This module issues no source/evidence IDs and never reads a real source path.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone


MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_RECORDS = 250_000
MAX_LINE_BYTES = 1 * 1024 * 1024
_CHANNELS = frozenset({"Microsoft-Windows-Sysmon/Operational", "Security", "System"})
_PROVIDERS = {
    "Microsoft-Windows-Sysmon/Operational": "Microsoft-Windows-Sysmon",
    "Security": "Microsoft-Windows-Security-Auditing",
    "System": "Service Control Manager",
}
_SYSTEM_FIELDS = frozenset({"Provider", "EventID", "Version", "Level", "Task", "Opcode",
                            "Keywords", "TimeCreated", "EventRecordID", "Correlation",
                            "Execution", "Channel", "Computer", "Security"})
_REQUIRED = frozenset({"Provider", "EventID", "TimeCreated", "EventRecordID",
                       "Channel", "Computer"})
_XML_TIME = re.compile(
    r"(?P<base>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]{1,9}))?"
    r"(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class XmlBoundaryPreviewError(ValueError):
    """The exact bytes do not support this provisional line framing."""


@dataclass(frozen=True, slots=True)
class XmlLineBoundary:
    ordinal: int
    byte_offset: int
    byte_length: int
    raw_sha256: str
    event_record_id: str
    event_time_utc: str
    event_code: int
    channel: str


@dataclass(frozen=True, slots=True)
class ParsedXmlEvent:
    provider: str
    channel: str
    computer: str
    event_id: int
    event_record_id: str
    timestamp_original: str
    timestamp_utc: datetime
    timestamp_precision_digits: int
    event_data: dict[str, str]


def _name(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        namespace, local = tag[1:].split("}", 1)
        return namespace, local
    return None, tag


def parse_xml_event(raw: bytes) -> ParsedXmlEvent:
    """Parse one UTF-8 Event without repairing bytes or inferring missing values."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_LINE_BYTES:
        raise XmlBoundaryPreviewError("invalid_or_oversized_record")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise XmlBoundaryPreviewError("invalid_utf8") from exc
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, re.IGNORECASE):
        raise XmlBoundaryPreviewError("prohibited_xml_declaration")
    if re.search(r"<\?xml\b[^?]*\bencoding\s*=\s*['\"](?!utf-8['\"])[^'\"]+", decoded,
                 re.IGNORECASE):
        raise XmlBoundaryPreviewError("unsupported_encoding")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise XmlBoundaryPreviewError("malformed_xml") from exc
    namespace, local = _name(root.tag)
    if local != "Event" or namespace not in (None,
            "http://schemas.microsoft.com/win/2004/08/events/event") or root.attrib:
        raise XmlBoundaryPreviewError("unsupported_xml_structure")
    if (root.text or "").strip():
        raise XmlBoundaryPreviewError("unsupported_xml_structure")
    sections: dict[str, ET.Element] = {}
    for child in root:
        child_ns, name = _name(child.tag)
        if (child_ns != namespace or name not in {"System", "EventData"}
                or name in sections or (child.tail or "").strip()):
            raise XmlBoundaryPreviewError("unsupported_xml_structure")
        sections[name] = child
    if "System" not in sections:
        raise XmlBoundaryPreviewError("missing_required_xml_field")
    if (sections["System"].attrib or (sections["System"].text or "").strip()
            or ("EventData" in sections and (sections["EventData"].attrib
                                             or (sections["EventData"].text or "").strip()))):
        raise XmlBoundaryPreviewError("unsupported_xml_structure")
    system: dict[str, ET.Element] = {}
    for child in sections["System"]:
        child_ns, name = _name(child.tag)
        if (child_ns != namespace or name not in _SYSTEM_FIELDS or name in system
                or len(child) or (child.tail or "").strip()):
            raise XmlBoundaryPreviewError("unsupported_xml_structure")
        system[name] = child
    if not _REQUIRED <= system.keys():
        raise XmlBoundaryPreviewError("missing_required_xml_field")
    if (not set(system["Provider"].attrib) <= {"Name", "Guid"}
            or set(system["TimeCreated"].attrib) != {"SystemTime"}
            or any(system[name].attrib for name in ("EventID", "EventRecordID",
                                                   "Channel", "Computer"))):
        raise XmlBoundaryPreviewError("unsupported_xml_structure")
    def value(name: str) -> str:
        return (system[name].text or "").strip()
    provider = system["Provider"].get("Name", "").strip()
    channel, computer, record_id = value("Channel"), value("Computer"), value("EventRecordID")
    code = value("EventID")
    if (channel not in _CHANNELS or provider != _PROVIDERS[channel]
            or not computer or not record_id.isascii() or not record_id.isdecimal()
            or len(record_id) > 20 or int(record_id) <= 0
            or str(int(record_id)) != record_id
            or not code.isascii() or not code.isdecimal()
            or len(code) > 10 or int(code) <= 0 or str(int(code)) != code
            or (system["Provider"].text or "").strip()):
        raise XmlBoundaryPreviewError("invalid_xml_identity")
    raw_time = system["TimeCreated"].get("SystemTime", "")
    time_match = _XML_TIME.fullmatch(raw_time)
    if time_match is None:
        raise XmlBoundaryPreviewError("invalid_xml_timestamp")
    try:
        fraction = time_match.group("fraction") or ""
        # W1 datetime stores microseconds. Preserve the original 100 ns/ns
        # timestamp in provenance; the normalized UTC view floors sub-microseconds.
        normalized_time = (time_match.group("base")
                           + ("." + fraction[:6] if fraction else "")
                           + time_match.group("zone").replace("Z", "+00:00"))
        timestamp = datetime.fromisoformat(normalized_time)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timezone missing")
        timestamp = timestamp.astimezone(timezone.utc)
    except ValueError as exc:
        raise XmlBoundaryPreviewError("invalid_xml_timestamp") from exc
    data: dict[str, str] = {}
    if "EventData" in sections:
        for child in sections["EventData"]:
            child_ns, name = _name(child.tag)
            key = child.get("Name", "")
            if (child_ns != namespace or name != "Data" or len(child)
                    or set(child.attrib) != {"Name"} or not key or key != key.strip()
                    or key in data or (child.tail or "").strip()):
                raise XmlBoundaryPreviewError("unsupported_xml_event_data")
            data[key] = (child.text or "").strip()
    return ParsedXmlEvent(provider, channel, computer, int(code), record_id,
                          raw_time, timestamp, len(fraction), data)


def preview_direct_xml_lines(raw: bytes) -> tuple[XmlLineBoundary, ...]:
    """Return exact physical-line locators after strict structural checks.

    The returned rows are proposals for a future owner-reviewed byte-boundary
    manifest. They cannot be passed directly to real identity allocation.
    """
    if type(raw) is not bytes or not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise XmlBoundaryPreviewError("invalid_or_oversized_artifact")
    rows: list[XmlLineBoundary] = []
    seen: set[tuple[str, str, str]] = set()
    offset = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        end = len(raw) if newline < 0 else newline + 1
        slice_bytes = raw[offset:end]
        ordinal = len(rows) + 1
        if ordinal > MAX_RECORDS or len(slice_bytes) > MAX_LINE_BYTES:
            raise XmlBoundaryPreviewError("record_count_or_byte_cap_exceeded")
        if not slice_bytes.strip(b"\r\n"):
            raise XmlBoundaryPreviewError("blank_or_unsafe_xml_line")
        try:
            parsed = parse_xml_event(slice_bytes)
        except XmlBoundaryPreviewError as exc:
            raise XmlBoundaryPreviewError("line_is_not_one_valid_xml_event") from exc
        key = (parsed.computer, parsed.channel, parsed.event_record_id)
        if key in seen:
            raise XmlBoundaryPreviewError("duplicate_source_record_id")
        seen.add(key)
        rows.append(XmlLineBoundary(
            ordinal=ordinal, byte_offset=offset, byte_length=len(slice_bytes),
            raw_sha256=hashlib.sha256(slice_bytes).hexdigest(),
            event_record_id=parsed.event_record_id,
            event_time_utc=parsed.timestamp_utc.isoformat(),
            event_code=parsed.event_id, channel=parsed.channel,
        ))
        offset = end
    return tuple(rows)
