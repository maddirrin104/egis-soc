"""W1-07 proposed group split, leakage audit, and structural design checks.

All inputs are sidecar records supplied by an authorized custodian. This
module never loads raw telemetry, sealed gold, or model predictions.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from itertools import combinations
from typing import Literal

from .integrity import FreezeApproval, Manifest, canonical_bytes
from .lineage import Component, GroupKey, LineageGraph, LineageRecord


Partition = Literal["train", "validation", "heldout_a", "heldout_b"]
AssignmentState = Literal["train", "validation", "heldout_a", "heldout_b", "reserved", "quarantine"]
PARTITIONS: tuple[Partition, ...] = ("train", "validation", "heldout_a", "heldout_b")
_A_PARTITIONS: tuple[Partition, ...] = ("train", "validation", "heldout_a")
ALGORITHM_REVISION = "whole-component-greedy-v1"
NORMALIZATION_VERSION = "nfc-casefold-whitespace-v1"
CANDIDATE_METHOD = "all-pairs-sequencematcher-v1"
DEFAULT_MAX_PAIR_COMPARISONS = 100_000  # Provisional safety cap; not methodological approval.
DEFAULT_MAX_INTRA_DUPLICATE_PAIRS = 100_000  # Exact-key candidate cap, pending owner review.


@dataclass(frozen=True, slots=True)
class AssignmentPlan:
    policy_version: str
    seed: str
    # Explicit owner-selected targets; the source plan's 40/10/15/15 is not a default.
    a_targets: tuple[int, int, int]
    minimum_components: tuple[int, int, int, int]
    heldout_a_collections: tuple[GroupKey, ...] = ()
    algorithm_revision: str = ALGORITHM_REVISION
    configuration_revision: str = "unreviewed"
    audit_policy_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "a_targets", tuple(self.a_targets))
        object.__setattr__(self, "minimum_components", tuple(self.minimum_components))
        if not self.policy_version.strip() or not self.seed.strip():
            raise ValueError("policy version and seed are required")
        if len(self.a_targets) != 3 or len(self.minimum_components) != 4:
            raise ValueError("targets and minimum component counts have fixed partition order")
        if any(type(value) is not int or value < 0 for value in (*self.a_targets, *self.minimum_components)):
            raise ValueError("targets and minimum counts must be nonnegative integers")
        if self.minimum_components[3] < 1:
            raise ValueError("independent B requires at least one component")
        object.__setattr__(self, "heldout_a_collections", tuple(self.heldout_a_collections))
        if not self.algorithm_revision.strip() or not self.configuration_revision.strip():
            raise ValueError("algorithm and configuration revisions are required")
        if self.algorithm_revision != ALGORITHM_REVISION:
            raise ValueError("unsupported assignment algorithm revision")
        if self.audit_policy_digest and not re.fullmatch(r"[0-9a-f]{64}", self.audit_policy_digest):
            raise ValueError("audit policy digest must be SHA-256 hex")

    @property
    def sha256(self) -> str:
        """Bind all assignment choices, even when resulting partitions coincide."""

        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True, slots=True)
class AssignmentDecision:
    component_id: str
    candidate_scores: tuple[tuple[Partition, int], ...]
    chosen: AssignmentState


@dataclass(frozen=True, slots=True)
class SplitResult:
    assignments: tuple[tuple[str, AssignmentState], ...]
    decisions: tuple[AssignmentDecision, ...]
    reasons: tuple[tuple[str, str], ...]
    incident_counts: tuple[int, int, int, int]
    component_counts: tuple[int, int, int, int]
    feasibility: Literal["feasible", "insufficient_groups"]
    issues: tuple[str, ...]
    plan_sha256: str

    def state_for(self, component_id: str) -> AssignmentState:
        return dict(self.assignments)[component_id]

    def partition_for_artifact(self, graph: LineageGraph, artifact_id: str) -> AssignmentState:
        for component in graph.components():
            if artifact_id in component.artifact_ids:
                return self.state_for(component.component_id)
        raise KeyError(artifact_id)


def _rank(component: Component, graph: LineageGraph, plan: AssignmentPlan) -> tuple[bytes, str]:
    roots = graph.roots(component)
    key = min((root.original_key.namespace, root.original_key.value) for root in roots)
    payload = [plan.policy_version, plan.algorithm_revision, plan.seed, list(key)]
    return hashlib.sha256(canonical_bytes(payload)).digest(), component.component_id


def assign_components(graph: LineageGraph, plan: AssignmentPlan) -> SplitResult:
    """Propose a deterministic whole-component assignment; never freezes data."""

    assignments: dict[str, AssignmentState] = {}
    reasons: list[tuple[str, str]] = []
    decisions: list[AssignmentDecision] = []
    a_components: list[Component] = []
    counts = [0, 0, 0, 0]
    clusters = [0, 0, 0, 0]
    a_pipelines = {
        (record.operator_id, record.pipeline_id)
        for record in graph.records.values()
        if record.kind == "incident" and record.environment == "A"
        and record.operator_id and record.pipeline_id
    }

    for component in graph.components():
        roots = graph.roots(component)
        reason: str | None = None
        state: AssignmentState | None = None
        if not roots or len(component.environments) != 1:
            reason = "missing root or mixed A/B lineage"
            state = "quarantine"
        elif component.missing_metadata:
            reason = "missing provenance: " + ", ".join(component.missing_metadata)
            state = "quarantine"
        elif component.environments == ("B",):
            reviews = {root.b_review for root in roots}
            if component.exposed_to_development or component.has_train_only_derivative:
                reason = "B exposed to development or has train-only derivative"
                state = "quarantine"
            elif any((root.operator_id, root.pipeline_id) in a_pipelines for root in roots):
                reason = "B shares an A operator/pipeline identity"
                state = "quarantine"
            elif reviews == {"reserved"}:
                reason = "B source role reserved"
                state = "reserved"
            elif reviews == {"eligible"}:
                state = "heldout_b"
            else:
                reason = "B independence review not eligible"
                state = "quarantine"
        else:
            a_components.append(component)
        if state is not None:
            assignments[component.component_id] = state
            if reason:
                reasons.append((component.component_id, reason))
            if state == "heldout_b":
                counts[3] += len(roots)
                clusters[3] += 1

    for component in sorted(a_components, key=lambda item: _rank(item, graph, plan)):
        roots = graph.roots(component)
        designated_holdout = bool(set(component.collection_keys) & set(plan.heldout_a_collections))
        if designated_holdout:
            allowed: tuple[Partition, ...] = ("heldout_a",)
        elif component.has_train_only_derivative:
            allowed = ("train",)
        elif component.exposed_to_development:
            allowed = ("train", "validation")
        else:
            allowed = _A_PARTITIONS
        if designated_holdout and (component.has_train_only_derivative or component.exposed_to_development):
            assignments[component.component_id] = "quarantine"
            reasons.append((component.component_id, "held-out collection has development exposure"))
            continue
        size = len(roots)
        scores: list[tuple[Partition, int]] = []
        for partition in allowed:
            index = _A_PARTITIONS.index(partition)
            projected = list(counts[:3])
            projected[index] += size
            scores.append((partition, sum(abs(value - target) for value, target in zip(projected, plan.a_targets))))
        chosen = min(scores, key=lambda item: (item[1], _A_PARTITIONS.index(item[0])))[0]
        assignments[component.component_id] = chosen
        index = PARTITIONS.index(chosen)
        counts[index] += size
        clusters[index] += 1
        decisions.append(AssignmentDecision(component.component_id, tuple(scores), chosen))

    issues = [
        f"{partition}: {clusters[index]} independent components below required {minimum}"
        for index, (partition, minimum) in enumerate(zip(PARTITIONS, plan.minimum_components))
        if clusters[index] < minimum
    ]
    issues.extend(
        f"{partition}: {counts[index]} incidents below target {target}"
        for index, (partition, target) in enumerate(zip(_A_PARTITIONS, plan.a_targets))
        if counts[index] < target
    )
    return SplitResult(
        assignments=tuple(sorted(assignments.items())),
        decisions=tuple(decisions),
        reasons=tuple(sorted(reasons)),
        incident_counts=tuple(counts),
        component_counts=tuple(clusters),
        feasibility="feasible" if not issues else "insufficient_groups",
        issues=tuple(issues),
        plan_sha256=plan.sha256,
    )


Disposition = Literal["unknown", "same_component", "distinct_with_reason", "exclude"]


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Explicit candidate method and review state; references are not signatures."""

    revision: str
    near_threshold: str
    max_pair_comparisons: int
    normalization_version: str = NORMALIZATION_VERSION
    candidate_method: str = CANDIDATE_METHOD
    review_status: Literal["proposed", "owner_reviewed"] = "proposed"
    owner_review_ref: str = ""
    max_intra_duplicate_pairs: int = DEFAULT_MAX_INTRA_DUPLICATE_PAIRS

    def __post_init__(self) -> None:
        if not self.revision.strip():
            raise ValueError("audit revision is required")
        try:
            threshold = Decimal(self.near_threshold)
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("near threshold must be a decimal string") from exc
        if not threshold.is_finite() or not 0 < threshold <= 1:
            raise ValueError("near threshold must be in (0, 1]")
        if type(self.max_pair_comparisons) is not int or self.max_pair_comparisons < 1:
            raise ValueError("comparison limit must be a positive integer")
        if type(self.max_intra_duplicate_pairs) is not int or self.max_intra_duplicate_pairs < 1:
            raise ValueError("intra-partition duplicate limit must be a positive integer")
        if self.normalization_version != NORMALIZATION_VERSION or self.candidate_method != CANDIDATE_METHOD:
            raise ValueError("unsupported audit method; amendment and implementation review required")
        if self.review_status not in ("proposed", "owner_reviewed"):
            raise ValueError("invalid audit review status")
        if self.review_status == "owner_reviewed" and not self.owner_review_ref.strip():
            raise ValueError("owner-reviewed audit policy needs a review reference")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True, slots=True)
