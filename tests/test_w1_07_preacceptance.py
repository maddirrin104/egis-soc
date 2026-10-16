"""Synthetic reproductions for W1-07 F-01 through F-09.

Each case was added before changing the corresponding implementation. No
acquired incident, sealed test item, gold label, or experiment is used.
"""

import hashlib
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from egis_soc.evaluation_boundary import (
    AccessGrant,
    EvaluationStore,
    OperationalFact,
    VerifierInputIdentity,
    build_inference_input,
    verify_shared_v2_v3_inputs,
)
from egis_soc.integrity import FreezeApproval, Manifest, canonical_bytes
from egis_soc.lineage import LineageGraph
from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, EvaluationGoldRecord, IncidentBundle
from egis_soc.split_freeze import (
    AssignmentPlan,
    AuditPolicy,
    ManualDisposition,
    assign_components,
    audit_leakage,
    freeze_split_manifest,
    proposed_split_manifest,
)
from test_split_freeze import child, incident, key, standard_graph


def approval() -> FreezeApproval:
    # Placeholder references are synthetic test data, never real approvals.
    return FreezeApproval("synthetic-owner", "synthetic-reviewer", "synthetic-access", "synthetic-lock")


def reviewed_policy(threshold: str = "0.9") -> AuditPolicy:
    # A synthetic state for gate tests, not an actual owner decision.
    return AuditPolicy("synthetic-audit-v1", threshold, 1000,
                       review_status="owner_reviewed", owner_review_ref="synthetic-review")


def configured_active(overlap: str = "train_validation"):
    graph, plan, _ = active_graph(overlap=overlap)
    policy = reviewed_policy()
    plan = replace(plan, configuration_revision="synthetic-config-v1",
                   audit_policy_digest=policy.sha256)
    return graph, plan, assign_components(graph, plan), policy


def active_graph(*, overlap: str = "train_validation"):
    train = incident(101)
    validation = incident(102, exposed_to_development=True)
    heldout = incident(103)
    b = incident(104, environment="B")
    mutation = child(train, "synthetic-mutation", "mutation")
    shared_hash = hashlib.sha256(b"synthetic shared event").hexdigest()
    left = child(train, "synthetic-train-event", event_hash=shared_hash)
    right_parent = validation if overlap == "train_validation" else heldout
    right = child(right_parent, "synthetic-other-event", event_hash=shared_hash)
    graph = LineageGraph([train, validation, heldout, b, mutation, left, right])
    plan = AssignmentPlan("synthetic-policy", "seed-2", (1, 1, 1), (1, 1, 1, 1),
                          (heldout.collection_key,))
    split = assign_components(graph, plan)
    assert split.feasibility == "feasible"
    assert split.partition_for_artifact(graph, train.artifact_id) == "train"
    assert split.partition_for_artifact(graph, validation.artifact_id) == "validation"
    assert split.partition_for_artifact(graph, heldout.artifact_id) == "heldout_a"
    return graph, plan, split


def synthetic_evidence():
    text = "synthetic evidence"
    digest = hashlib.sha256(text.encode()).hexdigest()
    provenance = EvidenceProvenance(
        source="synthetic", timestamp_utc=datetime(2026, 10, 16, tzinfo=timezone.utc),
        raw_message=text, raw_message_ref="synthetic:raw", sha256=digest,
        acquisition_method="synthetic-fixture",
    )
    event = EvidenceEvent(evidence_id="E1", incident_id="INC-1", tenant_id="TENANT-SYN",
                          normalized_fields={}, provenance=provenance)
    bundle = IncidentBundle(
        incident_id="INC-1", tenant_id="TENANT-SYN", environment_id="A",
        source_dataset="synthetic", scenario_family="synthetic",
        alert_ids=("A1",), evidence_ids=("E1", "E2"),
    )
    return digest, event, bundle


