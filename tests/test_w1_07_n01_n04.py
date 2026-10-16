"""Synthetic red-before-green regressions for W1-07 N-01 through N-04."""

import hashlib
import unittest
from dataclasses import replace

from egis_soc.evaluation_boundary import AccessGrant, build_inference_input
from egis_soc.integrity import FreezeApproval, Manifest
from egis_soc.lineage import LineageGraph, ReviewedLink
from egis_soc.split_freeze import (
    AssignmentPlan,
    AuditPolicy,
    ManualDisposition,
    assign_components,
    audit_leakage,
    freeze_split_manifest,
    proposed_split_manifest,
)
from test_split_freeze import child, incident
from test_w1_07_preacceptance import synthetic_evidence


class NewW107Regressions(unittest.TestCase):
    def test_n01_unknown_and_unverified_inheritance_fail_closed(self):
        root = incident(900, environment="B")
        plan = AssignmentPlan("synthetic-policy", "seed", (0, 0, 0), (0, 0, 0, 1))
        for changes in (
            {"rights_basis": "unresolved"},
            {"rights_evidence_ref": None},
            {"rights_status": "cleared", "rights_basis": "unresolved"},
        ):
            with self.subTest(changes=changes):
                descendant = child(root, "synthetic-rights-case", **changes)
                graph = LineageGraph([root, descendant])
                self.assertEqual(assign_components(graph, plan).partition_for_artifact(
                    graph, root.artifact_id), "quarantine")
        verified = child(root, "synthetic-verified-inheritance")
        graph = LineageGraph([root, verified])
        self.assertEqual(assign_components(graph, plan).partition_for_artifact(
            graph, root.artifact_id), "heldout_b")
        with self.assertRaises(ValueError):
            child(root, "synthetic-false-parent", rights_inherited_from="foreign-parent")
        blocked_root = replace(root, rights_status="blocked")
        graph = LineageGraph([blocked_root, verified])
        self.assertEqual(assign_components(graph, plan).partition_for_artifact(
            graph, root.artifact_id), "quarantine")

    def test_n01_blocked_descendant_keeps_b_out_of_holdout(self):
        root = incident(901, environment="B")
        blocked = child(root, "synthetic-blocked-event", rights_status="blocked")
        graph = LineageGraph([root, blocked])
        plan = AssignmentPlan("synthetic-policy", "seed", (0, 0, 0), (0, 0, 0, 1))
        split = assign_components(graph, plan)
        self.assertEqual(split.partition_for_artifact(graph, root.artifact_id), "quarantine")
        self.assertEqual(split.feasibility, "insufficient_groups")

    def test_n02_same_partition_hash_needs_independence_review(self):
        first, second = incident(911), incident(912)
        shared_hash = hashlib.sha256(b"synthetic shared event").hexdigest()
        a = child(first, "synthetic-event-a", event_hash=shared_hash)
        b = child(second, "synthetic-event-b", event_hash=shared_hash)
        graph = LineageGraph([first, second, a, b, incident(913, environment="B")])
        plan = AssignmentPlan("synthetic-policy", "seed", (2, 0, 0), (1, 0, 0, 1))
        split = assign_components(graph, plan)
        self.assertEqual(split.partition_for_artifact(graph, a.artifact_id), "train")
        self.assertEqual(split.partition_for_artifact(graph, b.artifact_id), "train")
        report = audit_leakage(graph, split, near_threshold=0.9)
        self.assertTrue(any(item.signal == "event_hash"
                            for item in report.intra_partition_findings))
        self.assertTrue(report.independence_blocked)

    def test_n02_distinct_disposition_and_rebuilt_component_counts(self):
        first, second, b_root = incident(941), incident(942), incident(943, environment="B")
        shared_hash = hashlib.sha256(b"synthetic duplicate event").hexdigest()
        a = child(first, "synthetic-a", event_hash=shared_hash)
        b = child(second, "synthetic-b", event_hash=shared_hash)
        graph = LineageGraph([first, second, b_root, a, b])
        policy = AuditPolicy("synthetic-audit", "0.9", 1000,
                             review_status="owner_reviewed", owner_review_ref="synthetic-review")
        plan = AssignmentPlan("synthetic-policy", "seed", (2, 0, 0), (1, 0, 0, 1),
                              configuration_revision="synthetic-config",
                              audit_policy_digest=policy.sha256)
        split = assign_components(graph, plan)
        self.assertEqual(split.component_counts[0], 2)
        unresolved = audit_leakage(graph, split, audit_policy=policy)
        approval = FreezeApproval("synthetic-owner", "synthetic-reviewer", "synthetic-access",
                                  "synthetic-lock")
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, unresolved),
                                  graph, split, plan, unresolved, approval, audit_policy=policy)
        distinct = ManualDisposition(a.artifact_id, b.artifact_id, "event_hash",
                                     "distinct_with_reason", "reviewer-one", "distinct sources",
                                     "synthetic-source-proof", "reviewer-two")
        reviewed = audit_leakage(graph, split, audit_policy=policy, dispositions=(distinct,))
        self.assertFalse(reviewed.independence_blocked)
        self.assertEqual(freeze_split_manifest(
            proposed_split_manifest(graph, split, plan, reviewed), graph, split, plan,
            reviewed, approval, audit_policy=policy, dispositions=(distinct,)
        ).lifecycle, "frozen")
        incomplete = audit_leakage(graph, split, audit_policy=policy,
                                   dispositions=(replace(distinct, second_reviewer=""),))
        self.assertTrue(incomplete.independence_blocked)
        same = ManualDisposition(a.artifact_id, b.artifact_id, "event_hash", "same_component",
                                 "reviewer-one", "shared source event", "synthetic-source-proof")
        self.assertTrue(audit_leakage(graph, split, audit_policy=policy,
                                      dispositions=(same,)).independence_blocked)
        merged = LineageGraph([first, second, b_root, a, b], [ReviewedLink(
            a.artifact_id, b.artifact_id, "copy", "synthetic-source-proof", "reviewer-one")])
        merged_split = assign_components(merged, plan)
        self.assertEqual(merged_split.component_counts[0], 1)
        self.assertFalse(audit_leakage(merged, merged_split, audit_policy=policy).independence_blocked)
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, reviewed),
                                  merged, split, plan, reviewed, approval, audit_policy=policy,
                                  dispositions=(distinct,))

    def test_n02_exact_candidate_budget_and_source_event_grouping(self):
        roots = [incident(950 + index) for index in range(4)]
        shared_hash = hashlib.sha256(b"synthetic common event").hexdigest()
        events = [child(root, f"synthetic-event-{index}", event_hash=shared_hash)
                  for index, root in enumerate(roots)]
        graph = LineageGraph([*roots, *events, incident(959, environment="B")])
        plan = AssignmentPlan("synthetic-policy", "seed", (4, 0, 0), (1, 0, 0, 1))
        policy = AuditPolicy("synthetic-audit", "0.9", 1000,
                             max_intra_duplicate_pairs=2)
        with self.assertRaisesRegex(ValueError, "intra-partition duplicate limit"):
            audit_leakage(graph, assign_components(graph, plan), audit_policy=policy)
        common_event_id = events[0].source_event_key
        grouped = LineageGraph([*roots, *events[:1],
                                replace(events[1], source_event_key=common_event_id),
                                *events[2:]])
        self.assertEqual(len(grouped.components()), 3)

    def test_n02_parent_dataset_signal_without_generic_text_ancestry(self):
        from test_split_freeze import key

        shared_parent = key("parent-dataset", "synthetic-shared")
        first = incident(971, parent_dataset_status="known", parent_dataset_key=shared_parent,
                         evidence_text="same generic description")
        second = incident(972, parent_dataset_status="known", parent_dataset_key=shared_parent,
                          evidence_text="same generic description")
        graph = LineageGraph([first, second, incident(973, environment="B")])
        plan = AssignmentPlan("synthetic-policy", "seed", (2, 0, 0), (1, 0, 0, 1))
        split = assign_components(graph, plan)
        report = audit_leakage(graph, split, near_threshold=0.9)
        self.assertEqual({item.signal for item in report.intra_partition_findings},
                         {"parent_dataset_key"})

    def test_n03_redundant_review_provenance_changes_digests(self):
        root = incident(921)
        event = child(root, "synthetic-event")
        first = LineageGraph([root, event], [ReviewedLink(
            root.artifact_id, event.artifact_id, "copy", "synthetic-evidence-1", "reviewer-1")])
        second = LineageGraph([root, event], [ReviewedLink(
            root.artifact_id, event.artifact_id, "copy", "synthetic-evidence-2", "reviewer-2")])
        plan = AssignmentPlan("synthetic-policy", "seed", (1, 0, 0), (1, 0, 0, 1))
        split_a, split_b = assign_components(first, plan), assign_components(second, plan)
        self.assertEqual(split_a.assignments, split_b.assignments)
        audit_a = audit_leakage(first, split_a, near_threshold=0.9)
        audit_b = audit_leakage(second, split_b, near_threshold=0.9)
        self.assertNotEqual(audit_a.subject_sha256, audit_b.subject_sha256)
        self.assertNotEqual(proposed_split_manifest(first, split_a, plan, audit_a).sha256,
                            proposed_split_manifest(second, split_b, plan, audit_b).sha256)
        for variant in (
            replace(first.reviewed_links[0], evidence_ref="changed-only-evidence"),
            replace(first.reviewed_links[0], reviewer="changed-only-reviewer"),
            replace(first.reviewed_links[0], relation="same_original"),
        ):
            with self.subTest(variant=variant):
                changed = LineageGraph([root, event], [variant])
                self.assertNotEqual(first.lineage_graph_sha256, changed.lineage_graph_sha256)

    def test_n03_stale_review_and_history_change_are_rejected(self):
        root, b_root = incident(961), incident(962, environment="B")
        event = child(root, "synthetic-review-event")
        old_link = ReviewedLink(root.artifact_id, event.artifact_id, "copy",
                                "synthetic-evidence-old", "reviewer-old")
        new_link = replace(old_link, evidence_ref="synthetic-evidence-new",
                           reviewer="reviewer-new")
        old = LineageGraph([root, b_root, event], [old_link],
                           review_registry_version="synthetic-review-v1")
        amended = LineageGraph([root, b_root, event], [new_link],
                               review_registry_version="synthetic-review-v2",
                               review_predecessor_sha256=old.review_registry_sha256,
                               review_history=[old_link])
        self.assertNotEqual(old.review_registry_sha256, amended.review_registry_sha256)
        policy = AuditPolicy("synthetic-audit", "0.9", 1000,
                             review_status="owner_reviewed", owner_review_ref="synthetic-review")
        plan = AssignmentPlan("synthetic-policy", "seed", (1, 0, 0), (1, 0, 0, 1),
                              configuration_revision="synthetic-config",
                              audit_policy_digest=policy.sha256)
        old_split = assign_components(old, plan)
        amended_split = assign_components(amended, plan)
        old_audit = audit_leakage(old, old_split, audit_policy=policy)
        old_manifest = proposed_split_manifest(old, old_split, plan, old_audit)
        with self.assertRaises(ValueError):
            proposed_split_manifest(amended, amended_split, plan, old_audit)
        with self.assertRaises(ValueError):
            freeze_split_manifest(old_manifest, amended, amended_split, plan, old_audit,
                                  FreezeApproval("owner", "reviewer", "access", "lock"),
                                  audit_policy=policy)
        reordered = LineageGraph([root, b_root, event], [old_link, new_link])
        reverse = LineageGraph([event, b_root, root], [new_link, old_link])
        self.assertEqual(reordered.review_registry_sha256, reverse.review_registry_sha256)

    def test_n04_inference_rejects_wrong_restricted_grant_scope(self):
        _, event, bundle = synthetic_evidence()
        root = incident(1)
        graph = LineageGraph([root, incident(932, environment="B")])
        plan = AssignmentPlan("synthetic-policy", "seed", (1, 0, 0), (1, 0, 0, 1))
        split = assign_components(graph, plan)
        manifest = proposed_split_manifest(graph, split, plan)
        grant = AccessGrant(manifest.manifest_id, "synthetic-owner", "synthetic-custodian",
                            "annotation", "train", (("TENANT-SYN", "INC-1"),))
        self.assertEqual(build_inference_input(bundle, (event,), (), partition="train",
                                               role="annotator", grant=grant,
                                               manifest=manifest).incident, bundle)
        for invalid in (
            replace(grant, partition="validation"),
            replace(grant, authorized_incidents=(("OTHER", "INC-1"),)),
            replace(grant, authorized_incidents=(("TENANT-SYN", "OTHER"),)),
            replace(grant, manifest_id="other"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(PermissionError):
                build_inference_input(bundle, (event,), (), partition="train",
                                      role="annotator", grant=invalid, manifest=manifest)
        wrong_tenant = type(bundle)(**(bundle.model_dump() | {"tenant_id": "OTHER"}))
        with self.assertRaises(PermissionError):
            build_inference_input(wrong_tenant, (event,), (), partition="train",
                                  role="annotator", grant=grant, manifest=manifest)

    def test_n04_prefreeze_annotation_and_postlock_evaluation_lifecycle(self):
        _, event, bundle = synthetic_evidence()
        graph = LineageGraph([incident(1), incident(981, environment="B")])
        policy = AuditPolicy("synthetic-audit", "0.9", 1000,
                             review_status="owner_reviewed", owner_review_ref="synthetic-review")
        plan = AssignmentPlan("synthetic-policy", "seed", (1, 0, 0), (1, 0, 0, 1),
                              configuration_revision="synthetic-config",
                              audit_policy_digest=policy.sha256)
        split = assign_components(graph, plan)
        audit = audit_leakage(graph, split, audit_policy=policy)
        proposed = proposed_split_manifest(graph, split, plan, audit)
        annotation = AccessGrant(proposed.manifest_id, "owner", "custodian", "annotation",
                                 "train", (("TENANT-SYN", "INC-1"),))
        self.assertIs(build_inference_input(bundle, (event,), (), partition="train",
                                            role="annotator", grant=annotation,
                                            manifest=proposed).incident, bundle)
        with self.assertRaises(PermissionError):
            build_inference_input(bundle, (event,), (), partition="train", role="evaluator",
                                  grant=replace(annotation, purpose="evaluation"), manifest=proposed)
        frozen = freeze_split_manifest(proposed, graph, split, plan, audit,
                                       FreezeApproval("owner", "reviewer", "access", "lock"),
                                       audit_policy=policy)
        evaluation = AccessGrant(frozen.manifest_id, "owner", "custodian", "evaluation",
                                 "train", (("TENANT-SYN", "INC-1"),))
        self.assertIs(build_inference_input(bundle, (event,), (), partition="train",
                                            role="evaluator", grant=evaluation,
                                            manifest=frozen).incident, bundle)
        for invalid in (None, replace(evaluation, purpose="annotation"),
                        replace(evaluation, partition="heldout_b"),
                        replace(evaluation, authorized_incidents=())):
            with self.subTest(invalid=invalid), self.assertRaises(PermissionError):
                build_inference_input(bundle, (event,), (), partition="train",
                                      role="evaluator", grant=invalid, manifest=frozen)
        with self.assertRaises(PermissionError):
            build_inference_input(bundle, (event,), (), partition="heldout_a",
                                  role="development", manifest=proposed)
        with self.assertRaises(PermissionError):
            build_inference_input(bundle, (event,), (), partition="train", role="development")
        generic = Manifest.proposed("synthetic", [{
            "component_id": "synthetic", "partition": "train",
            "incidents": [{"tenant_id": "TENANT-SYN", "incident_id": "INC-1"}],
        }])
        with self.assertRaises(ValueError):
            build_inference_input(bundle, (event,), (), partition="train",
                                  role="development", manifest=generic)


if __name__ == "__main__":
    unittest.main()