class ManualDisposition:
    left_id: str
    right_id: str
    signal: str
    decision: Disposition
    reviewer: str = ""
    reason: str = ""
    evidence_ref: str = ""
    second_reviewer: str = ""

    def __post_init__(self) -> None:
        if self.decision != "unknown" and (not self.reviewer.strip() or not self.reason.strip()):
            raise ValueError("a decided match needs reviewer and reason")

    @property
    def key(self) -> tuple[str, str, str]:
        left, right = sorted((self.left_id, self.right_id))
        return left, right, self.signal


@dataclass(frozen=True, slots=True)
class AuditFinding:
    left_id: str
    right_id: str
    left_partition: AssignmentState
    right_partition: AssignmentState
    signal: str
    disposition: Disposition
    reviewer: str
    reason: str
    similarity: str | None = None

    @property
    def touches_heldout(self) -> bool:
        return self.left_partition.startswith("heldout") or self.right_partition.startswith("heldout")

    @property
    def active_cross_partition(self) -> bool:
        return (self.left_partition in PARTITIONS and self.right_partition in PARTITIONS
                and self.left_partition != self.right_partition)


@dataclass(frozen=True, slots=True)
class AuditReport:
    findings: tuple[AuditFinding, ...]
    unresolved_risks: tuple[AuditFinding, ...]
    holdout_blocked: bool
    subject_sha256: str
    near_threshold: float
    active_blocked: bool = False
    excluded_findings: tuple[AuditFinding, ...] = ()
    audit_policy_digest: str = ""
    dispositions_digest: str = ""
    comparison_count: int = 0
    audit_revision: str = ""
    normalization_version: str = ""
    candidate_method: str = ""
    intra_partition_findings: tuple[AuditFinding, ...] = ()
    unresolved_independence: tuple[AuditFinding, ...] = ()
    independence_blocked: bool = False
    intra_duplicate_pair_count: int = 0

    @property
    def sha256(self) -> str:
        payload = asdict(self)
        payload["near_threshold"] = str(Decimal(str(self.near_threshold)))
        return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _subject_sha256(graph: LineageGraph, split: SplitResult) -> str:
    payload = {"lineage_graph_sha256": graph.lineage_graph_sha256,
               "assignments": list(split.assignments)}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


