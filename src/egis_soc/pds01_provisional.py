"""Private, unreviewed PDS-01 development bundles; never production or gold."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
from pathlib import Path

from .integrity import canonical_bytes
from .pds01_owner_review import proposed_membership
from .splunk_xml_replay import prepare_synthetic_pds01_xml_replay


VERSION = "pds01-development-provisional-1"
_SECRET = re.compile(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|credential)\s*[:=]\s*[^\s,;]+")
_SENSITIVE_FIELDS = frozenset({"CommandLine", "ParentCommandLine", "Details", "User"})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _id(group: str, source_ref: str) -> str:
    digest = hashlib.sha256(canonical_bytes({
        "version": VERSION, "incident_id": f"PDS01-DEV-{group}-v1",
        "source_ref": source_ref,
    })).digest()
    return "PDS01-DEV-EV1-" + base64.b32encode(digest).decode("ascii").rstrip("=")


def _redact(value: str) -> str:
    return _SECRET.sub(lambda match: match.group(1) + "=[REDACTED]", value)


def _rows(raw: bytes) -> list[dict[str, str]]:
    stream = io.StringIO(raw.decode("utf-8-sig"), newline="")
    reader = csv.DictReader(stream, delimiter="\t")
    if reader.fieldnames is None or not {
        "source_key", "ordinal", "byte_offset", "byte_length", "raw_sha256",
        "event_time_utc", "host", "provider", "event_id", "event_record_id",
        "provisional_source_ref", "proposed_membership", "owner_decision",
    } <= set(reader.fieldnames):
        raise ValueError("membership_columns_missing")
    rows = list(reader)
    if not rows or any(row["owner_decision"] for row in rows):
        raise ValueError("membership_not_unreviewed")
    return rows


def validate_membership(group: str, rows: list[dict[str, str]],
                        rule: dict[str, object]) -> tuple[str, str]:
    lookup = {(row["source_key"], int(row["ordinal"])): row for row in rows}
    if len(lookup) != len(rows):
        raise ValueError("duplicate_membership_locator")
    start = lookup[(rule["start"]["artifact_key"], rule["start"]["ordinal"])]["event_time_utc"]
    end = lookup[(rule["end"]["artifact_key"], rule["end"]["ordinal"])]["event_time_utc"]
    hosts = frozenset(row["host"] for row in rows)
    ordered = sorted(rows, key=lambda row: (
        group == "S06" and row["source_key"] != "S06-03",
        row["source_key"], int(row["ordinal"])))
    seen_raw: dict[str, str] = {}
    for row in ordered:
        proposal = proposed_membership({
            "group_key": group, "host": row["host"],
            "locator": {"event_time_utc": row["event_time_utc"]},
        }, group_key=group, start_utc=start, end_utc=end,
            included_hosts=hosts)
        digest = row["raw_sha256"]
        if digest in seen_raw and seen_raw[digest] != row["source_key"]:
            if proposal == "PROPOSED_INCLUDE":
                proposal = "PROPOSED_EXCLUDE_DUPLICATE"
        else:
            seen_raw[digest] = row["source_key"]
        if proposal != row["proposed_membership"]:
            raise ValueError("membership_rule_mismatch")
    return start, end


def replay_artifact(raw: bytes, boundary: bytes, membership: list[dict[str, str]],
                    *, group: str, key: str, path: str, source_sha256: str,
                    boundary_sha256: str) -> tuple[list[dict[str, object]], dict[str, str]]:
    """Replay all exact bytes, validate every locator, return included events."""
    occurrences = prepare_synthetic_pds01_xml_replay(
        raw, boundary, trusted_manifest_sha256=boundary_sha256,
        expected_candidate_id=group, expected_artifact_path=path,
        expected_artifact_sha256=source_sha256)
    selected = [row for row in membership if row["source_key"] == key]
    if len(selected) != len(occurrences):
        raise ValueError("membership_record_count_mismatch")
    events: list[dict[str, object]] = []
    refs: dict[str, str] = {}
    evidence_ids: set[str] = set()
    for item, row in zip(occurrences, selected, strict=True):
        parsed = item.parsed
        if (int(row["ordinal"]) != item.ordinal
                or int(row["byte_offset"]) != item.byte_offset
                or int(row["byte_length"]) != len(item.raw_bytes)
                or row["raw_sha256"] != _sha(item.raw_bytes)
                or row["event_time_utc"] != parsed.timestamp_utc.isoformat()
                or row["host"] != parsed.computer
                or row["provider"] != parsed.provider
                or int(row["event_id"]) != parsed.event_id
                or row["event_record_id"] != parsed.event_record_id):
            raise ValueError("membership_replay_mismatch")
        if row["proposed_membership"] != "PROPOSED_INCLUDE":
            continue
        source_ref = row["provisional_source_ref"]
        evidence_id = _id(group, source_ref)
        if source_ref in refs or evidence_id in evidence_ids:
            raise ValueError("duplicate_provisional_evidence")
        refs[source_ref] = evidence_id
        evidence_ids.add(evidence_id)
        fields = {name: ("[REDACTED]" if group == "S07" and name in _SENSITIVE_FIELDS
                         else _redact(value)) for name, value in parsed.event_data.items()}
        events.append({
            "version": VERSION, "evidence_id": evidence_id,
            "incident_id": f"PDS01-DEV-{group}-v1", "tenant_id": "UNKNOWN",
            "source_ref": source_ref, "source_key": key, "repository_path": path,
            "source_dataset": "PDS-01", "artifact_sha256": source_sha256,
            "ordinal": item.ordinal, "byte_offset": item.byte_offset,
            "byte_length": len(item.raw_bytes), "raw_sha256": row["raw_sha256"],
            "timestamp_utc": row["event_time_utc"],
            "timestamp_original": parsed.timestamp_original,
            "provider": parsed.provider, "channel": parsed.channel,
            "host": parsed.computer, "event_id": parsed.event_id,
            "event_record_id": parsed.event_record_id, "event_data": fields,
            "membership_status": "AI_PROPOSED_INCLUDE_UNREVIEWED",
            "raw_message_ref": f"pds01-provisional:{key}:{item.ordinal}",
        })
    return events, refs


def link_annotations(group: str, pairs_raw: bytes, facts_raw: bytes,
                     refs: dict[str, str]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    pairs: list[dict[str, object]] = []
    facts: list[dict[str, object]] = []
    for row in csv.DictReader(io.StringIO(pairs_raw.decode("utf-8-sig")), delimiter="\t"):
        if row["scenario"] != group:
            continue
        if row["human_label"] != "UNREVIEWED" or row["source_ref"] not in refs:
            raise ValueError("pair_not_unreviewed_or_outside_incident")
        pairs.append({
            "pair_id": row["pair_id"], "incident_id": f"PDS01-DEV-{group}-v1",
            "tenant_id": "UNKNOWN", "claim": row["claim"],
            "evidence_ids": [refs[row["source_ref"]]],
            "proposed_label": row["ai_proposed_label"],
            "proposal_rationale": row["ai_proposed_rationale"],
            "annotation_source": "AI_PROPOSED", "human_label": "UNREVIEWED",
            "gold_status": "NOT_GOLD", "source_ref": row["source_ref"],
        })
    for row in csv.DictReader(io.StringIO(facts_raw.decode("utf-8-sig")), delimiter="\t"):
        if row["scenario"] != group:
            continue
        if (row["human_status"] != "UNREVIEWED" or row["gold_status"] != "NOT_GOLD"
                or row["fixed_source_ref"] not in refs):
            raise ValueError("fact_not_unreviewed_or_outside_incident")
        facts.append({
            "fact_id": row["fact_id"], "incident_id": f"PDS01-DEV-{group}-v1",
            "tenant_id": "UNKNOWN", "statement": row["candidate_fact"],
            "evidence_ids": [refs[row["fixed_source_ref"]]],
            "annotation_source": "AI_PROPOSED", "human_status": "UNREVIEWED",
            "gold_status": "NOT_GOLD", "criticality": "PENDING_OWNER_REVIEW",
            "observability": "PENDING_OWNER_REVIEW", "source_ref": row["fixed_source_ref"],
        })
    if len(pairs) != 5 or len(facts) != 2:
        raise ValueError("incomplete_scenario_annotations")
    return pairs, facts


def jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(canonical_bytes(row) + b"\n" for row in rows)


def load_bundle(directory: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    """W3 development loader; rejects gold and cross-incident references."""
    bundle = json.loads((directory / "bundle.json").read_bytes())
    if bundle.get("version") != VERSION or bundle.get("status") != "UNREVIEWED_DEVELOPMENT":
        raise ValueError("not_a_provisional_development_bundle")
    events = [json.loads(line) for line in (directory / "events.jsonl").read_bytes().splitlines()]
    ids = {event["evidence_id"] for event in events}
    by_ref = {event["source_ref"]: event["evidence_id"] for event in events}
    if len(ids) != len(events) or bundle["evidence_ids"] != [e["evidence_id"] for e in events]:
        raise ValueError("evidence_index_mismatch")
    if len(by_ref) != len(events):
        raise ValueError("duplicate_source_reference")
    if any(event["incident_id"] != bundle["incident_id"] or event["tenant_id"] != "UNKNOWN"
           or event["evidence_id"] != _id(bundle["scenario"], event["source_ref"])
           or event["source_dataset"] != "PDS-01"
           for event in events):
        raise ValueError("cross_incident_or_tenant_event")
    for name in ("pairs.jsonl", "facts.jsonl"):
        for line in (directory / name).read_bytes().splitlines():
            row = json.loads(line)
            if (row["incident_id"] != bundle["incident_id"]
                    or row["tenant_id"] != "UNKNOWN"
                    or not set(row["evidence_ids"]) <= ids
                    or row["evidence_ids"] != [by_ref.get(row.get("source_ref"))]
                    or row.get("gold_status") != "NOT_GOLD"):
                raise ValueError("cross_incident_or_gold_annotation")
    return bundle, events
