"""W1-07 workflow access checks and future W5/W7 input contracts.

These are in-process checks for an authorized workflow. A real custodian must
also isolate storage, credentials, processes, and audit logs; Python roles are
not an OS security boundary or permission to open sealed material.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from .integrity import Manifest, canonical_bytes
from .schemas import EvaluationGoldRecord, EvidenceEvent, IncidentBundle
from .split_freeze import Partition


Role = Literal["development", "custodian", "annotator", "evaluator"]
Purpose = Literal["annotation", "evaluation"]


@dataclass(frozen=True, slots=True)
class AccessGrant:
    manifest_id: str
    owner_ref: str
    custodian_ref: str
    purpose: Purpose
    partition: Partition | None = None
    authorized_incidents: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.manifest_id, self.owner_ref, self.custodian_ref
        )):
            raise ValueError("grant needs manifest and owner/custodian references")
        if self.purpose not in ("annotation", "evaluation"):
            raise ValueError("invalid grant purpose")
        if self.partition is not None and self.partition not in (
            "train", "validation", "heldout_a", "heldout_b"
        ):
            raise ValueError("invalid grant partition")
        incidents = tuple(tuple(item) for item in self.authorized_incidents)
        if len(incidents) != len(set(incidents)) or any(
            len(item) != 2 or not item[0].strip() or not item[1].strip() for item in incidents
        ):
            raise ValueError("authorized incident scopes must be unique tenant/incident pairs")
        object.__setattr__(self, "authorized_incidents", incidents)


def require_access(
    role: Role,
    partition: Partition,
    *,
    gold: bool = False,
    grant: AccessGrant | None = None,
) -> None:
    """Deny development held-out/gold access; grants are workflow attestations."""

    if partition not in ("train", "validation", "heldout_a", "heldout_b"):
        raise ValueError("unknown partition")
    if role == "development":
        if gold or partition not in ("train", "validation"):
            raise PermissionError("development cannot access held-out or evaluation gold")
        return
    if role == "custodian":
        return
    if role == "annotator" and grant is not None and grant.purpose == "annotation":
        return
    if role == "evaluator" and grant is not None and grant.purpose == "evaluation":
        return
    raise PermissionError("restricted access requires an appropriate scoped grant")


@dataclass(frozen=True, slots=True)
class OperationalFact:
    fact_id: str
    incident_id: str
    tenant_id: str
    statement: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.fact_id, self.incident_id, self.tenant_id, self.statement
        )):
            raise ValueError("operational fact identity and statement are required")
        evidence_ids = tuple(self.evidence_ids)
        if (not evidence_ids or len(evidence_ids) != len(set(evidence_ids))
                or any(not isinstance(item, str) or not item.strip() for item in evidence_ids)):
            raise ValueError("operational fact needs unique evidence IDs")
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class InferenceInput:
    incident: IncidentBundle
    evidence: tuple[EvidenceEvent, ...]
    operational_facts: tuple[OperationalFact, ...]
    # Deliberately no evaluation-gold field.


def _manifest_scopes(manifest: Manifest, *, frozen: bool) -> dict[tuple[str, str], Partition]:
    """Read the custodian-supplied manifest scope; caller strings are not authority."""

    manifest.verify()
    if frozen and manifest.lifecycle != "frozen":
        raise PermissionError("evaluation requires a frozen manifest record")
    metadata = manifest.data["metadata"]
    if not metadata.get("assignment_plan_sha256") or (
        frozen and not metadata.get("audit_report_sha256")
    ):
        raise ValueError("manifest lacks required split-plan or audit binding")
    scopes: dict[tuple[str, str], Partition] = {}
    seen: set[tuple[str, str]] = set()
    for entry in manifest.data["entries"]:
        partition = entry["partition"]
        for item in entry.get("incidents", []):
            key = (item["tenant_id"], item["incident_id"])
            if key in seen:
                raise ValueError("incident appears in multiple manifest entries")
            seen.add(key)
            if partition in ("train", "validation", "heldout_a", "heldout_b"):
                scopes[key] = partition
    return scopes


def build_inference_input(
    incident: IncidentBundle,
    evidence: tuple[EvidenceEvent, ...],
    operational_facts: tuple[OperationalFact, ...],
    *,
    partition: Partition,
    role: Role,
    grant: AccessGrant | None = None,
    manifest: Manifest | None = None,
) -> InferenceInput:
    if manifest is None:
        raise PermissionError("inference requires a trusted manifest-linked scope")
    scopes = _manifest_scopes(manifest, frozen=role == "evaluator")
    key = (incident.tenant_id, incident.incident_id)
    actual_partition = scopes.get(key)
    if actual_partition is None or partition != actual_partition:
        raise PermissionError("inference incident/partition differs from manifest")
    require_access(role, partition, grant=grant)
    if role in ("annotator", "evaluator") and (
        grant is None or grant.manifest_id != manifest.manifest_id
        or grant.partition != actual_partition or key not in grant.authorized_incidents
    ):
        raise PermissionError("inference grant lacks manifest, partition or incident scope")
    events = tuple(evidence)
    facts = tuple(operational_facts)
    for event in events:
        if type(event) is not EvidenceEvent:
            raise TypeError("inference evidence must be EvidenceEvent")
        incident.check_scope(event)
    supplied_evidence_ids = {event.evidence_id for event in events}
    for fact in facts:
        if type(fact) is not OperationalFact:
            raise TypeError("evaluation gold cannot enter operational facts")
        if (fact.incident_id, fact.tenant_id) != (incident.incident_id, incident.tenant_id):
            raise ValueError("operational fact outside incident/tenant")
        if not set(fact.evidence_ids) <= supplied_evidence_ids:
            raise ValueError("operational fact uses evidence absent from this inference call")
    return InferenceInput(incident, events, facts)


class EvaluationStore:
    """Manifest-scoped adapter; host storage and credentials must also isolate gold."""

    def __init__(
        self, manifest: Manifest,
        gold: dict[tuple[str, str], EvaluationGoldRecord],
    ) -> None:
        if manifest.lifecycle != "frozen":
            raise ValueError("evaluation gold requires a frozen manifest record")
        scopes = _manifest_scopes(manifest, frozen=True)
        for key, record in gold.items():
            if key != (record.tenant_id, record.incident_id) or key not in scopes:
                raise ValueError("gold record lacks matching manifest incident scope")
        self._manifest_id = manifest.manifest_id
        self._scopes = scopes
        self._gold = dict(gold)

    def read_gold(
        self, incident_id: str, *, tenant_id: str, partition: Partition, role: Role,
        grant: AccessGrant | None = None,
    ) -> EvaluationGoldRecord:
        key = (tenant_id, incident_id)
        actual_partition = self._scopes.get(key)
        if actual_partition is None:
            raise PermissionError("incident is absent from the verified gold manifest")
        if partition != actual_partition:
            raise PermissionError("caller partition differs from manifest partition")
        require_access(role, partition, gold=True, grant=grant)
        if (grant is None or grant.manifest_id != self._manifest_id
                or grant.partition != actual_partition
                or key not in grant.authorized_incidents):
            raise PermissionError("grant is not scoped to this manifest, partition and incident")
        return self._gold[key]


PairPopulation = Literal["primary_draft", "source_diagnostic", "repair_diagnostic", "s3_output"]


@dataclass(frozen=True, slots=True)
class PairManifestCandidate:
    pair_id: str
    incident_id: str
    population: PairPopulation
    claim_source: str
    evidence_ids: tuple[str, ...]
    evidence_snapshot_sha256: str
    lineage_component_id: str
    draft_id: str | None = None
    draft_sha256: str | None = None
    annotation_record_id: str | None = None
    inclusion_probability: str | None = None
    arm_independent: bool = False
    generation_config_sha256: str | None = None
    pairing_rule_sha256: str | None = None

    def __post_init__(self) -> None:
        for value in (self.pair_id, self.incident_id, self.claim_source, self.lineage_component_id):
            if not value.strip():
                raise ValueError("pair IDs, source and lineage are required")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if not self.evidence_ids:
            raise ValueError("pair needs fixed permitted evidence IDs")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("pair evidence IDs must be unique")
        if any(not isinstance(item, str) or not item.strip() for item in self.evidence_ids):
            raise ValueError("pair evidence IDs must be nonblank")
        if self.population not in (
            "primary_draft", "source_diagnostic", "repair_diagnostic", "s3_output"
        ):
            raise ValueError("unknown pair population")
        if (not isinstance(self.evidence_snapshot_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.evidence_snapshot_sha256)):
            raise ValueError("pair evidence snapshot requires SHA-256 hex")
        for digest in (self.draft_sha256, self.generation_config_sha256, self.pairing_rule_sha256):
            if digest is not None and (
                not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError("snapshot/draft digest must be SHA-256 hex")
        if self.inclusion_probability is not None:
            if type(self.inclusion_probability) is not str:
                raise ValueError("inclusion probability must be a decimal string")
            try:
                probability = Decimal(self.inclusion_probability)
            except InvalidOperation as exc:
                raise ValueError("inclusion probability must be a decimal string") from exc
            if not probability.is_finite() or not 0 < probability <= 1:
                raise ValueError("inclusion probability must be in (0, 1]")
        if self.population == "primary_draft" and (
            self.claim_source != "generated_draft" or not self.draft_id
            or not self.draft_sha256 or not self.annotation_record_id
            or not self.arm_independent or not self.generation_config_sha256
            or not self.pairing_rule_sha256
        ):
            raise ValueError("primary pair requires arm-independent draft and annotation lineage")
        if self.population != "primary_draft" and self.claim_source == "generated_draft":
            raise ValueError("draft-derived primary claims cannot be relabeled diagnostic")


@dataclass(frozen=True, slots=True)
class VerifierInputIdentity:
    arm: Literal["V2", "V3"]
    ordered_pair_ids: tuple[str, ...]
    evidence_ids_by_pair: tuple[tuple[str, ...], ...]
    serialized_evidence_sha256: str
    nli_checkpoint: str
    shared_thresholds_sha256: str
    ordered_claim_texts: tuple[str, ...]
    ordered_claim_evidence_payload: bytes
    serialized_evidence: bytes
    shared_thresholds_payload: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_pair_ids", tuple(self.ordered_pair_ids))
        object.__setattr__(self, "evidence_ids_by_pair", tuple(
            tuple(ids) for ids in self.evidence_ids_by_pair
        ))
        object.__setattr__(self, "ordered_claim_texts", tuple(self.ordered_claim_texts))
        if self.arm not in ("V2", "V3") or not self.nli_checkpoint.strip():
            raise ValueError("verifier arm and NLI checkpoint are required")
        if not self.ordered_pair_ids or len(self.ordered_pair_ids) != len(set(self.ordered_pair_ids)):
            raise ValueError("verifier pair IDs must be nonempty and unique")
        if len(self.ordered_pair_ids) != len(self.evidence_ids_by_pair):
            raise ValueError("pair/evidence cardinality differs")
        if len(self.ordered_pair_ids) != len(self.ordered_claim_texts):
            raise ValueError("pair/claim cardinality differs")
        if any(not isinstance(text, str) or not text.strip() for text in self.ordered_claim_texts):
            raise ValueError("claim text must be nonblank")
        if any(not ids or len(ids) != len(set(ids)) for ids in self.evidence_ids_by_pair):
            raise ValueError("each pair needs unique evidence IDs")
        for digest in (self.serialized_evidence_sha256, self.shared_thresholds_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("verifier input hashes must be SHA-256 hex")
        payload = [
            {"pair_id": pair_id, "claim": claim, "evidence_ids": list(evidence_ids)}
            for pair_id, claim, evidence_ids in zip(
                self.ordered_pair_ids, self.ordered_claim_texts, self.evidence_ids_by_pair
            )
        ]
        if canonical_bytes(payload) != self.ordered_claim_evidence_payload:
            raise ValueError("ordered claim-evidence payload differs from its fields")
        if hashlib.sha256(self.serialized_evidence).hexdigest() != self.serialized_evidence_sha256:
            raise ValueError("serialized evidence digest mismatch")
        if hashlib.sha256(self.shared_thresholds_payload).hexdigest() != self.shared_thresholds_sha256:
            raise ValueError("shared thresholds digest mismatch")

    @property
    def ordered_payload_sha256(self) -> str:
        return hashlib.sha256(self.ordered_claim_evidence_payload).hexdigest()


def verify_shared_v2_v3_inputs(v2: VerifierInputIdentity, v3: VerifierInputIdentity) -> None:
    if (v2.arm, v3.arm) != ("V2", "V3"):
        raise ValueError("verifier identities must be V2 then V3")
    if len(v2.ordered_pair_ids) != len(v2.evidence_ids_by_pair):
        raise ValueError("V2 pair/evidence cardinality differs")
    if len(v3.ordered_pair_ids) != len(v3.evidence_ids_by_pair):
        raise ValueError("V3 pair/evidence cardinality differs")
    for field in (
        "ordered_pair_ids", "ordered_claim_texts", "evidence_ids_by_pair",
        "ordered_claim_evidence_payload", "serialized_evidence",
        "serialized_evidence_sha256", "nli_checkpoint",
        "shared_thresholds_payload", "shared_thresholds_sha256",
    ):
        if getattr(v2, field) != getattr(v3, field):
            raise ValueError(f"V2/V3 {field} differs")


@dataclass(frozen=True, slots=True)
class S2ForkIdentity:
    incident_id: str
    archive_id: str
    archive_sha256: str
    evidence_snapshot_sha256: str
    retrieval_sha256: str
    initial_draft_sha256: str
    verification_trace_sha256: str
    configuration_sha256: str

    def __post_init__(self) -> None:
        if not self.incident_id.strip() or not self.archive_id.strip():
            raise ValueError("S2 fork needs incident and archive IDs")
        for digest in (
            self.archive_sha256, self.evidence_snapshot_sha256, self.retrieval_sha256,
            self.initial_draft_sha256, self.verification_trace_sha256,
            self.configuration_sha256,
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("S2 fork hashes must be SHA-256 hex")


def verify_s2_s3_fork(s2: S2ForkIdentity, s3: S2ForkIdentity, archive_bytes: bytes) -> None:
    if s2 != s3:
        raise ValueError("S2/S3 do not share the identical archived fork state")
    if hashlib.sha256(archive_bytes).hexdigest() != s2.archive_sha256:
        raise ValueError("S2 fork archive bytes do not match their recorded digest")