_INTRA_EXACT_FIELDS = (
    "original_key", "run_key", "concrete_template_key", "collection_key",
    "parent_collection_key", "parent_dataset_key", "source_event_key", "event_hash",
)


def _intra_exact_findings(
    graph: LineageGraph, split: SplitResult, manual: dict[tuple[str, str, str], ManualDisposition],
    max_pairs: int,
) -> tuple[tuple[AuditFinding, ...], int]:
    """Index strong exact signals between components in one active partition."""

    artifact_component = {
        artifact_id: component.component_id
        for component in graph.components() for artifact_id in component.artifact_ids
    }
    index: dict[tuple[str, str, object], list[str]] = {}
    for artifact_id, item in sorted(graph.records.items()):
        state = split.state_for(artifact_component[artifact_id])
        if state not in PARTITIONS:
            continue
        for field in _INTRA_EXACT_FIELDS:
            value = getattr(item, field)
            if value is not None:
                index.setdefault((state, field, value), []).append(artifact_id)
        index.setdefault((state, "incident_scope", (item.tenant_id, item.incident_id)), []).append(artifact_id)
    findings: list[AuditFinding] = []
    pair_count = 0
    for (state, signal, _), ids in sorted(index.items(), key=lambda pair: repr(pair[0])):
        for first_id, second_id in combinations(ids, 2):
            if artifact_component[first_id] == artifact_component[second_id]:
                continue
            pair_count += 1
            if pair_count > max_pairs:
                raise ValueError("intra-partition duplicate limit exceeded; review candidate policy")
            left_id, right_id = sorted((first_id, second_id))
            disposition = manual.get((left_id, right_id, signal))
            decision = disposition.decision if disposition else "unknown"
            if decision == "distinct_with_reason" and (
                not disposition.evidence_ref or not disposition.second_reviewer
                or disposition.second_reviewer == disposition.reviewer
            ):
                decision = "unknown"
            findings.append(AuditFinding(
                left_id, right_id, state, state, signal, decision,
                disposition.reviewer if disposition else "",
                disposition.reason if disposition else "", None,
            ))
    return tuple(sorted(findings, key=lambda item: (item.left_id, item.right_id, item.signal))), pair_count


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _signals(left: LineageRecord, right: LineageRecord, threshold: float) -> list[tuple[str, float | None]]:
    found: list[tuple[str, float | None]] = []
    for field in (
        "incident_id", "run_key", "concrete_template_key", "collection_key",
        "parent_collection_key", "parent_dataset_key", "source_event_key",
        "event_hash", "source_family",
    ):
        a, b = getattr(left, field), getattr(right, field)
        if a is not None and b is not None and a == b:
            found.append((field, None))
    for field in ("evidence_text", "claim_text", "prompt_text"):
        a, b = getattr(left, field), getattr(right, field)
        if not a or not b:
            continue
        normalized_a, normalized_b = _normalize_text(a), _normalize_text(b)
        if normalized_a == normalized_b:
            found.append((f"{field}_exact", 1.0))
        else:
            ratio = SequenceMatcher(None, normalized_a, normalized_b, autojunk=False).ratio()
            if ratio >= threshold:
                found.append((f"{field}_near", ratio))
    return found


