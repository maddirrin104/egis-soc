"""W1-03 data contracts. Validation does not adjudicate factual support.

Raw events remain in their source store; these models describe a snapshot and
its references. ``IncidentBundle`` is inference-facing and contains no
evaluation gold. Call ``IncidentBundle.check_scope`` before using an event or
claim pair with a bundle. A valid citation ID alone never proves a claim.
Parse untrusted inputs through validation; ``model_construct`` and direct
Pydantic base-class APIs can bypass these contracts and are not trusted input.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FieldSerializationInfo,
    JsonValue,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)


SupportLabel = Literal["supported", "contradicted", "insufficient"]
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


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


def _strict_json(value: object, active: set[int] | None = None) -> JsonValue:
    """Validate exact JSON types and detach containers from untrusted input."""

    if value is None or type(value) in (str, bool, int):
        return cast(JsonValue, value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if type(value) not in (dict, list):
        raise ValueError(f"unsupported JSON value: {type(value).__name__}")
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ValueError("JSON containers must not contain cycles")
    active.add(identity)
    try:
        if type(value) is list:
            return [_strict_json(item, active) for item in value]
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            result[key] = _strict_json(item, active)
        return result
    finally:
        active.remove(identity)


class _FrozenJSONMapping(Mapping[str, JsonValue]):
    """Immutable mapping with no mutable backing object exposed to callers."""

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[tuple[str, object]]) -> None:
        object.__setattr__(self, "_items", tuple(items))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("normalized JSON objects are immutable")

    def __getitem__(self, key: str) -> JsonValue:
        for item_key, value in self._items:
            if item_key == key:
                return cast(JsonValue, value)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __deepcopy__(self, memo: dict[int, object]) -> _FrozenJSONMapping:
        return self


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return _FrozenJSONMapping((key, _freeze_json(item)) for key, item in value.items())
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _mutable_json(value: object) -> JsonValue:
    if isinstance(value, _FrozenJSONMapping):
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mutable_json(item) for item in value]
    return cast(JsonValue, value)


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
    """Normalized view bound to provenance; JSON objects/arrays are read-only after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    incident_id: str
    tenant_id: str
    normalized_fields: Mapping[str, JsonValue]
    provenance: EvidenceProvenance

    @field_validator("normalized_fields", mode="before")
    @classmethod
    def validate_json_fields(cls, value: object) -> JsonValue:
        if type(value) is not dict:
            raise ValueError("normalized_fields must be a JSON object")
        return _strict_json(value)

    @field_validator("normalized_fields")
    @classmethod
    def freeze_json_fields(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return cast(Mapping[str, JsonValue], _freeze_json(value))

    @field_serializer("normalized_fields")
    def serialize_json_fields(self, value: Mapping[str, JsonValue], info: FieldSerializationInfo) -> JsonValue:
        detached = cast(dict[str, JsonValue], _mutable_json(value))
        return _JSON_OBJECT_ADAPTER.dump_python(
            detached, mode=info.mode, include=info.include, exclude=info.exclude
        )

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
