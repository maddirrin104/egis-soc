"""Ten synthetic W1-07 cases; no raw, sealed, or acquired data is used."""

import hashlib
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

from egis_soc.evaluation_boundary import (
    AccessGrant,
    EvaluationStore,
    OperationalFact,
    PairManifestCandidate,
    S2ForkIdentity,
    VerifierInputIdentity,
    build_inference_input,
    verify_s2_s3_fork,
    verify_shared_v2_v3_inputs,
)
from egis_soc.integrity import FreezeApproval, Manifest, canonical_bytes
from egis_soc.lineage import GroupKey, LineageGraph, LineageRecord, ReviewedLink
from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, EvaluationGoldRecord, IncidentBundle
from egis_soc.split_freeze import (
    AssignmentPlan,
    AuditPolicy,
    AuditReport,
    ManualDisposition,
    assign_components,
    audit_leakage,
    freeze_split_manifest,
    proposed_split_manifest,
    structural_audit,
)


def key(kind: str, value: str) -> GroupKey:
    return GroupKey(f"synthetic:{kind}", value)


def incident(number: int, *, environment: str = "A", **changes) -> LineageRecord:
    values = dict(
        artifact_id=f"root-{number}",
        kind="incident",
        incident_id=f"INC-{number}",
        tenant_id="TENANT-SYN",
        environment=environment,
        original_key=key("original", str(number)),
        simulation_status="simulated",
        run_key=key("run", str(number)),
        concrete_template_key=key("template", str(number)),
        collection_key=key("collection", str(number)),
        parent_dataset_status="none_attested",
        source_family="synthetic-family",
        operator_id=f"operator-{environment}",
        pipeline_id=f"pipeline-{environment}",
        rights_status="cleared",
        rights_basis="independent",
        rights_evidence_ref=f"synthetic-rights-{number}",
        b_review="eligible" if environment == "B" else None,
        b_review_reference=f"synthetic-review-{number}" if environment == "B" else None,
    )
    return LineageRecord(**(values | changes))


def child(parent: LineageRecord, name: str, kind: str = "event", **changes) -> LineageRecord:
    values = dict(
        artifact_id=name,
        kind=kind,
        incident_id=parent.incident_id,
        tenant_id=parent.tenant_id,
        environment=parent.environment,
        parent_ids=(parent.artifact_id,),
        rights_basis="inherited",
        rights_evidence_ref=f"synthetic-inheritance-{name}",
        rights_inherited_from=parent.artifact_id,
    )
    if kind == "event":
        values["source_event_key"] = key("source-event", name)
        values["event_hash"] = hashlib.sha256(name.encode()).hexdigest()
    return LineageRecord(**(values | changes))


def standard_graph():
    roots = [incident(index) for index in range(1, 5)] + [incident(5, environment="B")]
    event = child(roots[0], "event-1")
    graph = LineageGraph([*roots, event])
    plan = AssignmentPlan("proposal-1", "synthetic-seed", (2, 1, 1), (1, 1, 1, 1))
    return roots, event, graph, plan


