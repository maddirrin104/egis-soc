"""Private PDS-01 event inventory for owner review, never incident gold.

Only a custody-gated intake caller may supply bytes. The output is sensitive
and belongs outside Git. Physical XML lines and proposed locators are not
approved D-021 v3 boundaries or production REAL identities.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta

from egis_soc.governance.integrity import canonical_bytes
from egis_soc.sources.public_xml_boundary_preview import parse_xml_event, preview_direct_xml_lines


REVIEW_FIELDS = (
    "Image", "ParentImage", "CommandLine", "ParentCommandLine",
    "TargetFilename", "TargetObject", "Details", "DestinationIp",
    "DestinationPort", "SourceIp", "SourcePort", "User", "ProcessGuid",
    "ParentProcessGuid", "Hashes", "ServiceName", "RuleName",
)


def build_artifact_inventory(
    raw: bytes, *, artifact_key: str, group_key: str,
    repository_path: str, artifact_sha256: str, audit_head_sha256: str,
) -> tuple[dict[str, object], bytes]:
    """Return exhaustive provisional locators and conservative summaries.

    All record membership remains UNDECIDED here. A separate explicit rule
    and owner review are required before any incident-scope claim.
    """
    if hashlib.sha256(raw).hexdigest() != artifact_sha256:
        raise ValueError("review_artifact_hash_mismatch")
    boundaries = preview_direct_xml_lines(raw)
    hosts: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    channels: Counter[str] = Counter()
    fields_seen: Counter[str] = Counter()
    observed: list[str] = []
    output: list[bytes] = []
    for row in boundaries:
        exact = raw[row.byte_offset:row.byte_offset + row.byte_length]
        parsed = parse_xml_event(exact)
        locator = {
            "artifact_key": artifact_key, "repository_path": repository_path,
            "artifact_sha256": artifact_sha256,
            "ordinal": row.ordinal, "byte_offset": row.byte_offset,
            "byte_length": row.byte_length, "raw_sha256": row.raw_sha256,
            "event_record_id": row.event_record_id,
            "event_time_utc": row.event_time_utc,
            "event_code": row.event_code, "channel": row.channel,
            "timestamp_original": parsed.timestamp_original,
            "timestamp_precision_digits": parsed.timestamp_precision_digits,
        }
        reference = ("PDS01-LOC3-" + base64.b32encode(
            hashlib.sha256(canonical_bytes(locator)).digest()
        ).decode("ascii").rstrip("="))
        selected = {key: parsed.event_data[key][:512] for key in REVIEW_FIELDS
                    if parsed.event_data.get(key)}
        for field in selected:
            fields_seen[field] += 1
        hosts[parsed.computer] += 1
        providers[parsed.provider] += 1
        codes[str(parsed.event_id)] += 1
        channels[parsed.channel] += 1
        observed.append(row.event_time_utc)
        output.append(canonical_bytes({
            "version": "pds01-private-event-inventory-1",
            "artifact_key": artifact_key, "group_key": group_key,
            "source_ref": reference, "locator": locator,
            "provider": parsed.provider, "host": parsed.computer,
            "event_fields": selected,
            "proposed_membership": "UNDECIDED",
            "review_status": "AI_PROPOSED_NOT_GOLD",
        }) + b"\n")
    summary: dict[str, object] = {
        "version": "pds01-private-artifact-inventory-1",
        "artifact_key": artifact_key, "group_key": group_key,
        "repository_path": repository_path,
        "artifact_sha256": artifact_sha256,
        "source_audit_head_sha256": audit_head_sha256,
        "record_count": len(boundaries),
        "observed_first_utc": min(observed),
        "observed_last_utc": max(observed),
        "host_counts": dict(sorted(hosts.items())),
        "provider_counts": dict(sorted(providers.items())),
        "channel_counts": dict(sorted(channels.items())),
        "event_code_counts": dict(sorted(codes.items())),
        "selected_field_presence": dict(sorted(fields_seen.items())),
        "upstream_run_id": "UNKNOWN",
        "incident_boundary_status": "PENDING_OWNER_REVIEW",
        "owner_review_status": "UNREVIEWED",
        "complete_physical_line_inventory": True,
        "physical_lines_are_approved_incident_membership": False,
    }
    return summary, b"".join(output)


def load_inventory(content: bytes, *, expected_sha256: str,
                   artifact_key: str) -> list[dict[str, object]]:
    """Validate an immutable private inventory before deriving membership."""
    if (type(content) is not bytes or hashlib.sha256(content).hexdigest()
            != expected_sha256):
        raise ValueError("inventory_hash_mismatch")
    rows: list[dict[str, object]] = []
    seen_refs: set[str] = set()
    last_end = 0
    for line in content.splitlines(keepends=True):
        try:
            row = json.loads(line)
            if (type(row) is not dict or canonical_bytes(row) + b"\n" != line
                    or row["version"] != "pds01-private-event-inventory-1"
                    or row["artifact_key"] != artifact_key
                    or row["proposed_membership"] != "UNDECIDED"
                    or row["review_status"] != "AI_PROPOSED_NOT_GOLD"):
                raise ValueError("invalid_inventory_row")
            locator = row["locator"]
            reference = ("PDS01-LOC3-" + base64.b32encode(
                hashlib.sha256(canonical_bytes(locator)).digest()
            ).decode("ascii").rstrip("="))
            offset, length = locator["byte_offset"], locator["byte_length"]
            if (locator["artifact_key"] != artifact_key
                    or locator["ordinal"] != len(rows) + 1
                    or type(offset) is not int or type(length) is not int
                    or offset != last_end or length <= 0
                    or row["source_ref"] != reference
                    or reference in seen_refs):
                raise ValueError("inventory_locator_mismatch")
            datetime.fromisoformat(locator["event_time_utc"])
            seen_refs.add(reference)
            last_end = offset + length
            rows.append(row)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_inventory_row") from exc
    if not rows:
        raise ValueError("empty_inventory")
    return rows


def proposed_membership(row: dict[str, object], *, group_key: str,
                        start_utc: str, end_utc: str,
                        included_hosts: frozenset[str]) -> str:
    """Apply a stated provisional UTC/host rule to one exact source row."""
    try:
        start, end = datetime.fromisoformat(start_utc), datetime.fromisoformat(end_utc)
        observed = datetime.fromisoformat(row["locator"]["event_time_utc"])
        if (type(row) is not dict or row["group_key"] != group_key
                or not included_hosts or start.utcoffset() != timedelta(0)
                or end.utcoffset() != timedelta(0)
                or observed.utcoffset() != timedelta(0) or start > end):
            raise ValueError("invalid_membership_rule")
        if row["host"] not in included_hosts:
            return "PROPOSED_EXCLUDE_HOST"
        if not start <= observed <= end:
            return "PROPOSED_EXCLUDE_TIME"
        return "PROPOSED_INCLUDE"
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("invalid_membership_rule") from exc


def propose_atomic_field_claim(row: dict[str, object], *, field: str
                               ) -> dict[str, object]:
    """Suggest one directly observable fact, without approving its label."""
    if field not in REVIEW_FIELDS or type(row) is not dict:
        raise ValueError("unsupported_claim_field")
    try:
        observed = row["event_fields"][field]
        if (type(observed) is not str or not observed or len(observed) >= 512
                or re.search(r"(?i)(?:\s-p\s+|--password\b|password\s*=)", observed)
                or row["review_status"] != "AI_PROPOSED_NOT_GOLD"
                or row["proposed_membership"] != "UNDECIDED"
                or not row["source_ref"].startswith("PDS01-LOC3-")):
            raise ValueError("unsafe_or_truncated_claim_field")
        locator = row["locator"]
        return {
            "group_key": row["group_key"],
            "artifact_key": row["artifact_key"],
            "source_ref": row["source_ref"],
            "event_time_utc": locator["event_time_utc"],
            "event_code": locator["event_code"],
            "field": field,
            "observed_value": observed,
            "claim": f"The cited Sysmon event recorded {field} as {observed}.",
            "proposed_label": "supported",
            "proposed_rationale": (
                "Direct equality to the named field in the fixed XML slice; "
                "no attack cause, effect or outcome is inferred."),
            "human_label": "UNREVIEWED",
            "human_decision": None,
            "criticality": "PENDING_OWNER_REVIEW",
            "observability": "PENDING_OWNER_REVIEW",
            "gold_status": "NOT_GOLD",
        }
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("invalid_claim_source_row") from exc
