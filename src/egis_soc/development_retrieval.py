"""W3 development-only structured retrieval followed by deterministic BM25."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .development_data import DevelopmentData, PDS01_MANIFEST_SHA256


VERSION = "w3-development-bm25-1"
K1 = 1.2
B = 0.75
_TOKEN = re.compile(r"[^\W_]+(?:_[^\W_]+)*", re.UNICODE)
_SEARCH_FIELDS = ("provider", "channel", "host", "event_id")
_PROVENANCE_FIELDS = (
    "source_dataset", "source_ref", "source_key", "repository_path",
    "artifact_sha256", "raw_sha256", "ordinal", "byte_offset", "byte_length",
    "raw_message_ref", "timestamp_original", "timestamp_utc", "provider", "channel",
    "event_record_id",
)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(value.casefold()))


def _passage(event: Mapping[str, Any]) -> str:
    """Serialize only permitted normalized fields; content remains untrusted data."""
    parts = [f"{field}: {event[field]}" for field in _SEARCH_FIELDS
             if isinstance(event.get(field), (str, int)) and str(event[field]).strip()]
    fields = event["event_data"]
    for name in sorted(fields):
        value = fields[name]
        if type(value) in (str, int, float) and str(value).strip():
            parts.append(f"{name}: {value}")
    return "\n".join(parts)


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name}_requires_timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RetrievalHit:
    evidence_id: str
    score: float
    incident_id: str
    tenant_id: str
    source_ref: str
    timestamp_utc: str
    passage: str  # Untrusted normalized event text; never operational instructions.
    provenance: Mapping[str, Any]


class DevelopmentRetriever:
    """One gated incident corpus; scope and structured filters precede scoring."""

    def __init__(self, data: DevelopmentData):
        if data.source_dataset == "PDS-01":
            valid = (data.partition == "train_designated_grouped"
                     and data.lineage_group == "PDS01_ALL"
                     and data.tenant_id == "UNKNOWN"
                     and data.manifest_sha256 == PDS01_MANIFEST_SHA256)
        elif data.source_dataset == "synthetic":
            valid = (data.partition == "train" and data.lineage_group == "SYNTHETIC"
                     and data.manifest_sha256 is None)
        else:
            valid = False
        if not valid or not data.incident_id or not data.tenant_id:
            raise ValueError("retrieval_input_not_train_development")
        seen: set[str] = set()
        for event in data.events:
            evidence_id = event.get("evidence_id")
            if (not isinstance(evidence_id, str) or not evidence_id
                    or evidence_id in seen
                    or event.get("incident_id") != data.incident_id
                    or event.get("tenant_id") != data.tenant_id
                    or not isinstance(event.get("source_ref"), str)
                    or not event["source_ref"]
                    or not isinstance(event.get("timestamp_utc"), str)
                    or not isinstance(event.get("event_data"), Mapping)):
                raise ValueError("invalid_retrieval_event_scope_or_provenance")
            seen.add(evidence_id)
        self._data = data

    def search(self, query: str, *, incident_id: str, tenant_id: str, limit: int = 10,
               start_utc: datetime | None = None, end_utc: datetime | None = None,
               source_key: str | None = None, source_ref: str | None = None,
               host: str | None = None) -> tuple[RetrievalHit, ...]:
        """Filter first, then score only matching events; ties use evidence ID."""
        if incident_id != self._data.incident_id or tenant_id != self._data.tenant_id:
            raise PermissionError("foreign_incident_or_tenant")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit_must_be_positive_integer")
        if not isinstance(query, str):
            raise TypeError("query_must_be_text")
        start = _utc(start_utc, "start") if start_utc is not None else None
        end = _utc(end_utc, "end") if end_utc is not None else None
        if start is not None and end is not None and start > end:
            raise ValueError("reversed_time_range")
        terms = tuple(sorted(set(_tokens(query))))
        if not terms:
            return ()
        candidates: list[tuple[Mapping[str, Any], str, Counter[str], int]] = []
        document_frequency = Counter[str]()
        for event in self._data.events:
            if source_key is not None and event.get("source_key") != source_key:
                continue
            if source_ref is not None and event["source_ref"] != source_ref:
                continue
            event_host = event.get("host", event["event_data"].get("host"))
            if host is not None and (not isinstance(event_host, str)
                                     or event_host.casefold() != host.casefold()):
                continue
            if start is not None or end is not None:
                stamp = datetime.fromisoformat(event["timestamp_utc"])
                stamp = _utc(stamp, "event_timestamp")
                if start is not None and stamp < start or end is not None and stamp > end:
                    continue
            passage = _passage(event)
            tokens = _tokens(passage)
            counts = Counter(tokens)
            candidates.append((event, passage, counts, len(tokens)))
            document_frequency.update(term for term in terms if term in counts)
        if not candidates:
            return ()
        count = len(candidates)
        average_length = sum(length for _, _, _, length in candidates) / count
        if average_length == 0:
            return ()
        idf = {term: math.log1p((count - document_frequency[term] + 0.5)
                                / (document_frequency[term] + 0.5)) for term in terms}
        hits: list[RetrievalHit] = []
        for event, passage, frequencies, length in candidates:
            score = sum(
                idf[term] * frequencies[term] * (K1 + 1)
                / (frequencies[term] + K1 * (1 - B + B * length / average_length))
                for term in terms if frequencies[term]
            )
            if score <= 0:
                continue
            hits.append(RetrievalHit(
                evidence_id=event["evidence_id"], score=score,
                incident_id=self._data.incident_id, tenant_id=self._data.tenant_id,
                source_ref=event["source_ref"], timestamp_utc=event["timestamp_utc"],
                passage=passage, provenance=MappingProxyType({
                    name: event[name] for name in _PROVENANCE_FIELDS if name in event
                })))
        hits.sort(key=lambda hit: (-hit.score, hit.evidence_id))
        return tuple(hits[:limit])