def audit_leakage(
    graph: LineageGraph,
    split: SplitResult,
    *,
    near_threshold: float | None = None,
    audit_policy: AuditPolicy | None = None,
    max_pair_comparisons: int | None = None,
    dispositions: tuple[ManualDisposition, ...] = (),
) -> AuditReport:
    """Audit all cross-state pairs within an explicit cost bound.

    The legacy near_threshold-only form yields a proposed, unreviewed policy;
    it cannot pass the freeze gate. It changes no similarity method.
    """

    if audit_policy is None:
        if near_threshold is None:
            raise ValueError("audit policy or explicit near threshold is required")
        audit_policy = AuditPolicy(
            "unreviewed", str(near_threshold),
            DEFAULT_MAX_PAIR_COMPARISONS if max_pair_comparisons is None else max_pair_comparisons,
        )
    elif (near_threshold is not None and Decimal(str(near_threshold)) !=
          Decimal(audit_policy.near_threshold)):
        raise ValueError("near threshold conflicts with the audit policy")
    elif (max_pair_comparisons is not None and
          max_pair_comparisons != audit_policy.max_pair_comparisons):
        raise ValueError("comparison limit conflicts with the audit policy")
    threshold = float(Decimal(audit_policy.near_threshold))
    manual = {item.key: item for item in dispositions}
    if len(manual) != len(dispositions):
        raise ValueError("manual dispositions must have unique pair/signal keys")
    partitions = {
        artifact_id: split.state_for(component.component_id)
        for component in graph.components()
        for artifact_id in component.artifact_ids
    }
    state_counts = Counter(partitions.values())
    comparison_count = (
        len(partitions) ** 2 - sum(count ** 2 for count in state_counts.values())
    ) // 2
    if comparison_count > audit_policy.max_pair_comparisons:
        raise ValueError(
            f"audit comparison limit exceeded: {comparison_count} > "
            f"{audit_policy.max_pair_comparisons}; candidate indexing requires owner review"
        )
    findings: list[AuditFinding] = []
    observed_keys: set[tuple[str, str, str]] = set()
    by_state: dict[AssignmentState, list[str]] = {}
    for artifact_id, state in sorted(partitions.items()):
        by_state.setdefault(state, []).append(artifact_id)
    for state_a, state_b in combinations(sorted(by_state), 2):
        for first_id in by_state[state_a]:
            for second_id in by_state[state_b]:
                left_id, right_id = sorted((first_id, second_id))
                left_partition, right_partition = partitions[left_id], partitions[right_id]
                left, right = graph.records[left_id], graph.records[right_id]
                for signal, similarity in _signals(left, right, threshold):
                    observed_keys.add((left_id, right_id, signal))
                    disposition = manual.get((left_id, right_id, signal))
                    decision = disposition.decision if disposition else "unknown"
                    active = left_partition in PARTITIONS and right_partition in PARTITIONS
                    if (active and signal != "source_family" and decision == "distinct_with_reason"
                            and (not disposition.evidence_ref or not disposition.second_reviewer
                                 or disposition.second_reviewer == disposition.reviewer)):
                        decision = "unknown"
                    findings.append(AuditFinding(
                        left_id, right_id, left_partition, right_partition, signal,
                        decision,
                        disposition.reviewer if disposition else "",
                        disposition.reason if disposition else "",
                        format(similarity, ".17g") if similarity is not None else None,
                    ))
    findings.sort(key=lambda item: (item.left_id, item.right_id, item.signal))
    intra, intra_pair_count = _intra_exact_findings(
        graph, split, manual, audit_policy.max_intra_duplicate_pairs
    )
    observed_keys.update((item.left_id, item.right_id, item.signal) for item in intra)
    if set(manual) - observed_keys:
        raise ValueError("manual disposition does not match an observed audit finding")
    unresolved = tuple(
        item for item in findings
        if item.active_cross_partition and item.disposition == "unknown"
        and item.signal != "source_family"
    )
    unwaivable = {
        "incident_id", "run_key", "concrete_template_key", "collection_key",
        "parent_collection_key", "source_event_key",
    }
    active_blocked = any(
        item.active_cross_partition and item.signal != "source_family" and (
            item.signal in unwaivable or item.disposition != "distinct_with_reason"
        )
        for item in findings
    )
    holdout_blocked = any(
        item.active_cross_partition and item.touches_heldout
        and item.signal != "source_family"
        and (item.signal in unwaivable or item.disposition != "distinct_with_reason")
        for item in findings
    )
    disposition_payload = [asdict(item) for item in sorted(dispositions, key=lambda item: item.key)]
    return AuditReport(
        tuple(findings), unresolved, holdout_blocked, _subject_sha256(graph, split), threshold,
        active_blocked,
        tuple(item for item in findings if not item.active_cross_partition),
        audit_policy.sha256,
        hashlib.sha256(canonical_bytes(disposition_payload)).hexdigest(),
        comparison_count,
        audit_policy.revision,
        audit_policy.normalization_version,
        audit_policy.candidate_method,
        intra,
        tuple(item for item in intra if item.disposition != "distinct_with_reason"),
        any(item.disposition != "distinct_with_reason" for item in intra),
        intra_pair_count,
    )


