"""W5-00 synthetic retrieval, draft and V3 handoff without evaluation gold.

The draft is supplied by an independent authored fixture. No LLM, omission
detector, repairer, final report, or research-data admission lives here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from egis_soc.development.contract import CitationCheck, RuleTrace, VerifierInput, VerifierOutput
from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_data import DevelopmentData, from_synthetic_fixture
from egis_soc.development_retrieval import DevelopmentRetriever, RetrievalHit, _passage
from egis_soc.development_v2 import NLIPair
from egis_soc.integrity import canonical_bytes
from egis_soc.schemas import EvidenceEvent, IncidentBundle


VERSION = "w5-00-synthetic-contract-1"
STATUS = "SYNTHETIC_DRAFT_VERIFICATION_NOT_FINAL"
_DENIED_KEYS = frozenset({
    "expected", "label", "gold_status", "support_status", "annotation_source",
    "annotation_record_id", "human_label", "human_status", "prediction",
    "verifier_output", "review_required", "split_id", "evaluation_gold",
})


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _check_no_evaluation_fields(value: object) -> None:
    """Reject structured gold/verifier fields before retrieval or draft creation."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("invalid_synthetic_event_field")
            name = key.casefold()
            if (name in _DENIED_KEYS or "gold" in name or name.startswith("human_")
                    or name.startswith("annotation_") or name.startswith("verifier_")):
                raise ValueError("evaluation_field_in_inference_evidence")
            _check_no_evaluation_fields(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _check_no_evaluation_fields(item)


@dataclass(frozen=True)
class RetrievedIncident:
    """One scoped W1 bundle, its W3 view, and ordered W3 retrieval hits."""

    bundle: IncidentBundle
    data: DevelopmentData
    events: tuple[EvidenceEvent, ...]
    query: str
    hits: tuple[RetrievalHit, ...]

    def __post_init__(self) -> None:
        if (type(self.bundle) is not IncidentBundle
                or not isinstance(self.data, DevelopmentData)
                or type(self.events) is not tuple or not self.events
                or type(self.hits) is not tuple or not self.hits
                or not isinstance(self.query, str) or not self.query.strip()):
            raise ValueError("invalid_retrieved_incident")
        if (self.bundle.incident_id != self.data.incident_id
                or self.bundle.tenant_id != self.data.tenant_id
                or self.bundle.source_dataset != "synthetic"
                or self.bundle.environment_id != "SYNTHETIC"
                or self.data.source_dataset != "synthetic"
                or self.data.partition != "train"):
            raise ValueError("retrieval_outside_synthetic_train")
        if self.data != from_synthetic_fixture(self.bundle, self.events):
            raise ValueError("retrieval_view_differs_from_w1_evidence")
        source_by_id = {event.evidence_id: event for event in self.events}
        if (len(source_by_id) != len(self.events)
                or tuple(source_by_id) != self.bundle.evidence_ids
                or len({hit.evidence_id for hit in self.hits}) != len(self.hits)):
            raise ValueError("retrieval_evidence_identity_mismatch")
        DevelopmentRetriever(self.data)
        for event in self.events:
            self.bundle.check_scope(event)
            _check_no_evaluation_fields(event.normalized_fields)
        for hit in self.hits:
            source = source_by_id.get(hit.evidence_id)
            resolved = self.data.resolve(hit.evidence_id,
                                         incident_id=self.bundle.incident_id,
                                         tenant_id=self.bundle.tenant_id)
            if (source is None or hit.incident_id != self.bundle.incident_id
                    or hit.tenant_id != self.bundle.tenant_id
                    or hit.source_ref != source.provenance.raw_message_ref
                    or hit.passage != _passage(resolved)
                    or hit.timestamp_utc != resolved["timestamp_utc"]
                    or hit.provenance.get("raw_sha256") != source.provenance.sha256
                    or hit.provenance.get("raw_message_ref") != source.provenance.raw_message_ref
                    or resolved["raw_sha256"] != source.provenance.sha256):
                raise ValueError("retrieval_provenance_or_scope_mismatch")

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(hit.evidence_id for hit in self.hits)


def retrieve_synthetic_incident(bundle: IncidentBundle,
                                events: Sequence[EvidenceEvent], *,
                                query: str, limit: int = 10) -> RetrievedIncident:
    """Validate W1 input anew; derive a scoped W3 view without gold access."""
    if (type(bundle) is not IncidentBundle or type(events) not in (tuple, list)
            or any(type(event) is not EvidenceEvent for event in events)):
        raise ValueError("w5_requires_w1_synthetic_incident_and_events")
    # Re-parse instead of trusting model_construct or caller-created subclasses.
    checked_bundle = IncidentBundle.model_validate(bundle.model_dump(mode="python"))
    checked_events = tuple(EvidenceEvent.model_validate(event.model_dump(mode="python"))
                           for event in events)
    for event in checked_events:
        _check_no_evaluation_fields(event.normalized_fields)
    data = from_synthetic_fixture(checked_bundle, checked_events)
    hits = DevelopmentRetriever(data).search(
        query, incident_id=checked_bundle.incident_id,
        tenant_id=checked_bundle.tenant_id, limit=limit)
    if not hits:
        raise ValueError("no_retrieved_evidence")
    return RetrievedIncident(checked_bundle, data, checked_events, query, hits)


@dataclass(frozen=True)
class AtomicDraftClaim:
    claim_id: str
    text: str
    span_start: int
    span_end: int
    evidence_ids: tuple[str, ...]
    citation_ids: tuple[str, ...] = ()
    claim_type: str = "factual_candidate"
    review_reasons: tuple[str, ...] = ()
    citation_marker_spans: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if (not _identifier(self.claim_id) or not isinstance(self.text, str)
                or not self.text.strip() or self.text != self.text.strip()
                or type(self.span_start) is not int or type(self.span_end) is not int
                or self.span_start < 0 or self.span_end <= self.span_start
                or type(self.evidence_ids) is not tuple or not self.evidence_ids
                or type(self.citation_ids) is not tuple
                or self.claim_type != "factual_candidate"
                or type(self.review_reasons) is not tuple
                or len(set(self.review_reasons)) != len(self.review_reasons)
                or any(not _identifier(reason) for reason in self.review_reasons)
                or type(self.citation_marker_spans) is not tuple
                or any(not _identifier(item) for item in
                       (*self.evidence_ids, *self.citation_ids))
                or len(set(self.evidence_ids)) != len(self.evidence_ids)
                or len(set(self.citation_ids)) != len(self.citation_ids)):
            raise ValueError("invalid_atomic_draft_claim")
        previous_end = self.span_end
        for marker in self.citation_marker_spans:
            if (type(marker) is not tuple or len(marker) != 2
                    or any(type(value) is not int for value in marker)
                    or marker[0] < previous_end or marker[1] <= marker[0]):
                raise ValueError("invalid_citation_marker_span")
            previous_end = marker[1]


@dataclass(frozen=True)
class SyntheticDraft:
    draft_id: str
    incident_id: str
    tenant_id: str
    text: str
    retrieved_evidence_ids: tuple[str, ...]
    claims: tuple[AtomicDraftClaim, ...]
    generator_id: str = "authored-synthetic-fixture-v1"
    version: str = VERSION
    source_kind: str = "SYNTHETIC_AUTHORED_NOT_GOLD"

    def __post_init__(self) -> None:
        if (any(not _identifier(item) for item in
                (self.draft_id, self.incident_id, self.tenant_id, self.generator_id))
                or not isinstance(self.text, str) or not self.text.strip()
                or type(self.retrieved_evidence_ids) is not tuple
                or not self.retrieved_evidence_ids
                or any(not _identifier(item) for item in self.retrieved_evidence_ids)
                or len(set(self.retrieved_evidence_ids)) != len(self.retrieved_evidence_ids)
                or type(self.claims) is not tuple or not self.claims
                or self.version != VERSION
                or self.source_kind not in {
                    "SYNTHETIC_AUTHORED_NOT_GOLD",
                    "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD"}):
            raise ValueError("invalid_synthetic_draft")
        seen: set[str] = set()
        previous_end = 0
        for claim in self.claims:
            if (not isinstance(claim, AtomicDraftClaim) or claim.claim_id in seen
                    or claim.span_start < previous_end
                    or self.text[claim.span_start:claim.span_end] != claim.text
                    or (self.source_kind == "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD"
                        and claim.citation_ids and not claim.citation_marker_spans)):
                raise ValueError("invalid_draft_claim_span_or_identity")
            for start, end in claim.citation_marker_spans:
                if (end > len(self.text) or not self.text[start:end].startswith("[")
                        or not self.text[start:end].endswith("]")):
                    raise ValueError("citation_marker_not_in_source_draft")
            seen.add(claim.claim_id)
            previous_end = (claim.citation_marker_spans[-1][1]
                            if claim.citation_marker_spans else claim.span_end)

    @property
    def sha256(self) -> str:
        record = {
            "version": self.version, "draft_id": self.draft_id,
            "incident_id": self.incident_id, "tenant_id": self.tenant_id,
            "text": self.text, "retrieved_evidence_ids": self.retrieved_evidence_ids,
            "generator_id": self.generator_id,
            "source_kind": self.source_kind,
            "claims": [{"claim_id": claim.claim_id, "text": claim.text,
                        "span_start": claim.span_start, "span_end": claim.span_end,
                        "evidence_ids": claim.evidence_ids,
                        "citation_ids": claim.citation_ids,
                        "claim_type": claim.claim_type,
                        "review_reasons": claim.review_reasons,
                        "citation_marker_spans": claim.citation_marker_spans}
                       for claim in self.claims],
        }
        return hashlib.sha256(canonical_bytes(record)).hexdigest()


@dataclass(frozen=True)
class ClaimAssessment:
    claim_id: str
    prediction: str
    review_required: bool
    decision_reason: str
    rule_trace: tuple[RuleTrace, ...]
    citation_checks: tuple[CitationCheck, ...]
    verifier_output: VerifierOutput | None
    failure_tag: str | None = None

    def __post_init__(self) -> None:
        if (not _identifier(self.claim_id)
                or self.prediction not in {"supported", "contradicted", "insufficient"}
                or type(self.review_required) is not bool
                or not _identifier(self.decision_reason)
                or type(self.rule_trace) is not tuple
                or type(self.citation_checks) is not tuple):
            raise ValueError("invalid_w5_claim_assessment")
        if self.verifier_output is None:
            if (self.prediction != "insufficient" or not self.review_required
                    or self.failure_tag != "VERIFIER_FAILURE"
                    or not self.rule_trace):
                raise ValueError("invalid_w5_failure_fallback")
        elif (self.verifier_output.arm != "V3"
              or self.verifier_output.request.pair.pair_id != self.claim_id
              or self.prediction != self.verifier_output.prediction
              or self.review_required != self.verifier_output.review_required
              or self.decision_reason != self.verifier_output.decision_reason
              or self.rule_trace != self.verifier_output.rule_trace
              or self.citation_checks != self.verifier_output.citation_checks
              or self.failure_tag is not None):
            raise ValueError("unmatched_w5_v3_assessment")


@dataclass(frozen=True)
class StructuredDraftReport:
    """Verified draft packet for later omission, repair, and analyst stages."""

    incident_id: str
    tenant_id: str
    draft_id: str
    draft_sha256: str
    retrieved_evidence_ids: tuple[str, ...]
    incident_overview: str
    claims: tuple[ClaimAssessment, ...]
    status: str = STATUS
    version: str = VERSION

    def __post_init__(self) -> None:
        if (not all(_identifier(item) for item in
                    (self.incident_id, self.tenant_id, self.draft_id))
                or not isinstance(self.incident_overview, str)
                or not self.incident_overview.strip()
                or len(self.draft_sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.draft_sha256)
                or type(self.retrieved_evidence_ids) is not tuple
                or type(self.claims) is not tuple or not self.claims
                or self.status != STATUS or self.version != VERSION):
            raise ValueError("invalid_structured_draft_report")


def verify_synthetic_draft(context: RetrievedIncident, draft: SyntheticDraft,
                           verifier: SyntheticV3Verifier) -> StructuredDraftReport:
    """Verify authored claims after the draft and retrieval set are fixed."""
    if (not isinstance(context, RetrievedIncident)
            or not isinstance(draft, SyntheticDraft)
            or not isinstance(verifier, SyntheticV3Verifier)):
        raise ValueError("invalid_w5_synthetic_integration_input")
    if draft.source_kind != "SYNTHETIC_AUTHORED_NOT_GOLD":
        raise ValueError("generated_claims_require_atomization_review")
    if (draft.incident_id != context.bundle.incident_id
            or draft.tenant_id != context.bundle.tenant_id
            or draft.retrieved_evidence_ids != context.evidence_ids):
        raise ValueError("draft_retrieval_scope_or_order_mismatch")
    fixed = set(context.evidence_ids)
    for claim in draft.claims:
        if (not set(claim.evidence_ids) <= fixed
                or not set(claim.citation_ids) <= set(claim.evidence_ids)):
            raise ValueError("claim_evidence_outside_fixed_retrieval")
    assessments = []
    for claim in draft.claims:
        pair = NLIPair(claim.claim_id, draft.incident_id, draft.tenant_id,
                       claim.text, claim.evidence_ids)
        request = VerifierInput.from_synthetic_data(
            context.data, pair, citation_ids=claim.citation_ids)
        try:
            output = verifier.predict(request)
        except Exception:
            output = None
        if output is None:
            assessments.append(ClaimAssessment(
                claim.claim_id, "insufficient", True, "VERIFIER_FAILURE",
                (RuleTrace(f"{VERSION}:inference_boundary", "insufficient", (),
                           "VERIFIER_FAILURE"),), request.citation_checks,
                None, "VERIFIER_FAILURE"))
            continue
        if not isinstance(output, VerifierOutput) or output.request is not request:
            raise ValueError("unmatched_w5_v3_output")
        assessments.append(ClaimAssessment(
            claim.claim_id, output.prediction, output.review_required,
            output.decision_reason, output.rule_trace, output.citation_checks,
            output))
    return StructuredDraftReport(
        draft.incident_id, draft.tenant_id, draft.draft_id, draft.sha256,
        draft.retrieved_evidence_ids, draft.text, tuple(assessments))
