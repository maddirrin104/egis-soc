"""W1-03 data contracts. Validation does not adjudicate factual support.

Raw events remain in their source store; these models describe a snapshot and
its references. ``IncidentBundle`` is inference-facing and contains no
evaluation gold. Call ``IncidentBundle.check_scope`` before using an event or
claim pair with a bundle. A valid citation ID alone never proves a claim.
Parse untrusted inputs through validation; ``model_construct`` and direct
Pydantic base-class APIs can bypass these contracts and are not trusted input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SupportLabel = Literal["supported", "contradicted", "insufficient"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> Self:
        """Require validation for changed records; Pydantic skips it in updates."""

        if update:
            raise ValueError("model_copy(update=...) skips validation; construct a validated record instead")
        return super().model_copy(deep=deep)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _unique_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError("IDs must be unique")
    return values


class EvidenceProvenance(ContractModel):
    """Source details for one immutable evidence snapshot.

    ``raw_message_ref`` is an opaque, stable key resolved by the source store.
    ``sha256`` covers the exact persisted raw snapshot bytes at that key,
    before decoding or normalization; ``raw_message`` is a decoded view.
    Ingestion must verify the digest against those bytes and retain the raw
    snapshot outside Git. A matching digest does not attest source truth.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    timestamp_utc: datetime
    raw_message: str
    raw_message_ref: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_method: str

    @field_validator("source", "acquisition_method")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("raw_message_ref")
    @classmethod
    def valid_raw_reference(cls, value: str) -> str:
        if not value or any(character.isspace() for character in value):
            raise ValueError("raw message reference must be a nonblank source-store key")
        return value

    @field_validator("timestamp_utc")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value.astimezone(timezone.utc)


class EvidenceEvent(ContractModel):
    """Normalized view bound to an immutable raw-snapshot provenance record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    incident_id: str
    tenant_id: str
    normalized_fields: dict[str, Any]
    provenance: EvidenceProvenance

    @field_validator("evidence_id", "incident_id", "tenant_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        return _nonblank(value)


class GoldFact(ContractModel):
    """Human-reviewed evaluation fact, separate from operational facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    statement: str
    criticality: Literal["low", "medium", "high"]
    support_status: SupportLabel
    evidence_ids: tuple[str, ...]
    observability: str
    annotation_source: Literal["human_reviewed"]

    @field_validator("fact_id", "statement", "observability")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_ids(tuple(_nonblank(value) for value in values))

    @model_validator(mode="after")
    def supported_has_evidence(self) -> GoldFact:
        if self.support_status == "supported" and not self.evidence_ids:
            raise ValueError("a supported gold fact needs cited evidence")
        return self


class ClaimEvidencePair(ContractModel):
    """Labeled pair for training or diagnostics; not evaluation gold by itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str
    incident_id: str
    tenant_id: str
    claim: str
    evidence_ids: tuple[str, ...]
    claim_type: str
    label: SupportLabel
    annotation_source: str
    claim_source: str = "unspecified"

    @field_validator("pair_id", "incident_id", "tenant_id", "claim", "claim_type", "annotation_source", "claim_source")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_ids(tuple(_nonblank(value) for value in values))

    @model_validator(mode="after")
    def decided_pair_has_evidence(self) -> ClaimEvidencePair:
        if self.label != "insufficient" and not self.evidence_ids:
            raise ValueError("supported/contradicted pairs need evidence")
        return self


class EvaluationClaimEvidencePair(ClaimEvidencePair):
    """Human-reviewed gold label; candidate origin is recorded separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_source: str
    annotation_source: Literal["human_reviewed"]
    annotation_record_id: str

    @field_validator("annotation_record_id")
    @classmethod
    def nonblank_annotation_record(cls, value: str) -> str:
        return _nonblank(value)


class IncidentBundle(ContractModel):
    """Inference-facing references for a triaged incident; no gold facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str
    tenant_id: str
    environment_id: str
    source_dataset: str
    scenario_family: str
    alert_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    @field_validator("incident_id", "tenant_id", "environment_id", "source_dataset", "scenario_family")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("alert_ids", "evidence_ids")
    @classmethod
    def unique_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_ids(tuple(_nonblank(value) for value in values))

    @model_validator(mode="after")
    def check_internal_references(self) -> IncidentBundle:
        if not self.evidence_ids:
            raise ValueError("incident bundle needs evidence")
        return self

    def check_scope(self, item: EvidenceEvent | ClaimEvidencePair) -> None:
        """Reject another tenant/incident or an unknown evidence reference."""

        if item.tenant_id != self.tenant_id or item.incident_id != self.incident_id:
            raise ValueError("item is outside this tenant/incident")
        references = {item.evidence_id} if isinstance(item, EvidenceEvent) else set(item.evidence_ids)
        if not references <= set(self.evidence_ids):
            raise ValueError("item references evidence outside this incident")


class EvaluationGoldRecord(ContractModel):
    """Evaluation-only facts, stored separately from inference incident input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str
    tenant_id: str
    evidence_ids: tuple[str, ...]
    gold_facts: tuple[GoldFact, ...]

    @field_validator("incident_id", "tenant_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_ids(tuple(_nonblank(value) for value in values))

    @model_validator(mode="after")
    def check_internal_references(self) -> EvaluationGoldRecord:
        if len({fact.fact_id for fact in self.gold_facts}) != len(self.gold_facts):
            raise ValueError("fact IDs must be unique within an incident")
        known = set(self.evidence_ids)
        for fact in self.gold_facts:
            if not set(fact.evidence_ids) <= known:
                raise ValueError(f"fact {fact.fact_id} cites evidence outside its incident")
        return self

    def check_scope(self, incident: IncidentBundle) -> None:
        """Require the same incident, tenant, and permitted evidence snapshot."""

        if self.incident_id != incident.incident_id or self.tenant_id != incident.tenant_id:
            raise ValueError("gold record is outside this tenant/incident")
        if set(self.evidence_ids) != set(incident.evidence_ids):
            raise ValueError("gold record uses a different evidence snapshot")
