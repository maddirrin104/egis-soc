"""W4-00 synthetic-only verifier boundary; no rule or fusion policy lives here."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from egis_soc.development_data import DevelopmentData
from egis_soc.development_retrieval import DevelopmentRetriever, _passage
from egis_soc.development_v2 import (
    MODEL_ID, MODEL_REVISION, DevelopmentV2, NLIPair,
)


VERSION = "w4-synthetic-verifier-contract-1"
LABELS = frozenset({"supported", "contradicted", "insufficient"})
ARMS = frozenset({"V0", "V2", "V3"})
NLI_SCORES = frozenset({"contradiction", "entailment", "neutral"})
_FORBIDDEN_FIELDS = frozenset({
    "expected", "label", "gold_status", "gold_label", "gold_facts",
    "annotation_source", "annotation_record_id", "human_label", "human_status",
    "support_status", "prediction", "verifier_output", "split_id",
})


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _snapshot(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _snapshot(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot(item) for item in value)
    return value


@dataclass(frozen=True)
class OrderedEvidence:
    evidence_id: str
    text: str
    incident_id: str
    tenant_id: str


@dataclass(frozen=True)
class CitationCheck:
    evidence_id: str
    valid: bool
    reason: str  # IN_FIXED_SET or UNKNOWN_OR_OUTSIDE_FIXED_SET


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    outcome: str  # pass, contradiction, insufficient, not_applicable
    evidence_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class VerifierInput:
    """One author-asserted atomic claim and one fixed, ordered synthetic set.

    Atomicity is a caller/author review obligation; text alone cannot prove it.
    The W3 V2 pair and data are retained so V2 receives its unchanged input.
    """

    data: DevelopmentData
    pair: NLIPair
    evidence: tuple[OrderedEvidence, ...]
    citation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.data, DevelopmentData) or not isinstance(self.pair, NLIPair):
            raise ValueError("invalid_verifier_input_type")
        if (type(self.data.events) is not tuple or any(not isinstance(event, Mapping)
                                                      for event in self.data.events)
                or type(self.pair.evidence_ids) is not tuple
                or type(self.evidence) is not tuple or type(self.citation_ids) is not tuple):
            raise ValueError("mutable_or_invalid_verifier_input")
        object.__setattr__(self, "data", replace(
            self.data, events=tuple(_snapshot(event) for event in self.data.events)))
        DevelopmentRetriever(self.data)
        if (self.data.source_dataset != "synthetic" or self.data.partition != "train"
                or self.data.lineage_group != "SYNTHETIC"
                or self.data.manifest_sha256 is not None):
            raise ValueError("verifier_requires_synthetic_train")
        if (not _identifier(self.pair.pair_id) or not isinstance(self.pair.claim, str)
                or not self.pair.claim.strip() or self.pair.claim != self.pair.claim.strip()
                or self.pair.gold_status != "NOT_GOLD"
                or self.pair.incident_id != self.data.incident_id
                or self.pair.tenant_id != self.data.tenant_id):
            raise ValueError("invalid_verifier_claim_or_scope")
        if (not self.pair.evidence_ids
                or any(not _identifier(item) for item in self.pair.evidence_ids)
                or len(set(self.pair.evidence_ids)) != len(self.pair.evidence_ids)
                or any(not _identifier(item) for item in self.citation_ids)
                or len(set(self.citation_ids)) != len(self.citation_ids)):
            raise ValueError("missing_or_duplicate_verifier_id")
        for event in self.data.events:
            if any(not isinstance(key, str) or key.casefold() in _FORBIDDEN_FIELDS
                   or "gold" in key.casefold() or key.casefold().startswith("human_")
                   for key in event):
                raise ValueError("gold_bearing_verifier_evidence")
            fields = event["event_data"]
            if any(not isinstance(key, str) or key.casefold() in _FORBIDDEN_FIELDS
                   or "gold" in key.casefold() or key.casefold().startswith("human_")
                   for key in fields):
                raise ValueError("gold_bearing_verifier_evidence")
        if (len(self.evidence) != len(self.pair.evidence_ids)
                or any(not isinstance(item, OrderedEvidence) for item in self.evidence)):
            raise ValueError("verifier_evidence_mismatch")
        for item, evidence_id in zip(self.evidence, self.pair.evidence_ids):
            event = self.data.resolve(evidence_id, incident_id=self.pair.incident_id,
                                      tenant_id=self.pair.tenant_id)
            if (item.evidence_id != evidence_id or item.incident_id != self.pair.incident_id
                    or item.tenant_id != self.pair.tenant_id or item.text != _passage(event)):
                raise ValueError("verifier_evidence_mismatch")

    @classmethod
    def from_synthetic_data(cls, data: DevelopmentData, pair: NLIPair,
                            *, citation_ids: tuple[str, ...] = ()) -> VerifierInput:
        # Validate scope before resolving any ID; no foreign event can enter the set.
        DevelopmentRetriever(data)
        if (data.source_dataset != "synthetic" or data.partition != "train"
                or pair.incident_id != data.incident_id or pair.tenant_id != data.tenant_id
                or not pair.evidence_ids or any(not _identifier(item) for item in pair.evidence_ids)
                or len(set(pair.evidence_ids)) != len(pair.evidence_ids)):
            raise ValueError("invalid_verifier_claim_or_scope")
        evidence = tuple(OrderedEvidence(evidence_id, _passage(data.resolve(
            evidence_id, incident_id=pair.incident_id, tenant_id=pair.tenant_id)),
            pair.incident_id, pair.tenant_id) for evidence_id in pair.evidence_ids)
        return cls(data, pair, evidence, citation_ids)

    @property
    def citation_checks(self) -> tuple[CitationCheck, ...]:
        fixed = set(self.pair.evidence_ids)
        return tuple(CitationCheck(item, item in fixed,
                                   "IN_FIXED_SET" if item in fixed else
                                   "UNKNOWN_OR_OUTSIDE_FIXED_SET")
                     for item in self.citation_ids)


@dataclass(frozen=True)
class VerifierOutput:
    request: VerifierInput
    arm: str
    prediction: str
    review_required: bool
    decision_reason: str
    rule_trace: tuple[RuleTrace, ...]
    citation_checks: tuple[CitationCheck, ...]
    nli_scores: Mapping[str, float] | None = None
    model_id: str | None = None
    model_revision: str | None = None
    truncated: bool = False
    policy_version: str | None = None
    policy_sha256: str | None = None
    version: str = VERSION
    status: str = "SYNTHETIC_DEVELOPMENT_NOT_GOLD"

    def __post_init__(self) -> None:
        if (not isinstance(self.request, VerifierInput) or self.arm not in ARMS
                or self.prediction not in LABELS or type(self.review_required) is not bool
                or not _identifier(self.decision_reason) or type(self.truncated) is not bool
                or self.version != VERSION or self.status != "SYNTHETIC_DEVELOPMENT_NOT_GOLD"
                or type(self.rule_trace) is not tuple or type(self.citation_checks) is not tuple
                or self.citation_checks != self.request.citation_checks):
            raise ValueError("invalid_verifier_output")
        if any(not check.valid for check in self.citation_checks) and not self.review_required:
            raise ValueError("invalid_citation_requires_review")
        fixed = set(self.request.pair.evidence_ids)
        if any(not isinstance(trace, RuleTrace) for trace in self.rule_trace):
            raise ValueError("invalid_verifier_rule_trace")
        if len({trace.rule_id for trace in self.rule_trace}) != len(self.rule_trace):
            raise ValueError("duplicate_verifier_rule_trace")
        for trace in self.rule_trace:
            if (not _identifier(trace.rule_id) or type(trace.evidence_ids) is not tuple
                    or trace.outcome not in {"pass", "contradiction", "insufficient", "not_applicable"}
                    or not _identifier(trace.reason) or len(set(trace.evidence_ids)) != len(trace.evidence_ids)
                    or not set(trace.evidence_ids) <= fixed):
                raise ValueError("invalid_verifier_rule_trace")
        if self.arm == "V2":
            if self.rule_trace:
                raise ValueError("v2_has_no_rules")
        elif not self.rule_trace:
            raise ValueError("rules_require_trace")
        if self.arm == "V0":
            if self.nli_scores is not None or self.model_id is not None or self.model_revision is not None:
                raise ValueError("v0_has_no_nli")
        elif (self.model_id != MODEL_ID or self.model_revision != MODEL_REVISION
              or not isinstance(self.nli_scores, Mapping)
              or set(self.nli_scores) != NLI_SCORES
              or any(not isinstance(value, (int, float)) or not math.isfinite(value)
                     or value < 0 for value in self.nli_scores.values())
              or not math.isclose(sum(self.nli_scores.values()), 1.0, abs_tol=1e-8)):
            raise ValueError("unmatched_verifier_nli")
        if self.arm == "V2" and self.prediction != {
            "contradiction": "contradicted", "entailment": "supported",
            "neutral": "insufficient",
        }[max(("contradiction", "entailment", "neutral"),
              key=lambda label: self.nli_scores[label])]:
            raise ValueError("v2_prediction_disagrees_with_nli")
        if self.arm == "V3":
            if (not _identifier(self.policy_version) or not isinstance(self.policy_sha256, str)
                    or len(self.policy_sha256) != 64
                    or any(character not in "0123456789abcdef" for character in self.policy_sha256)):
                raise ValueError("v3_requires_versioned_policy")
        elif self.policy_version is not None or self.policy_sha256 is not None:
            raise ValueError("non_v3_policy_metadata")
        if self.nli_scores is not None:
            object.__setattr__(self, "nli_scores", MappingProxyType(dict(self.nli_scores)))


def run_v2(request: VerifierInput, model: DevelopmentV2) -> VerifierOutput:
    """Adapt unchanged pinned V2 output; never inspect fixture answer labels."""
    result = model.predict(request.data, request.pair)
    return VerifierOutput(
        request=request, arm="V2", prediction=result["prediction"],
        review_required=(result["prediction"] == "insufficient"
                         or any(not item.valid for item in request.citation_checks)),
        decision_reason=result["reason"], rule_trace=(),
        citation_checks=request.citation_checks, nli_scores=result["scores"],
        model_id=result["model_id"], model_revision=result["model_revision"],
        truncated=result["truncated"],
    )
