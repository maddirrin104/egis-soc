"""W5-05 synthetic, source-derived S3 inventory and conservative omission screen.

This is an inference-time review aid. It does not construct evaluation gold,
decide criticality, or modify the archived S2 fork.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from egis_soc.integrity import canonical_bytes

from .contract import RetrievedIncident
from .generation import GenerationConfig
from .s2 import ReviewBatch, verify_s2_archive


VERSION = "w5-05-synthetic-operational-inventory-1"
MATCH_POLICY = "w5-05-exact-observed-logon-v1"
STATUS = "SYNTHETIC_OPERATIONAL_CANDIDATES_NOT_GOLD"
FILES = ("inventory.json", "omission.json", "manifest.json")
_FIELDS = frozenset({"record_ref", "event_type", "actor", "host", "outcome"})
_TOKEN = re.compile(r"[A-Za-z0-9_.:@/-]{1,128}\Z")
_STRUCTURED = re.compile(
    r"record=([A-Za-z0-9_.:@/-]+); event=logon; "
    r"actor=([A-Za-z0-9_.:@/-]+); host=([A-Za-z0-9_.:@/-]+); "
    r"time=([0-9T:+.Z-]+); outcome=(success|failure)\Z"
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _value(raw: object) -> str | None:
    return raw if type(raw) is str and _TOKEN.fullmatch(raw) else None


def _retrieval_record(context: RetrievedIncident) -> dict:
    by_id = {event.evidence_id: event for event in context.events}
    return {
        "incident_id": context.bundle.incident_id,
        "tenant_id": context.bundle.tenant_id,
        "query": context.query,
        "evidence": [{"evidence_id": hit.evidence_id,
                      "passage": hit.passage, "source_ref": hit.source_ref,
                      "timestamp_utc": hit.timestamp_utc,
                      "raw_sha256": by_id[hit.evidence_id].provenance.sha256}
                     for hit in context.hits],
    }


def build_operational_inventory(context: RetrievedIncident) -> dict:
    """Project only known fields from fixed retrieved W1 events, never draft text."""
    if type(context) is not RetrievedIncident:
        raise TypeError("w5_05_requires_scoped_retrieved_incident")
    events = {event.evidence_id: event for event in context.events}
    facts = []
    for hit in context.hits:
        event = events[hit.evidence_id]
        fields = event.normalized_fields
        values = {name: _value(fields.get(name)) for name in _FIELDS}
        issues = ["MISSING_OR_UNSUPPORTED_" + name.upper() for name in
                  sorted(_FIELDS) if values[name] is None]
        if set(fields) - _FIELDS:
            issues.append("UNREVIEWED_SOURCE_FIELDS")
        if values["event_type"] != "logon":
            issues.append("EVENT_SCHEMA_NOT_COVERED")
        if values["outcome"] not in {"success", "failure"}:
            issues.append("OUTCOME_NOT_COVERED")
        if hit.timestamp_utc != event.provenance.timestamp_utc.isoformat():
            raise ValueError("w5_05_timestamp_provenance_drift")
        stamp = hit.timestamp_utc
        identity = {"incident_id": context.bundle.incident_id,
                    "tenant_id": context.bundle.tenant_id,
                    "evidence_id": hit.evidence_id,
                    "raw_sha256": event.provenance.sha256,
                    "projection": values, "timestamp_utc": stamp}
        fact_id = "W5OF-" + _sha(canonical_bytes(identity))[:20]
        statement = None
        if not issues:
            statement = (f"record={values['record_ref']}; event=logon; "
                         f"actor={values['actor']}; host={values['host']}; "
                         f"time={stamp}; outcome={values['outcome']}")
        facts.append({
            "fact_id": fact_id,
            "statement": statement,
            "source_attributes": values,
            "incident_id": context.bundle.incident_id,
            "tenant_id": context.bundle.tenant_id,
            "evidence_ids": [hit.evidence_id],
            "observability": "observable" if not issues else "unresolved",
            "uncertainty": issues,
            "criticality": "not_adjudicated",
            "support_status": "source_recorded_not_adjudicated",
            "provenance": {"evidence_id": hit.evidence_id,
                           "source": event.provenance.source,
                           "source_ref": hit.source_ref,
                           "raw_sha256": event.provenance.sha256,
                           "timestamp_utc": stamp},
        })
    # Reused source record numbers can refer to inconsistent or duplicate
    # records. Neither case is automatically eligible for an omission claim.
    by_record: dict[tuple[str, str], list[dict]] = {}
    for fact in facts:
        record = fact["source_attributes"]["record_ref"]
        if record is not None:
            by_record.setdefault((fact["provenance"]["source"], record), []).append(fact)
    for group in by_record.values():
        if len(group) > 1:
            reason = ("DUPLICATE_SOURCE_RECORD" if len({
                canonical_bytes((item["source_attributes"],
                                 item["provenance"]["timestamp_utc"]))
                for item in group}) == 1 else "CONFLICTING_SOURCE_RECORD")
            for fact in group:
                fact["observability"] = "unresolved"
                fact["statement"] = None
                fact["uncertainty"].append(reason)
    if len({fact["fact_id"] for fact in facts}) != len(facts):
        raise ValueError("w5_05_duplicate_fact_identity")
    return {"version": VERSION, "status": STATUS,
            "incident_id": context.bundle.incident_id,
            "tenant_id": context.bundle.tenant_id,
            "retrieval_sha256": _sha(canonical_bytes(_retrieval_record(context))),
            "source_evidence_ids": list(context.evidence_ids),
            "facts": facts, "gold_status": "NOT_GOLD"}


def _match(fact: dict, claim: dict) -> dict:
    claim_id = claim["claim_id"]
    text = claim["text"]
    parsed = _STRUCTURED.fullmatch(text)
    if parsed is None:
        return {"claim_id": claim_id, "result": "ambiguous",
                "reason": "UNPARSEABLE_CLAIM_REQUIRES_SEMANTIC_REVIEW"}
    record, actor, host, stamp, outcome = parsed.groups()
    source = fact["source_attributes"]
    if record != source["record_ref"]:
        return {"claim_id": claim_id, "result": "unrelated",
                "reason": "DIFFERENT_SOURCE_RECORD"}
    if (actor, host, stamp, outcome) == (
            source["actor"], source["host"],
            fact["provenance"]["timestamp_utc"], source["outcome"]):
        return {"claim_id": claim_id, "result": "exact_match",
                "reason": "ALL_OBSERVED_ATTRIBUTES_MATCH"}
    return {"claim_id": claim_id, "result": "conflict",
            "reason": "SOURCE_RECORD_ATTRIBUTES_DIFFER"}


def check_operational_omissions(context: RetrievedIncident, s2_report: dict,
                                fork_bytes: bytes) -> tuple[dict, dict]:
    """Screen the verified S2 state; never infer a CFR or confirmed omission."""
    inventory = build_operational_inventory(context)
    if type(s2_report) is not dict or type(fork_bytes) is not bytes:
        raise TypeError("w5_05_requires_verified_s2_inputs")
    try:
        fork = json.loads(fork_bytes)
        claims = s2_report["final_claims"]
        if (type(fork) is not dict or type(claims) is not list
                or fork["incident_id"] != inventory["incident_id"]
                or fork["tenant_id"] != inventory["tenant_id"]
                or fork["retrieval_sha256"] != inventory["retrieval_sha256"]
                or fork["s2_report_sha256"] != _sha(canonical_bytes(s2_report))
                or fork["operational_inventory_status"] != "NOT_ACCESSED_S2"
                or s2_report["incident_id"] != inventory["incident_id"]
                or s2_report["tenant_id"] != inventory["tenant_id"]
                or s2_report["retrieved_evidence_ids"] != inventory["source_evidence_ids"]
                or any(type(claim) is not dict or
                       set(claim) != {"claim_id", "source_claim_id", "text",
                                      "citation_ids", "evidence_ids", "prediction",
                                      "review_required"} or
                       claim["prediction"] != "supported" or
                       claim["review_required"] is not False or
                       type(claim["claim_id"]) is not str or
                       type(claim["text"]) is not str for claim in claims)):
            raise ValueError("w5_05_s2_fork_mismatch")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("w5_05_s2_fork_mismatch") from None
    findings = []
    for fact in inventory["facts"]:
        trace = [] if fact["observability"] != "observable" else [
            _match(fact, claim) for claim in claims]
        kinds = {item["result"] for item in trace}
        if fact["observability"] != "observable":
            outcome, reason = "unknown", "SOURCE_UNOBSERVABLE_OR_CONFLICTING"
        elif "conflict" in kinds:
            outcome, reason = "unknown", "S2_SOURCE_ATTRIBUTE_CONFLICT"
        elif "exact_match" in kinds:
            outcome, reason = "covered", "EXACT_SOURCE_ATTRIBUTES_IN_S2"
        elif "ambiguous" in kinds:
            outcome, reason = "unknown", "SEMANTIC_MATCH_REVIEW_REQUIRED"
        else:
            outcome, reason = "candidate_unmentioned", "NO_S2_MENTION"
        findings.append({"fact_id": fact["fact_id"], "outcome": outcome,
                         "reason": reason, "review_required": outcome != "covered",
                         "match_trace": trace})
    report = {"version": VERSION, "status": STATUS,
              "match_policy": MATCH_POLICY,
              "incident_id": inventory["incident_id"],
              "tenant_id": inventory["tenant_id"],
              "fork_sha256": _sha(fork_bytes),
              "inventory_sha256": _sha(canonical_bytes(inventory)),
              "findings": findings,
              "criticality_status": "NOT_ADJUDICATED",
              "cfr_status": "NOT_SCORED",
              "gold_status": "NOT_GOLD"}
    return inventory, report


def _expected(context: RetrievedIncident, config: GenerationConfig,
              source_draft: Path, source_claims: Path, source_s1: Path,
              review: ReviewBatch, backend_binding: dict[str, str],
              source_s2: Path) -> dict[str, bytes]:
    report = verify_s2_archive(context, config, source_draft, source_claims,
                               source_s1, review, backend_binding, source_s2)
    fork = (source_s2 / "fork.json").read_bytes()
    inventory, omission = check_operational_omissions(context, report, fork)
    records = {"inventory.json": canonical_bytes(inventory),
               "omission.json": canonical_bytes(omission)}
    manifest = {"version": VERSION, "status": STATUS,
                "source_s2_manifest_sha256": _sha((source_s2 / "manifest.json").read_bytes()),
                "source_fork_sha256": _sha(fork),
                "output_sha256": {name: _sha(raw) for name, raw in records.items()},
                "code_sha256": _sha(Path(__file__).read_bytes()),
                "match_policy": MATCH_POLICY,
                "gold_status": "NOT_GOLD",
                "research_result": "NOT_RUN_SYNTHETIC_DEVELOPMENT_ONLY"}
    records["manifest.json"] = canonical_bytes(manifest)
    return records


def create_omission_archive(context: RetrievedIncident, config: GenerationConfig,
                            source_draft: Path, source_claims: Path,
                            source_s1: Path, review: ReviewBatch,
                            backend_binding: dict[str, str], source_s2: Path,
                            target: Path) -> dict:
    """Create a separate, hash-bound S3 input without writing to the S2 fork."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w5_05_archive_already_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w5_05_archive_parent_required")
    records = _expected(context, config, Path(source_draft), Path(source_claims),
                        Path(source_s1), review, backend_binding, Path(source_s2))
    target.mkdir(exist_ok=False)
    for name, raw in records.items():
        with (target / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return json.loads(records["omission.json"])


def verify_omission_archive(context: RetrievedIncident, config: GenerationConfig,
                            source_draft: Path, source_claims: Path,
                            source_s1: Path, review: ReviewBatch,
                            backend_binding: dict[str, str], source_s2: Path,
                            target: Path) -> dict:
    """Offline exact-byte and parent-fork verification; no generator or NLI call."""
    target = Path(target)
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} != set(FILES)
            or any((target / name).is_symlink() or not (target / name).is_file()
                   for name in FILES)):
        raise ValueError("invalid_w5_05_archive_file_set")
    expected = _expected(context, config, Path(source_draft), Path(source_claims),
                         Path(source_s1), review, backend_binding, Path(source_s2))
    if any((target / name).read_bytes() != raw for name, raw in expected.items()):
        raise ValueError("w5_05_archive_drift")
    return json.loads(expected["omission.json"])