class SplitFreezeTests(unittest.TestCase):
    def test_01_explicit_parents_run_template_and_collection_components(self):
        first = incident(1)
        same_run = incident(2, run_key=first.run_key)
        same_template = incident(3, concrete_template_key=same_run.concrete_template_key)
        same_parent_collection = incident(4, parent_collection_key=first.collection_key)
        separate = incident(5)
        derived = child(first, "derived-1", "draft")
        graph = LineageGraph([separate, derived, same_template, same_parent_collection, same_run, first])
        components = graph.components()
        self.assertEqual(len(components), 2)
        joined = next(item for item in components if first.artifact_id in item.artifact_ids)
        self.assertEqual(len(joined.incident_ids), 4)
        self.assertIn(derived.artifact_id, joined.artifact_ids)
        with self.assertRaises(FrozenInstanceError):
            first.artifact_id = "changed"
        with self.assertRaises(ValueError):
            LineageGraph([child(first, "orphan")])
        with self.assertRaises(ValueError):
            LineageGraph([first, child(first, "wrong", tenant_id="FOREIGN")])
        with self.assertRaises(ValueError):
            LineageGraph([first, first])
        copied_event = child(separate, "copied-event", collection_key=first.collection_key)
        self.assertEqual(len(LineageGraph([first, separate, copied_event]).components()), 1)
        event_a = child(first, "event-key-a")
        event_b = child(separate, "event-key-b", source_event_key=event_a.source_event_key)
        self.assertEqual(len(LineageGraph([first, separate, event_a, event_b]).components()), 1)
        with self.assertRaises(ValueError):
            LineageGraph([first, child(first, "wrong-original", original_key=key("original", "foreign"))])
        first_event = child(first, "first-parent")
        other_root = incident(6, incident_id=first.incident_id)
        other_event = child(other_root, "other-parent")
        mixed = LineageRecord("mixed-derivative", "draft", first.incident_id, first.tenant_id,
                              first.environment, (first_event.artifact_id, other_event.artifact_id))
        with self.assertRaises(ValueError):
            LineageGraph([first, other_root, first_event, other_event, mixed])

    def test_02_broad_family_does_not_group_and_missing_provenance_quarantines(self):
        first, second = incident(1), incident(2)
        self.assertEqual(len(LineageGraph([first, second]).components()), 2)
        with self.assertRaises(ValueError):
            incident(7, original_key="unnamespaced")
        missing_run = incident(3, run_key=None)
        real_world = incident(4, simulation_status="not_applicable", run_key=None,
                              concrete_template_key=None)
        no_operator_b = incident(5, environment="B", operator_id=None)
        no_parent_attestation_b = incident(6, environment="B", parent_dataset_status="unknown")
        graph = LineageGraph([missing_run, real_world, no_operator_b, no_parent_attestation_b])
        plan = AssignmentPlan("proposal-1", "seed", (1, 0, 0), (1, 0, 0, 1))
        result = assign_components(graph, plan)
        self.assertEqual(result.partition_for_artifact(graph, missing_run.artifact_id), "quarantine")
        self.assertEqual(result.partition_for_artifact(graph, no_operator_b.artifact_id), "quarantine")
        self.assertEqual(result.partition_for_artifact(graph, no_parent_attestation_b.artifact_id),
                         "quarantine")
        self.assertEqual(result.partition_for_artifact(graph, real_world.artifact_id), "train")
        self.assertEqual(result.feasibility, "insufficient_groups")
        reviewed = ReviewedLink(first.artifact_id, second.artifact_id, "concrete_template",
                                "synthetic-evidence", "reviewer-1")
        self.assertEqual(len(LineageGraph([first, second], [reviewed]).components()), 1)

    def test_03_seeded_whole_component_assignment_and_structural_audit(self):
        roots, event, graph, plan = standard_graph()
        result = assign_components(graph, plan)
        reordered = LineageGraph(list(reversed([*roots, event])))
        self.assertEqual(result.assignments, assign_components(reordered, plan).assignments)
        self.assertEqual(result.feasibility, "feasible")
        self.assertEqual(result.incident_counts, (2, 1, 1, 1))
        self.assertEqual(result.partition_for_artifact(graph, event.artifact_id),
                         result.partition_for_artifact(graph, roots[0].artifact_id))
        self.assertEqual(result.partition_for_artifact(graph, roots[-1].artifact_id), "heldout_b")
        strata = structural_audit(graph, result)
        self.assertEqual(tuple(item.component_count for item in strata), (2, 1, 1, 1))
        self.assertEqual(strata[3].component_sizes, (1,))
        self.assertEqual(strata[3].source_families, ("synthetic-family",))
        self.assertEqual(strata[0].source_family_component_counts,
                         (("synthetic-family", 2),))
        self.assertEqual(sum(count for _, count in strata[0].collection_component_counts), 2)
        self.assertTrue(result.decisions)

    def test_04_b_reserved_unknown_and_exposed_never_fall_back_to_a(self):
        a = incident(1)
        reserved = incident(2, environment="B", b_review="reserved", b_review_reference=None)
        unknown = incident(3, environment="B", b_review="unknown", b_review_reference=None)
        exposed = incident(4, environment="B", exposed_to_development=True)
        shared_pipeline = incident(5, environment="B", operator_id=a.operator_id,
                                   pipeline_id=a.pipeline_id)
        graph = LineageGraph([a, reserved, unknown, exposed, shared_pipeline])
        plan = AssignmentPlan("proposal-1", "seed", (1, 0, 0), (1, 0, 0, 1))
        result = assign_components(graph, plan)
        self.assertEqual(result.partition_for_artifact(graph, reserved.artifact_id), "reserved")
        for item in (unknown, exposed, shared_pipeline):
            self.assertEqual(result.partition_for_artifact(graph, item.artifact_id), "quarantine")
        self.assertEqual(result.incident_counts[3], 0)
        self.assertEqual(result.feasibility, "insufficient_groups")

    def test_05_train_only_derivatives_and_holdout_conflict(self):
        a, b = incident(1), incident(2, environment="B")
        mutation = child(a, "mutation-1", "mutation")
        graph = LineageGraph([a, mutation, b])
        plan = AssignmentPlan("proposal-1", "seed", (1, 0, 0), (1, 0, 0, 1))
        result = assign_components(graph, plan)
        self.assertEqual(result.partition_for_artifact(graph, mutation.artifact_id), "train")
        conflict_plan = AssignmentPlan("proposal-1", "seed", (1, 0, 0), (1, 0, 0, 1),
                                       (a.collection_key,))
        self.assertEqual(assign_components(graph, conflict_plan).partition_for_artifact(
            graph, a.artifact_id), "quarantine")
        b_mutation = child(b, "mutation-b", "counterfactual")
        b_graph = LineageGraph([a, b, b_mutation])
        self.assertEqual(assign_components(b_graph, plan).partition_for_artifact(
            b_graph, b.artifact_id), "quarantine")

    def test_06_exact_and_near_leakage_needs_manual_disposition(self):
        a = incident(1)
        holdout = incident(2)
        b = incident(3, environment="B")
        event_hash = hashlib.sha256(b"synthetic common event").hexdigest()
        first = child(a, "event-a", event_hash=event_hash,
                      evidence_text="Synthetic account logged on to host A",
                      claim_text="The account logged on to host A",
                      prompt_text="Summarize this synthetic event")
        second = child(holdout, "event-h", event_hash=event_hash,
                       evidence_text="synthetic  account logged on to host A",
                       claim_text="The account logged on to host B",
                       prompt_text="Summarize this synthetic event")
        graph = LineageGraph([a, holdout, b, first, second])
        plan = AssignmentPlan("proposal-1", "seed", (1, 0, 1), (1, 0, 1, 1),
                              (holdout.collection_key,))
        split = assign_components(graph, plan)
        report = audit_leakage(graph, split, near_threshold=0.80)
        signals = {finding.signal for finding in report.findings}
        self.assertTrue({"event_hash", "evidence_text_exact", "claim_text_near",
                         "prompt_text_exact", "source_family"} <= signals)
        self.assertTrue(report.holdout_blocked)
        self.assertTrue(report.unresolved_risks)
        resolved = tuple(ManualDisposition(f.left_id, f.right_id, f.signal,
                                           "distinct_with_reason", "reviewer", "synthetic review",
                                           "synthetic-evidence-ref", "second-reviewer")
                         for f in report.findings if f.signal != "source_family")
        clean = audit_leakage(graph, split, near_threshold=0.80, dispositions=resolved)
        self.assertFalse(clean.holdout_blocked)
        with self.assertRaises(ValueError):
            ManualDisposition(first.artifact_id, second.artifact_id, "event_hash",
                              "distinct_with_reason")

    def test_07_cross_partition_structural_overlap_cannot_be_waived(self):
        first = incident(1, incident_id="SHARED-INC")
        second = incident(2, incident_id="SHARED-INC")
        b = incident(3, environment="B")
        graph = LineageGraph([first, second, b])
        plan = AssignmentPlan("proposal-1", "seed", (1, 0, 1), (1, 0, 1, 1),
                              (second.collection_key,))
        policy = AuditPolicy("synthetic-audit-v1", "0.9", 1000,
                             review_status="owner_reviewed", owner_review_ref="synthetic-review")
        plan = replace(plan, configuration_revision="synthetic-config",
                       audit_policy_digest=policy.sha256)
        split = assign_components(graph, plan)
        review = ManualDisposition(first.artifact_id, second.artifact_id, "incident_id",
                                   "distinct_with_reason", "reviewer", "synthetic rationale")
        report = audit_leakage(graph, split, audit_policy=policy, dispositions=(review,))
        self.assertTrue(report.holdout_blocked)
        self.assertIn("incident_id", {finding.signal for finding in report.findings})
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed_split_manifest(graph, split, plan, report), graph,
                                  split, plan, report,
                                  FreezeApproval("owner", "reviewer", "access", "method"),
                                  audit_policy=policy, dispositions=(review,))

    def test_08_manifest_bytes_checksums_determinism_and_tamper_detection(self):
        roots, event, graph, plan = standard_graph()
        split = assign_components(graph, plan)
        manifest = proposed_split_manifest(graph, split, plan)
        reversed_graph = LineageGraph(list(reversed([*roots, event])))
        same = proposed_split_manifest(reversed_graph, assign_components(reversed_graph, plan), plan)
        self.assertEqual(manifest.manifest_id, same.manifest_id)
        self.assertEqual(manifest.lifecycle, "proposed")
        self.assertEqual(Manifest.deserialize(manifest.serialize()).manifest_id, manifest.manifest_id)
        detached = manifest.data
        detached["entries"][0]["partition"] = "tampered"
        self.assertNotEqual(detached, manifest.data)
        with self.assertRaises(ValueError):
            Manifest(manifest.content + b" ", manifest.sha256).verify()
        with self.assertRaises(ValueError):
            Manifest.deserialize(manifest.serialize().replace(b"proposed", b"frozen"))
        with self.assertRaises(ValueError):
            canonical_bytes({"not_json": float("nan")})
        self.assertEqual(canonical_bytes({"e\u0301": 1}), canonical_bytes({"é": 1}))

    def test_09_freeze_needs_feasibility_audit_and_explicit_refs(self):
        _, _, graph, plan = standard_graph()
        policy = AuditPolicy("synthetic-audit-v1", "0.9", 1000,
                             review_status="owner_reviewed", owner_review_ref="synthetic-review")
        plan = replace(plan, configuration_revision="synthetic-config",
                       audit_policy_digest=policy.sha256)
        split = assign_components(graph, plan)
        clean = audit_leakage(graph, split, audit_policy=policy)
        proposed = proposed_split_manifest(graph, split, plan, clean)
        with self.assertRaises(ValueError):
            FreezeApproval("", "reviewer", "access", "method")
        with self.assertRaises(ValueError):
            proposed.freeze(FreezeApproval("owner", "reviewer", "access", "method"),
                            gates_passed=False)
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed, graph, split, plan,
                                  replace(clean, holdout_blocked=True),
                                  FreezeApproval("owner", "reviewer", "access", "method"),
                                  audit_policy=policy)
        with self.assertRaises(ValueError):
            freeze_split_manifest(proposed, graph, split, plan,
                                  replace(clean, subject_sha256="0" * 64),
                                  FreezeApproval("owner", "reviewer", "access", "method"),
                                  audit_policy=policy)
        altered = Manifest.proposed(plan.policy_version, [])
        with self.assertRaises(ValueError):
            freeze_split_manifest(altered, graph, split, plan, clean,
                                  FreezeApproval("owner", "reviewer", "access", "method"),
                                  audit_policy=policy)
        frozen = freeze_split_manifest(proposed, graph, split, plan, clean,
                                       FreezeApproval("owner", "reviewer", "access", "method"),
                                       audit_policy=policy)
        self.assertEqual(frozen.lifecycle, "frozen")
        self.assertNotEqual(frozen.sha256, proposed.sha256)
        with self.assertRaises(ValueError):
            frozen.freeze(FreezeApproval("owner", "reviewer", "access", "method"),
                          gates_passed=True)

    def test_10_access_gold_separation_and_future_pair_fork_contracts(self):
        message = "synthetic event"
        digest = hashlib.sha256(message.encode()).hexdigest()
        provenance = EvidenceProvenance(source="synthetic", timestamp_utc=datetime(
            2026, 10, 16, tzinfo=timezone.utc), raw_message=message,
            raw_message_ref="synthetic:raw-1", sha256=digest, acquisition_method="fixture")
        event = EvidenceEvent(evidence_id="E1", incident_id="INC-1", tenant_id="TENANT-SYN",
                              normalized_fields={"synthetic": True}, provenance=provenance)
        bundle = IncidentBundle(incident_id="INC-1", tenant_id="TENANT-SYN",
                                environment_id="A", source_dataset="synthetic",
                                scenario_family="fixture", alert_ids=("ALT-1",), evidence_ids=("E1",))
        gold = EvaluationGoldRecord(incident_id="INC-1", tenant_id="TENANT-SYN",
                                    evidence_ids=("E1",), gold_facts=())
        fact = OperationalFact("OP-1", "INC-1", "TENANT-SYN", "observed event", ("E1",))
        dev_graph = LineageGraph([incident(1)])
        dev_plan = AssignmentPlan("synthetic-policy", "dev-seed", (1, 0, 0), (1, 0, 0, 1))
        dev_manifest = proposed_split_manifest(dev_graph, assign_components(dev_graph, dev_plan),
                                               dev_plan)
        valid = build_inference_input(bundle, (event,), (fact,), partition="train",
                                      role="development", manifest=dev_manifest)
        self.assertFalse(hasattr(valid, "gold_facts"))
        with self.assertRaises(PermissionError):
            build_inference_input(bundle, (event,), (fact,), partition="heldout_a",
                                  role="development", manifest=dev_manifest)
        with self.assertRaises(TypeError):
            build_inference_input(bundle, (event,), (gold,), partition="train",
                                  role="development", manifest=dev_manifest)
        scope_root = incident(701, environment="B", incident_id="INC-1")
        scope_graph = LineageGraph([scope_root])
        scope_policy = AuditPolicy("synthetic-audit-v1", "0.9", 1000,
                                   review_status="owner_reviewed",
                                   owner_review_ref="synthetic-review")
        scope_plan = AssignmentPlan(
            "synthetic-policy", "seed", (0, 0, 0), (0, 0, 0, 1),
            configuration_revision="synthetic-config",
            audit_policy_digest=scope_policy.sha256,
        )
        scope_split = assign_components(scope_graph, scope_plan)
        scope_audit = audit_leakage(scope_graph, scope_split, audit_policy=scope_policy)
        scope_manifest = freeze_split_manifest(
            proposed_split_manifest(scope_graph, scope_split, scope_plan, scope_audit),
            scope_graph, scope_split, scope_plan, scope_audit,
            FreezeApproval("owner", "reviewer", "access", "method"),
            audit_policy=scope_policy,
        )
        store = EvaluationStore(scope_manifest, {("TENANT-SYN", "INC-1"): gold})
        with self.assertRaises(PermissionError):
            store.read_gold("INC-1", tenant_id="TENANT-SYN", partition="heldout_b",
                            role="development")
        grant = AccessGrant(scope_manifest.manifest_id, "owner", "custodian", "evaluation",
                            "heldout_b", (("TENANT-SYN", "INC-1"),))
        self.assertIs(store.read_gold("INC-1", partition="heldout_b", role="evaluator",
                                      tenant_id="TENANT-SYN", grant=grant), gold)
        with self.assertRaises(PermissionError):
            store.read_gold("INC-1", partition="heldout_b", role="evaluator",
                            tenant_id="TENANT-SYN", grant=replace(grant, manifest_id="other"))
        primary = PairManifestCandidate("P1", "INC-1", "primary_draft", "generated_draft",
                                        ("E1",), digest, "component-1", "draft-1", digest,
                                        "annotation-1", "1", True, digest, digest)
        self.assertEqual(primary.population, "primary_draft")
        with self.assertRaises(ValueError):
            replace(primary, draft_id=None)
        with self.assertRaises(ValueError):
            replace(primary, population="source_diagnostic")
        with self.assertRaises(ValueError):
            replace(primary, inclusion_probability="NaN")
        with self.assertRaises(ValueError):
            replace(primary, arm_independent=False)
        with self.assertRaises(ValueError):
            replace(primary, evidence_snapshot_sha256=None)
        evidence_bytes = b"synthetic serialized evidence"
        threshold_bytes = b"synthetic shared threshold config"
        claim_payload = canonical_bytes([{"pair_id": "P1", "claim": "synthetic claim",
                                          "evidence_ids": ["E1"]}])
        shared = VerifierInputIdentity(
            "V2", ("P1",), (("E1",),), hashlib.sha256(evidence_bytes).hexdigest(),
            "nli-rev", hashlib.sha256(threshold_bytes).hexdigest(),
            ("synthetic claim",), claim_payload, evidence_bytes, threshold_bytes,
        )
        verify_shared_v2_v3_inputs(shared, replace(shared, arm="V3"))
        with self.assertRaises(ValueError):
            verify_shared_v2_v3_inputs(shared, replace(shared, arm="V3", nli_checkpoint="other"))
        archive = b"synthetic archived S2 state"
        archive_digest = hashlib.sha256(archive).hexdigest()
        fork = S2ForkIdentity("INC-1", "archive-1", archive_digest, digest, digest,
                              digest, digest, digest)
        verify_s2_s3_fork(fork, fork, archive)
        with self.assertRaises(ValueError):
            verify_s2_s3_fork(fork, replace(fork, archive_id="different"), archive)
        with self.assertRaises(ValueError):
            verify_s2_s3_fork(fork, fork, b"tampered")


if __name__ == "__main__":
    unittest.main()
