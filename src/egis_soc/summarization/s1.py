"""Synthetic S1 display packet: original draft, scoped evidence, and separate citation checks.

Semantic relevance/support are explicit review inputs, never inferred from an ID,
keyword overlap, or the generator. This module does not call V3 or repair text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from egis_soc.integrity import canonical_bytes

from .contract import RetrievedIncident, SyntheticDraft
from .atomization import verify_claim_archive
from .generation import GenerationConfig


VERSION = "w5-03-synthetic-s1-1"
STATUS = "S1_DRAFT_NOT_VERIFIED_NOT_GOLD"
SECTIONS = ("timeline", "affected_entities", "observed_behaviors",
            "confirmed_outcomes", "uncertainties")
_MARKER = re.compile(r"\[([^\[\]]+)\]")


@dataclass(frozen=True)
class CitationAudit:
    """Optional, explicit development review of each citation and the cited set."""

    claim_id: str
    reviewer_id: str
    rationale: str
    relevance: tuple[str, ...]  # one judgment per emitted ID occurrence
    cited_set_support: str  # semantic judgment of the combination, not each ID

    def __post_init__(self) -> None:
        if (not all(isinstance(value, str) and value.strip() == value and value
                    for value in (self.claim_id, self.reviewer_id, self.rationale))
                or type(self.relevance) is not tuple
                or any(value not in {"relevant", "irrelevant", "not_assessed"}
                       for value in self.relevance)
                or self.cited_set_support not in
                {"supported", "contradicted", "insufficient", "not_assessed"}):
            raise ValueError("invalid_s1_citation_audit")


@dataclass(frozen=True)
class S1Evidence:
    evidence_id: str
    incident_id: str
    tenant_id: str
    passage: str
    raw_message: str
    raw_message_ref: str
    raw_sha256: str
    source: str
    timestamp_utc: str


@dataclass(frozen=True)
class S1Citation:
    evidence_id: str
    marker_start: int
    marker_end: int
    valid_in_scope: bool
    relevance: str
    evidence_ref: str | None


@dataclass(frozen=True)
class S1Claim:
    claim_id: str
    text: str
    span_start: int
    span_end: int
    section: str
    claim_type: str
    citations: tuple[S1Citation, ...]
    cited_set_support: str
    review_reasons: tuple[str, ...]
    audit_reviewer_id: str | None
    audit_rationale: str | None


@dataclass(frozen=True)
class S1Report:
    incident_id: str
    tenant_id: str
    draft_id: str
    draft_sha256: str
    original_draft_text: str
    incident_overview: str
    retrieved_evidence_ids: tuple[str, ...]
    evidence: tuple[S1Evidence, ...]
    timeline: tuple[str, ...]
    affected_entities: tuple[str, ...]
    observed_behaviors: tuple[str, ...]
    confirmed_outcomes: tuple[str, ...]
    uncertainties: tuple[str, ...]
    claims: tuple[S1Claim, ...]
    analyst_notes: tuple[str, ...]
    verification_status: str = "NOT_RUN_S1"
    status: str = STATUS
    version: str = VERSION

    def __post_init__(self) -> None:
        if (self.version != VERSION or self.status != STATUS
                or self.verification_status != "NOT_RUN_S1"
                or self.incident_overview != self.original_draft_text
                or type(self.evidence) is not tuple or type(self.claims) is not tuple
                or type(self.analyst_notes) is not tuple
                or self.analyst_notes
                or tuple(item.evidence_id for item in self.evidence)
                != self.retrieved_evidence_ids):
            raise ValueError("invalid_s1_report")
        by_id = {claim.claim_id: claim for claim in self.claims}
        if len(by_id) != len(self.claims):
            raise ValueError("duplicate_s1_claim")
        for section in SECTIONS:
            ids = getattr(self, section)
            if (type(ids) is not tuple or len(ids) != len(set(ids))
                    or any(item not in by_id or by_id[item].section != section
                           for item in ids)):
                raise ValueError("invalid_s1_section")
        if {item for section in SECTIONS for item in getattr(self, section)} != {
                claim.claim_id for claim in self.claims
                if claim.section != "unclassified"}:
            raise ValueError("missing_s1_section_claim")
        for claim in self.claims:
            if (claim.section not in (*SECTIONS, "unclassified")
                    or self.original_draft_text[claim.span_start:claim.span_end]
                    != claim.text):
                raise ValueError("invalid_s1_claim_span")

    def to_record(self) -> dict:
        """JSON-compatible, versioned record for an offline round trip."""
        return json.loads(canonical_bytes(asdict(self)))

    @classmethod
    def from_record(cls, record: dict) -> S1Report:
        if type(record) is not dict:
            raise ValueError("invalid_s1_record")
        try:
            values = dict(record)
            values["retrieved_evidence_ids"] = tuple(values["retrieved_evidence_ids"])
            values["evidence"] = tuple(S1Evidence(**item) for item in values["evidence"])
            values["claims"] = tuple(S1Claim(
                **{**item,
                   "citations": tuple(S1Citation(**citation)
                                      for citation in item["citations"]),
                   "review_reasons": tuple(item["review_reasons"])})
                for item in values["claims"])
            for section in (*SECTIONS, "analyst_notes"):
                values[section] = tuple(values[section])
            report = cls(**values)
            if report.to_record() != record:
                raise ValueError("invalid_s1_record")
            return report
        except (KeyError, TypeError, AttributeError, ValueError):
            raise ValueError("invalid_s1_record") from None


def render_s1(context: RetrievedIncident, draft: SyntheticDraft, *,
              sections: Mapping[str, str] | None = None,
              citation_audits: tuple[CitationAudit, ...] = ()) -> S1Report:
    """Render without changing draft bytes or making an automated support verdict.

    Section placement and semantic judgments are explicit inputs. An unknown
    citation remains visible as invalid and is never resolved outside the fixed
    retrieval set. All generated claims remain reviewable even with an audit.
    """
    if (not isinstance(context, RetrievedIncident)
            or not isinstance(draft, SyntheticDraft)
            or draft.source_kind != "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD"
            or draft.incident_id != context.bundle.incident_id
            or draft.tenant_id != context.bundle.tenant_id
            or draft.retrieved_evidence_ids != context.evidence_ids
            or type(citation_audits) is not tuple):
        raise ValueError("s1_scope_or_source_mismatch")
    placement = dict(sections or {})
    claim_ids = {claim.claim_id for claim in draft.claims}
    if (not set(placement) <= claim_ids
            or any(value not in SECTIONS for value in placement.values())):
        raise ValueError("invalid_s1_section_assignment")
    audits = {audit.claim_id: audit for audit in citation_audits
              if isinstance(audit, CitationAudit)}
    if (len(audits) != len(citation_audits)
            or not set(audits) <= claim_ids):
        raise ValueError("invalid_s1_citation_audit_set")
    fixed = set(context.evidence_ids)
    refs = {event.evidence_id: event.provenance.raw_message_ref
            for event in context.events}
    rendered = []
    for claim in draft.claims:
        if claim.evidence_ids != context.evidence_ids:
            raise ValueError("s1_claim_evidence_set_mismatch")
        occurrences = []
        for start, end in claim.citation_marker_spans:
            marker = draft.text[start:end]
            match = _MARKER.fullmatch(marker)
            if match is None:
                raise ValueError("s1_citation_marker_mismatch")
            occurrences.extend((part.strip(), start, end)
                               for part in match.group(1).split(","))
        parsed = tuple(item[0] for item in occurrences)
        if parsed != claim.citation_ids:
            raise ValueError("s1_citation_marker_mismatch")
        audit = audits.get(claim.claim_id)
        if audit is not None:
            if (len(audit.relevance) != len(parsed) or not parsed
                    or (audit.cited_set_support == "supported"
                        and (any(item not in fixed for item in parsed)
                             or any(value != "relevant"
                                    for value in audit.relevance)))):
                raise ValueError("invalid_s1_supported_citation_audit")
        citations = []
        for index, (evidence_id, start, end) in enumerate(occurrences):
            # A multi-ID marker has one source span shared by its occurrences.
            citations.append(S1Citation(
                evidence_id, start, end, evidence_id in fixed,
                audit.relevance[index] if audit else "not_assessed",
                refs[evidence_id] if evidence_id in fixed else None))
        reasons = list(claim.review_reasons)
        if not parsed:
            reasons.append("MISSING_CITATION")
        if any(item.evidence_id not in fixed for item in citations):
            reasons.append("INVALID_CITATION")
        if len(parsed) != len(set(parsed)):
            reasons.append("DUPLICATE_CITATION")
        if audit is None or audit.cited_set_support == "not_assessed":
            reasons.append("CITED_SUPPORT_NOT_ASSESSED")
        if audit is None or any(value == "not_assessed" for value in audit.relevance):
            reasons.append("CITATION_RELEVANCE_NOT_ASSESSED")
        if audit and "irrelevant" in audit.relevance:
            reasons.append("IRRELEVANT_CITATION")
        if audit and audit.cited_set_support in {"insufficient", "contradicted"}:
            reasons.append("CITED_SET_NOT_SUPPORTED")
        rendered.append(S1Claim(
            claim.claim_id, claim.text, claim.span_start, claim.span_end,
            placement.get(claim.claim_id, "unclassified"), claim.claim_type,
            tuple(citations), audit.cited_set_support if audit else "not_assessed",
            tuple(dict.fromkeys(reasons)), audit.reviewer_id if audit else None,
            audit.rationale if audit else None))
    by_event = {event.evidence_id: event for event in context.events}
    evidence = tuple(S1Evidence(
        hit.evidence_id, hit.incident_id, hit.tenant_id, hit.passage,
        by_event[hit.evidence_id].provenance.raw_message,
        hit.source_ref, by_event[hit.evidence_id].provenance.sha256,
        by_event[hit.evidence_id].provenance.source,
        hit.timestamp_utc) for hit in context.hits)
    return S1Report(
        draft.incident_id, draft.tenant_id, draft.draft_id, draft.sha256,
        draft.text, draft.text, context.evidence_ids, evidence,
        *(tuple(claim.claim_id for claim in rendered if claim.section == section)
          for section in SECTIONS), tuple(rendered), ())


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _archive_bytes(context: RetrievedIncident, config: GenerationConfig,
                   source_draft: Path, source_claims: Path) -> tuple[bytes, bytes]:
    result = verify_claim_archive(context, config, source_draft, source_claims)
    report = render_s1(context, result.draft)
    raw = canonical_bytes(report.to_record())
    manifest = {"version": VERSION, "status": STATUS,
                "report_sha256": _sha(raw), "draft_sha256": report.draft_sha256,
                "source_w5_01_manifest_sha256": _sha((source_draft / "manifest.json").read_bytes()),
                "source_w5_02_manifest_sha256": _sha((source_claims / "manifest.json").read_bytes()),
                "s1_code_sha256": _sha(Path(__file__).read_bytes()),
                "verification_status": "NOT_RUN_S1", "gold_status": "NOT_GOLD"}
    return raw, canonical_bytes(manifest)


def create_s1_archive(context: RetrievedIncident, config: GenerationConfig,
                      source_draft: Path, source_claims: Path,
                      target: Path) -> S1Report:
    """Create-only offline S1 packet bound to verified W5-01/02 archives."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w5_03_s1_archive_already_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w5_03_archive_parent_required")
    raw, manifest = _archive_bytes(context, config, Path(source_draft),
                                   Path(source_claims))
    target.mkdir(exist_ok=False)
    for name, data in (("report.json", raw), ("manifest.json", manifest)):
        with (target / name).open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return S1Report.from_record(json.loads(raw))


def verify_s1_archive(context: RetrievedIncident, config: GenerationConfig,
                      source_draft: Path, source_claims: Path,
                      target: Path) -> S1Report:
    """Check exact report/manifest bytes without a model or verifier call."""
    target = Path(target)
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()}
            != {"report.json", "manifest.json"}
            or any((target / name).is_symlink() for name in
                   ("report.json", "manifest.json"))):
        raise ValueError("invalid_w5_03_archive_file_set")
    raw, manifest = _archive_bytes(context, config, Path(source_draft),
                                   Path(source_claims))
    if ((target / "report.json").read_bytes() != raw
            or (target / "manifest.json").read_bytes() != manifest):
        raise ValueError("w5_03_s1_archive_drift")
    return S1Report.from_record(json.loads(raw))