@dataclass(frozen=True, slots=True)
class StructuralStratum:
    partition: Partition
    component_count: int
    incident_count: int
    component_sizes: tuple[int, ...]
    source_families: tuple[str, ...]
    source_family_component_counts: tuple[tuple[str, int], ...]
    collection_keys: tuple[GroupKey, ...]
    collection_component_counts: tuple[tuple[GroupKey, int], ...]
    largest_component_share: float | None


def structural_audit(graph: LineageGraph, split: SplitResult) -> tuple[StructuralStratum, ...]:
    """Restricted, non-label design audit. Never pass exact B detail to development."""

    strata = []
    for partition in PARTITIONS:
        components = [
            item for item in graph.components() if split.state_for(item.component_id) == partition
        ]
        sizes = tuple(sorted((len(graph.roots(item)) for item in components), reverse=True))
        total = sum(sizes)
        family_counts = Counter(
            family for item in components for family in item.source_families
        )
        collection_counts = Counter(
            key for item in components for key in item.collection_keys
        )
        strata.append(StructuralStratum(
            partition, len(components), total, sizes,
            tuple(sorted(family_counts)), tuple(sorted(family_counts.items())),
            tuple(sorted(collection_counts)), tuple(sorted(collection_counts.items())),
            sizes[0] / total if total else None,
        ))
    return tuple(strata)