class PreAcceptanceRegressions(unittest.TestCase):
    def test_f01_descendant_development_exposure_quarantines_b(self):
        root = incident(201, environment="B")
        exposed = child(root, "synthetic-exposed-draft", "draft",
                        exposed_to_development=True)
        graph = LineageGraph([root, exposed])
        plan = AssignmentPlan("synthetic-policy", "seed", (0, 0, 0), (0, 0, 0, 1))
        self.assertTrue(graph.components()[0].exposed_to_development)
        self.assertEqual(assign_components(graph, plan).partition_for_artifact(
            graph, root.artifact_id), "quarantine")

    def test_f02_unresolved_train_validation_overlap_blocks_freeze(self):
        graph, plan, split, policy = configured_active()
        report = audit_leakage(graph, split, audit_policy=policy)
        self.assertTrue(any(item.signal == "event_hash" and {
            item.left_partition, item.right_partition
        } == {"train", "validation"} for item in report.findings))
        self.assertTrue(report.active_blocked)
        self.assertFalse(report.holdout_blocked)
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, report, approval(), audit_policy=policy)

    def test_f02_excluded_candidate_is_reported_separately_from_active_leakage(self):
        roots, event, _, base_plan = standard_graph()
        excluded_root = incident(110, rights_status="unknown")
        excluded_event = child(excluded_root, "excluded-event", event_hash=event.event_hash)
        graph = LineageGraph([*roots, event, excluded_root, excluded_event])
        policy = reviewed_policy()
        plan = replace(base_plan, configuration_revision="synthetic-config-v1",
                       audit_policy_digest=policy.sha256)
        split = assign_components(graph, plan)
        self.assertEqual(split.partition_for_artifact(graph, event.artifact_id), "train")
        self.assertEqual(split.partition_for_artifact(graph, excluded_root.artifact_id),
                         "quarantine")
        report = audit_leakage(graph, split, audit_policy=policy)
        self.assertTrue(any(item.signal == "event_hash" for item in report.excluded_findings))
        self.assertFalse(report.active_blocked)
        self.assertFalse(report.unresolved_risks)
        frozen = freeze_split_manifest(
            proposed_split_manifest(graph, split, plan, report), graph, split, plan,
            report, approval(), audit_policy=policy,
        )
        self.assertEqual(frozen.lifecycle, "frozen")

    def test_f03_forged_audit_boolean_and_findings_cannot_bypass_freeze(self):
        graph, plan, split, policy = configured_active(overlap="train_heldout")
        report = audit_leakage(graph, split, audit_policy=policy)
        self.assertTrue(report.holdout_blocked)
        boolean_only = replace(report, holdout_blocked=False, active_blocked=False)
        with self.assertRaisesRegex(ValueError, "audit report differs"):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, boolean_only, approval(), audit_policy=policy)
        forged = replace(report, holdout_blocked=False, active_blocked=False,
                         unresolved_risks=(), findings=())
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, forged, approval(), audit_policy=policy)

    def test_f03_direct_manifest_freeze_cannot_skip_split_audit(self):
        graph, plan, split, policy = configured_active(overlap="train_heldout")
        report = audit_leakage(graph, split, audit_policy=policy)
        self.assertTrue(report.active_blocked)
        proposed = proposed_split_manifest(graph, split, plan, report)
        with self.assertRaises(ValueError):
            proposed.freeze(approval(), gates_passed=True)

    def test_f04_manifest_changes_when_plan_changes_without_assignment_change(self):
        a, b = incident(301), incident(302, environment="B")
        graph = LineageGraph([a, b])
        first = AssignmentPlan("synthetic-policy", "seed-one", (1, 0, 0), (1, 0, 0, 1))
        second = replace(first, seed="seed-two")
        split_a, split_b = assign_components(graph, first), assign_components(graph, second)
        self.assertEqual(split_a.assignments, split_b.assignments)
        self.assertNotEqual(proposed_split_manifest(graph, split_a, first).sha256,
                            proposed_split_manifest(graph, split_b, second).sha256)
        base_digest = proposed_split_manifest(graph, split_a, first).sha256
        for variant in (
            replace(first, a_targets=(2, 0, 0)),
            replace(first, minimum_components=(0, 0, 0, 1)),
            replace(first, heldout_a_collections=(key("collection", "unrelated"),)),
            replace(first, policy_version="synthetic-policy-2"),
            replace(first, configuration_revision="synthetic-config-v2"),
            replace(first, audit_policy_digest="a" * 64),
        ):
            with self.subTest(variant=variant):
                other_split = assign_components(graph, variant)
                self.assertEqual(split_a.assignments, other_split.assignments)
                self.assertNotEqual(base_digest,
                                    proposed_split_manifest(graph, other_split, variant).sha256)
        with self.assertRaises(ValueError):
            replace(first, algorithm_revision="unimplemented-algorithm-v2")

    def test_f05_gold_read_rejects_wrong_partition_and_incident_scope(self):
        gold = EvaluationGoldRecord(incident_id="INC-1", tenant_id="TENANT-SYN",
                                    evidence_ids=("E1",), gold_facts=())
        root = incident(701, environment="B", incident_id="INC-1")
        graph = LineageGraph([root])
        policy = reviewed_policy()
        plan = AssignmentPlan("synthetic-policy", "seed", (0, 0, 0), (0, 0, 0, 1),
                              configuration_revision="synthetic-config-v1",
                              audit_policy_digest=policy.sha256)
        split = assign_components(graph, plan)
        audit = audit_leakage(graph, split, audit_policy=policy)
        manifest = freeze_split_manifest(
            proposed_split_manifest(graph, split, plan, audit), graph, split, plan,
            audit, approval(), audit_policy=policy,
        )
        store = EvaluationStore(manifest, {("TENANT-SYN", "INC-1"): gold})
        grant = AccessGrant(manifest.manifest_id, "synthetic-owner", "synthetic-custodian",
                            "evaluation", "heldout_b", (("TENANT-SYN", "INC-1"),))
        with self.assertRaises(PermissionError):
            store.read_gold("INC-1", tenant_id="TENANT-SYN", partition="train",
                            role="evaluator", grant=grant)
        with self.assertRaises(PermissionError):
            store.read_gold("INC-1", tenant_id="OTHER", partition="heldout_b",
                            role="evaluator", grant=grant)
        with self.assertRaises(PermissionError):
            store.read_gold("INC-1", tenant_id="TENANT-SYN", partition="heldout_b",
                            role="evaluator", grant=replace(grant, authorized_incidents=()))
        with self.assertRaises(ValueError):
            EvaluationStore(manifest, {("OTHER", "INC-1"): gold})
        generic = Manifest.proposed("synthetic-policy", [{
            "component_id": "generic", "partition": "heldout_b",
            "incidents": [{"tenant_id": "TENANT-SYN", "incident_id": "INC-1"}],
        }])
        generic_data = generic.data
        generic_data["lifecycle"] = "frozen"
        generic_data["approval"] = {"owner_ref": "synthetic"}
        generic_bytes = canonical_bytes(generic_data)
        generic_frozen = Manifest(generic_bytes, hashlib.sha256(generic_bytes).hexdigest())
        with self.assertRaises(ValueError):
            EvaluationStore(generic_frozen, {("TENANT-SYN", "INC-1"): gold})
        self.assertIs(store.read_gold("INC-1", tenant_id="TENANT-SYN",
                                      partition="heldout_b", role="evaluator", grant=grant), gold)

    def test_f06_operational_fact_requires_actually_supplied_evidence(self):
        _, event, bundle = synthetic_evidence()
        fact = OperationalFact("OP-1", "INC-1", "TENANT-SYN", "synthetic fact", ("E2",))
        graph = LineageGraph([incident(1)])
        plan = AssignmentPlan("synthetic-policy", "seed", (1, 0, 0), (1, 0, 0, 1))
        manifest = proposed_split_manifest(graph, assign_components(graph, plan), plan)
        with self.assertRaises(ValueError):
            build_inference_input(bundle, (event,), (fact,), partition="train",
                                  role="development", manifest=manifest)

    def test_f07_verifier_claim_and_serialized_payload_identity(self):
        evidence_bytes = b"synthetic evidence serialization"
        threshold_bytes = b"synthetic threshold serialization"
        claim = "synthetic claim"
        payload = canonical_bytes([{"pair_id": "P1", "claim": claim, "evidence_ids": ["E1"]}])
        common = dict(ordered_pair_ids=("P1",), evidence_ids_by_pair=(("E1",),),
                      serialized_evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
                      nli_checkpoint="synthetic-nli",
                      shared_thresholds_sha256=hashlib.sha256(threshold_bytes).hexdigest(),
                      ordered_claim_texts=(claim,), ordered_claim_evidence_payload=payload,
                      serialized_evidence=evidence_bytes,
                      shared_thresholds_payload=threshold_bytes)
        v2 = VerifierInputIdentity("V2", **common)
        different_claim = "different synthetic claim"
        different_payload = canonical_bytes([{"pair_id": "P1", "claim": different_claim,
                                              "evidence_ids": ["E1"]}])
        v3 = VerifierInputIdentity("V3", **(common | {
            "ordered_claim_texts": (different_claim,),
            "ordered_claim_evidence_payload": different_payload,
        }))
        with self.assertRaises(ValueError):
            verify_shared_v2_v3_inputs(v2, v3)
        with self.assertRaises(ValueError):
            replace(v2, serialized_evidence=b"different bytes")
        different_evidence = b"different evidence serialization"
        v3_evidence = replace(
            v2, arm="V3", serialized_evidence=different_evidence,
            serialized_evidence_sha256=hashlib.sha256(different_evidence).hexdigest(),
        )
        with self.assertRaises(ValueError):
            verify_shared_v2_v3_inputs(v2, v3_evidence)

    def test_f08_large_near_duplicate_audit_has_explicit_cost_limit(self):
        roots = [incident(400 + index) for index in range(12)]
        graph = LineageGraph(roots + [incident(499, environment="B")])
        plan = AssignmentPlan("synthetic-policy", "seed", (6, 3, 3), (1, 1, 1, 1))
        split = assign_components(graph, plan)
        # No implicit unbounded all-pairs scan may proceed past a small budget.
        with self.assertRaises(ValueError):
            audit_leakage(graph, split, near_threshold=0.9, max_pair_comparisons=10)

    def test_f08_budgeted_synthetic_near_audit_cost_and_candidate_strategy(self):
        roots = [incident(500 + index, claim_text=f"synthetic claim for host {index:03d}")
                 for index in range(50)]
        graph = LineageGraph(roots + [incident(599, environment="B")])
        plan = AssignmentPlan("synthetic-policy", "seed", (25, 15, 10), (1, 1, 1, 1))
        split = assign_components(graph, plan)
        start = time.perf_counter()
        report = audit_leakage(graph, split, near_threshold=0.9,
                               max_pair_comparisons=1000)
        elapsed = time.perf_counter() - start
        states = [state for _, state in split.assignments]
        counts = {state: states.count(state) for state in set(states)}
        expected_pairs = (len(states) ** 2 - sum(count ** 2 for count in counts.values())) // 2
        self.assertEqual(report.comparison_count, expected_pairs)
        self.assertLessEqual(report.comparison_count, 1000)
        self.assertLess(elapsed, 10.0)  # Diagnostic ceiling for a small synthetic fixture only.

    def test_f09_changed_audit_threshold_cannot_be_reused_for_freeze(self):
        graph, plan, split, policy = configured_active()
        report = audit_leakage(graph, split, audit_policy=policy)
        forged = replace(report, near_threshold=0.1, holdout_blocked=False,
                         active_blocked=False, unresolved_risks=(), findings=())
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, forged, approval(), audit_policy=policy)
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, report, approval(),
                                  audit_policy=reviewed_policy("0.8"))
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, report, approval(),
                                  audit_policy=replace(policy, revision="changed-revision"))
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, report, approval(),
                                  audit_policy=replace(policy, review_status="proposed",
                                                       owner_review_ref=""))
        with self.assertRaises(ValueError):
            replace(policy, normalization_version="unapproved-normalization-v2")

    def test_f09_exact_review_dispositions_are_replayed_at_freeze(self):
        graph, plan, split, policy = configured_active()
        preliminary = audit_leakage(graph, split, audit_policy=policy)
        dispositions = tuple(
            ManualDisposition(item.left_id, item.right_id, item.signal,
                              "distinct_with_reason", "synthetic-reviewer-a",
                              "synthetic distinct-source finding", "synthetic-evidence-ref",
                              "synthetic-reviewer-b")
            for item in preliminary.findings
            if item.active_cross_partition and item.signal != "source_family"
        )
        clean = audit_leakage(graph, split, audit_policy=policy, dispositions=dispositions)
        self.assertFalse(clean.active_blocked)
        manifest = proposed_split_manifest(graph, split, plan, clean)
        frozen = freeze_split_manifest(manifest, graph, split, plan, clean, approval(),
                                       audit_policy=policy, dispositions=dispositions)
        self.assertEqual(frozen.lifecycle, "frozen")
        with self.assertRaisesRegex(ValueError, "audit report differs"):
            freeze_split_manifest(manifest, graph, split, plan, clean, approval(),
                                  audit_policy=policy, dispositions=())
        incomplete = tuple(replace(item, second_reviewer="") for item in dispositions)
        with self.assertRaisesRegex(ValueError, "audit report differs"):
            freeze_split_manifest(manifest, graph, split, plan, clean, approval(),
                                  audit_policy=policy, dispositions=incomplete)


if __name__ == "__main__":
    unittest.main()
