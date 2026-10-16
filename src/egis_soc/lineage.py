"""W1-07 sidecar lineage. These records do not change W1-03 schemas.

Keys are reviewer-supplied, source-namespaced identities. A broad scenario
family is an audit attribute, never an automatic connected-component edge.
This module handles structure only; it cannot attest source provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

from .integrity import canonical_bytes


Environment = Literal["A", "B"]
ArtifactKind = Literal[
    "incident", "event", "snapshot", "draft", "claim", "pair", "mutation",
    "counterfactual", "perturbation", "operational_fact", "gold_fact", "report", "s2_fork",
]
BReview = Literal["eligible", "reserved", "unknown", "ineligible"]


def _nonblank(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonblank")


@dataclass(frozen=True, order=True, slots=True)
class GroupKey:
    """A source-namespaced exact identity, never a fuzzy scenario label."""

    namespace: str
    value: str

    def __post_init__(self) -> None:
        _nonblank(self.namespace, "namespace")
        _nonblank(self.value, "value")


@dataclass(frozen=True, slots=True)
class LineageRecord:
    artifact_id: str
    kind: ArtifactKind
    incident_id: str
    tenant_id: str
    environment: Environment
    parent_ids: tuple[str, ...] = ()
    original_key: GroupKey | None = None
    simulation_status: Literal["simulated", "not_applicable", "unknown"] = "unknown"
    run_key: GroupKey | None = None
    concrete_template_key: GroupKey | None = None
    collection_key: GroupKey | None = None
    parent_collection_key: GroupKey | None = None
    parent_dataset_key: GroupKey | None = None
    parent_dataset_status: Literal["known", "none_attested", "unknown"] = "unknown"
    source_event_key: GroupKey | None = None
    source_family: str | None = None
    operator_id: str | None = None
    pipeline_id: str | None = None
    rights_status: Literal["cleared", "unknown", "blocked"] = "unknown"
    rights_basis: Literal["independent", "inherited", "unresolved"] = "unresolved"
    rights_evidence_ref: str | None = None
    rights_inherited_from: str | None = None
    b_review: BReview | None = None
    b_review_reference: str | None = None
    exposed_to_development: bool = False
    event_hash: str | None = None
    evidence_text: str | None = None
    claim_text: str | None = None
    prompt_text: str | None = None

    def __post_init__(self) -> None:
        for name in ("artifact_id", "incident_id", "tenant_id"):
            _nonblank(getattr(self, name), name)
        if self.environment not in ("A", "B"):
            raise ValueError("environment must be A or B")
        if self.kind not in ArtifactKind.__args__:
            raise ValueError("unsupported artifact kind")
        for name in (
            "original_key", "run_key", "concrete_template_key", "collection_key",
            "parent_collection_key", "parent_dataset_key", "source_event_key",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, GroupKey):
                raise ValueError(f"{name} must be a GroupKey")
        for name in ("source_family", "operator_id", "pipeline_id", "b_review_reference",
                     "rights_evidence_ref", "rights_inherited_from"):
            value = getattr(self, name)
            if value is not None:
                _nonblank(value, name)
        parents = tuple(self.parent_ids)
        if len(parents) != len(set(parents)) or self.artifact_id in parents:
            raise ValueError("parent IDs must be unique and cannot self-reference")
        for parent in parents:
            _nonblank(parent, "parent ID")
        object.__setattr__(self, "parent_ids", parents)
        if self.kind == "incident" and parents:
            raise ValueError("original incident cannot have artifact parents")
        if self.kind != "incident" and not parents:
            raise ValueError("derived artifact requires an explicit parent")
        if self.event_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", self.event_hash):
            raise ValueError("event_hash must be lowercase SHA-256 hex")
        if self.kind == "incident" and self.environment == "B" and self.b_review is None:
            raise ValueError("B incident must have an explicit review state")
        if self.b_review == "eligible" and not self.b_review_reference:
            raise ValueError("eligible B requires a review reference")
        if self.simulation_status not in ("simulated", "not_applicable", "unknown"):
            raise ValueError("invalid simulation status")
        if self.rights_status not in ("cleared", "unknown", "blocked"):
            raise ValueError("invalid rights status")
        if self.rights_basis not in ("independent", "inherited", "unresolved"):
            raise ValueError("invalid rights basis")
        if self.rights_inherited_from is not None and self.rights_inherited_from not in parents:
            raise ValueError("rights inheritance must name a direct parent")
        if self.parent_dataset_status not in ("known", "none_attested", "unknown"):
            raise ValueError("invalid parent dataset status")
        if self.b_review is not None and self.b_review not in (
            "eligible", "reserved", "unknown", "ineligible"
        ):
            raise ValueError("invalid B review state")


@dataclass(frozen=True, slots=True)
class ReviewedLink:
    """An accepted ancestry edge supported by a separate human review record."""

    left_id: str
    right_id: str
    relation: Literal["same_original", "same_run", "concrete_template", "collection", "copy"]
    evidence_ref: str
    reviewer: str

    def __post_init__(self) -> None:
        for name in ("left_id", "right_id", "evidence_ref", "reviewer"):
            _nonblank(getattr(self, name), name)
        if self.left_id == self.right_id:
            raise ValueError("link endpoints must differ")
        if self.relation not in (
            "same_original", "same_run", "concrete_template", "collection", "copy"
        ):
            raise ValueError("unknown reviewed link relation")


@dataclass(frozen=True, slots=True)
class Component:
    component_id: str
    artifact_ids: tuple[str, ...]
    incident_ids: tuple[str, ...]
    environments: tuple[Environment, ...]
    source_families: tuple[str, ...]
    collection_keys: tuple[GroupKey, ...]
    missing_metadata: tuple[str, ...]
    has_train_only_derivative: bool
    exposed_to_development: bool


class LineageGraph:
    """Deterministic connected components over exact keys, parents and reviewed links."""

    _GROUP_FIELDS = ("original_key", "run_key", "concrete_template_key", "source_event_key")
    _REQUIRED_ROOT_FIELDS = ("original_key", "collection_key", "source_family", "operator_id", "pipeline_id")

    def __init__(
        self, records: tuple[LineageRecord, ...] | list[LineageRecord],
        reviewed_links: tuple[ReviewedLink, ...] | list[ReviewedLink] = (),
        *,
        review_registry_version: str = "unreviewed-v1",
        review_predecessor_sha256: str | None = None,
        review_history: tuple[ReviewedLink, ...] | list[ReviewedLink] = (),
    ) -> None:
        items = tuple(records)
        self.records = {item.artifact_id: item for item in items}
        if len(self.records) != len(items):
            raise ValueError("artifact IDs must be globally unique")
        self.reviewed_links = tuple(reviewed_links)
        self.review_history = tuple(review_history)
        _nonblank(review_registry_version, "review registry version")
        if (review_predecessor_sha256 is not None and
                not re.fullmatch(r"[0-9a-f]{64}", review_predecessor_sha256)):
            raise ValueError("review predecessor must be SHA-256 hex")
        if self.review_history and review_predecessor_sha256 is None:
            raise ValueError("retained review history needs a predecessor registry digest")
        self.review_registry_version = review_registry_version
        self.review_predecessor_sha256 = review_predecessor_sha256
        for item in items:
            for parent_id in item.parent_ids:
                parent = self.records.get(parent_id)
                if parent is None:
                    raise ValueError(f"unknown parent: {parent_id}")
                if (parent.incident_id, parent.tenant_id, parent.environment) != (
                    item.incident_id, item.tenant_id, item.environment
                ):
                    raise ValueError("parent and descendant scope/environment differ")
        for link in self.reviewed_links:
            if link.left_id not in self.records or link.right_id not in self.records:
                raise ValueError("reviewed link references unknown artifact")
        self._check_cycles()
        self._check_inherited_originals()

    @property
    def review_registry_sha256(self) -> str:
        """Bind accepted links and retained history; references are not signatures."""

        def ordered(links: tuple[ReviewedLink, ...]) -> list[dict[str, str]]:
            return [asdict(link) for link in sorted(
                links, key=lambda link: (
                    min(link.left_id, link.right_id), max(link.left_id, link.right_id),
                    link.relation, link.evidence_ref, link.reviewer,
                ),
            )]

        payload = {
            "version": self.review_registry_version,
            "predecessor_sha256": self.review_predecessor_sha256,
            "accepted_links": ordered(self.reviewed_links),
            "review_history": ordered(self.review_history),
        }
        return hashlib.sha256(canonical_bytes(payload)).hexdigest()

    @property
    def lineage_graph_sha256(self) -> str:
        payload = {
            "records": [asdict(self.records[artifact_id]) for artifact_id in sorted(self.records)],
            "review_registry_sha256": self.review_registry_sha256,
        }
        return hashlib.sha256(canonical_bytes(payload)).hexdigest()

    def _check_cycles(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(artifact_id: str) -> None:
            if artifact_id in visiting:
                raise ValueError("artifact parent cycle")
            if artifact_id in visited:
                return
            visiting.add(artifact_id)
            for parent_id in self.records[artifact_id].parent_ids:
                visit(parent_id)
            visiting.remove(artifact_id)
            visited.add(artifact_id)

        for artifact_id in sorted(self.records):
            visit(artifact_id)

    def _check_inherited_originals(self) -> None:
        known: dict[str, set[GroupKey]] = {}

        def originals(artifact_id: str) -> set[GroupKey]:
            if artifact_id in known:
                return known[artifact_id]
            item = self.records[artifact_id]
            inherited = (
                {item.original_key} if item.kind == "incident" and item.original_key else set()
            )
            for parent_id in item.parent_ids:
                inherited.update(originals(parent_id))
            if item.kind != "incident" and len(inherited) > 1:
                raise ValueError("descendant has multiple original incidents")
            if item.kind != "incident" and item.original_key and item.original_key not in inherited:
                raise ValueError("descendant original key conflicts with its parents")
            known[artifact_id] = inherited
            return inherited

        for artifact_id in sorted(self.records):
            originals(artifact_id)

    def components(self) -> tuple[Component, ...]:
        parent = {artifact_id: artifact_id for artifact_id in self.records}

        def find(artifact_id: str) -> str:
            while parent[artifact_id] != artifact_id:
                parent[artifact_id] = parent[parent[artifact_id]]
                artifact_id = parent[artifact_id]
            return artifact_id

        def join(left: str, right: str) -> None:
            a, b = find(left), find(right)
            if a != b:
                parent[max(a, b)] = min(a, b)

        seen: dict[tuple[str, GroupKey], str] = {}
        for artifact_id, record in sorted(self.records.items()):
            for parent_id in record.parent_ids:
                join(artifact_id, parent_id)
            for field in self._GROUP_FIELDS:
                key = getattr(record, field)
                if key is not None:
                    typed = (field, key)
                    if typed in seen:
                        join(artifact_id, seen[typed])
                    else:
                        seen[typed] = artifact_id
            # A collection and its documented parent use one lineage key space.
            for key in (record.collection_key, record.parent_collection_key):
                if key is not None:
                    typed = ("collection_lineage", key)
                    if typed in seen:
                        join(artifact_id, seen[typed])
                    else:
                        seen[typed] = artifact_id
        for link in self.reviewed_links:
            join(link.left_id, link.right_id)

        groups: dict[str, list[LineageRecord]] = {}
        for artifact_id, record in sorted(self.records.items()):
            groups.setdefault(find(artifact_id), []).append(record)
        result: list[Component] = []
        for group in groups.values():
            ids = tuple(sorted(item.artifact_id for item in group))
            digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
            roots = [item for item in group if item.kind == "incident"]
            missing = {
                f"{item.artifact_id}:{field}"
                for item in roots
                for field in self._REQUIRED_ROOT_FIELDS
                if getattr(item, field) is None or getattr(item, field) == ""
            }
            for item in roots:
                if item.parent_dataset_status == "unknown":
                    missing.add(f"{item.artifact_id}:parent_dataset_status")
                elif item.parent_dataset_status == "known" and item.parent_dataset_key is None:
                    missing.add(f"{item.artifact_id}:parent_dataset_key")
                if item.simulation_status == "unknown":
                    missing.add(f"{item.artifact_id}:simulation_status")
                elif item.simulation_status == "simulated":
                    for field in ("run_key", "concrete_template_key"):
                        if getattr(item, field) is None:
                            missing.add(f"{item.artifact_id}:{field}")
            rights_ok: dict[str, bool] = {}

            def cleared(artifact_id: str) -> bool:
                if artifact_id in rights_ok:
                    return rights_ok[artifact_id]
                item = self.records[artifact_id]
                if item.rights_status == "blocked":
                    result = False
                elif item.rights_basis == "independent":
                    result = item.rights_status == "cleared" and bool(item.rights_evidence_ref)
                elif item.rights_basis == "inherited":
                    result = (item.rights_status == "unknown" and bool(item.rights_evidence_ref)
                              and item.rights_inherited_from in item.parent_ids
                              and cleared(item.rights_inherited_from))
                else:
                    result = False
                rights_ok[artifact_id] = result
                return result

            for item in group:
                if not cleared(item.artifact_id):
                    missing.add(f"{item.artifact_id}:rights_{item.rights_status}_{item.rights_basis}")
                if item.kind == "event" and item.source_event_key is None:
                    missing.add(f"{item.artifact_id}:source_event_key")
                if item.kind in ("event", "snapshot") and item.event_hash is None:
                    missing.add(f"{item.artifact_id}:event_hash")
            result.append(Component(
                component_id=f"sha256:{digest}",
                artifact_ids=ids,
                incident_ids=tuple(sorted({item.incident_id for item in roots})),
                environments=tuple(sorted({item.environment for item in roots})),
                source_families=tuple(sorted({item.source_family for item in roots if item.source_family})),
                collection_keys=tuple(sorted({item.collection_key for item in roots if item.collection_key})),
                missing_metadata=tuple(sorted(missing)),
                has_train_only_derivative=any(
                    item.kind in ("mutation", "counterfactual") for item in group
                ),
                exposed_to_development=any(item.exposed_to_development for item in group),
            ))
        return tuple(sorted(result, key=lambda component: component.component_id))

    def roots(self, component: Component) -> tuple[LineageRecord, ...]:
        return tuple(
            self.records[artifact_id]
            for artifact_id in component.artifact_ids
            if self.records[artifact_id].kind == "incident"
        )