def proposed_split_manifest(
    graph: LineageGraph, split: SplitResult, plan: AssignmentPlan,
    audit: AuditReport | None = None,
) -> Manifest:
    """Build a private proposal containing exact IDs; caller must restrict storage."""

    if split.plan_sha256 != plan.sha256:
        raise ValueError("assignment was produced under a different plan")
    if audit is not None and audit.subject_sha256 != _subject_sha256(graph, split):
        raise ValueError("audit does not match the proposed split")
    entries = []
    for component in graph.components():
        records = [asdict(graph.records[artifact_id]) for artifact_id in component.artifact_ids]
        lineage_hash = hashlib.sha256(canonical_bytes(records)).hexdigest()
        incident_scopes = [
            {"incident_id": root.incident_id, "tenant_id": root.tenant_id}
            for root in graph.roots(component)
        ]
        entries.append({
            "component_id": component.component_id,
            "partition": split.state_for(component.component_id),
            "artifact_ids": list(component.artifact_ids),
            "incident_count": len(incident_scopes),
            "incidents": sorted(incident_scopes, key=lambda item: (item["tenant_id"], item["incident_id"])),
            "lineage_sha256": lineage_hash,
            "missing_metadata": list(component.missing_metadata),
        })
    metadata = {
        "assignment_plan": asdict(plan),
        "assignment_plan_sha256": plan.sha256,
        "audit_report_sha256": audit.sha256 if audit is not None else None,
        "review_registry_sha256": graph.review_registry_sha256,
        "review_registry_version": graph.review_registry_version,
        "review_predecessor_sha256": graph.review_predecessor_sha256,
        "lineage_graph_sha256": graph.lineage_graph_sha256,
    }
    return Manifest.proposed(plan.policy_version, entries, metadata=metadata)


def freeze_split_manifest(
    manifest: Manifest,
    graph: LineageGraph,
    split: SplitResult,
    plan: AssignmentPlan,
    audit: AuditReport,
    approval: FreezeApproval,
    *,
    audit_policy: AuditPolicy | None = None,
    dispositions: tuple[ManualDisposition, ...] = (),
) -> Manifest:
    """Recompute plan/audit gates; external references are not authorization."""

    if audit_policy is None or audit_policy.review_status != "owner_reviewed":
        raise ValueError("audit method is pending owner review")
    if plan.audit_policy_digest != audit_policy.sha256 or plan.configuration_revision == "unreviewed":
        raise ValueError("plan has no matching reviewed audit/configuration revision")
    if split != assign_components(graph, plan):
        raise ValueError("assignment is stale or differs from the current plan")
    recomputed_audit = audit_leakage(
        graph, split, audit_policy=audit_policy, dispositions=dispositions
    )
    if audit != recomputed_audit:
        raise ValueError("audit report differs from recomputed findings or policy")
    if manifest.sha256 != proposed_split_manifest(graph, split, plan, audit).sha256:
        raise ValueError("manifest does not match current lineage and assignment")
    if (split.feasibility != "feasible" or audit.active_blocked or audit.unresolved_risks
            or audit.independence_blocked):
        raise ValueError("split is infeasible or material leakage/independence risk remains")
    return manifest._freeze_after_verified_gates(approval)
