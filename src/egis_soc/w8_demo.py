"""Allowlisted offline W8 integration over the existing W1/W3/W5 contracts.

The draft and NLI scores are deterministic synthetic adapters, not model output,
human gold, or a research result. Raw event text is never interpreted as policy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import DevelopmentV2
from egis_soc.integrity import canonical_bytes
from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, IncidentBundle
from egis_soc.summarization.atomization import extract_generated_candidates
from egis_soc.summarization.contract import retrieve_synthetic_incident
from egis_soc.summarization.final_report import build_final_report
from egis_soc.summarization.generation import GeneratedDraft
from egis_soc.summarization.omission import (
    build_operational_inventory, check_operational_omissions,
)
from egis_soc.summarization.s1 import CitationAudit, render_s1
from egis_soc.summarization.s2 import ReviewBatch, ReviewedCandidate, run_s2
from egis_soc.summarization.s3 import RepairAction, RepairPlan, RepairRound, run_s3


VERSION = "w8-00-offline-demo-1"
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = {
    "positive": ROOT / "tests" / "fixtures" / "w8_positive_v1.json",
    "negative": ROOT / "tests" / "fixtures" / "w8_negative_v1.json",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class DeterministicDemoNLI:
    """Fixed logits to exercise V3 wiring; no semantic NLI claim is made."""

    calls = 0

    def score(self, premise: str, hypothesis: str):
        self.calls += 1
        return (0.0, 5.0, 0.0), False


def load_fixture(case: str) -> tuple[dict, bytes]:
    if case not in FIXTURES:
        raise ValueError("unknown_synthetic_case")
    path = FIXTURES[case]
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing_synthetic_fixture")
    raw = path.read_bytes()
    fixture = json.loads(raw)
    if (type(fixture) is not dict or set(fixture) != {
            "version", "case", "bundle", "query", "events", "draft_text",
            "reviews", "repair"}
            or fixture["version"] != VERSION or fixture["case"] != case
            or type(fixture["events"]) is not list or not fixture["events"]
            or type(fixture["reviews"]) is not list
            or fixture["repair"] not in {"none", "add_first_unmentioned"}):
        raise ValueError("invalid_synthetic_fixture")
    return fixture, raw


def _source(fixture: dict):
    bundle = IncidentBundle.model_validate(fixture["bundle"])
    events = []
    for item in fixture["events"]:
        if type(item) is not dict or set(item) != {
                "evidence_id", "incident_id", "tenant_id", "timestamp_utc",
                "normalized_fields", "raw_message"}:
            raise ValueError("invalid_synthetic_event")
        raw = item["raw_message"]
        if type(raw) is not str:
            raise ValueError("invalid_synthetic_raw_message")
        provenance = EvidenceProvenance(
            source="synthetic:splunk-offline-export",
            timestamp_utc=item["timestamp_utc"], raw_message=raw,
            raw_message_ref="synthetic:w8:" + fixture["case"] + ":" + item["evidence_id"],
            sha256=_sha(raw.encode("utf-8")),
            acquisition_method="authored_offline_fixture",
        )
        events.append(EvidenceEvent(
            evidence_id=item["evidence_id"],
            incident_id=item["incident_id"], tenant_id=item["tenant_id"],
            normalized_fields=item["normalized_fields"], provenance=provenance,
        ))
    return bundle, tuple(events)


def run_case(case: str) -> dict:
    """Run a fixed synthetic case; reject scope, citation and review drift."""
    fixture, fixture_raw = load_fixture(case)
    bundle, events = _source(fixture)
    context = retrieve_synthetic_incident(bundle, events, query=fixture["query"])
    if set(context.evidence_ids) != set(bundle.evidence_ids):
        raise ValueError("incomplete_demo_retrieval")
    generated = GeneratedDraft(
        "W8D-" + _sha(fixture_raw)[:20], bundle.incident_id,
        bundle.tenant_id, fixture["draft_text"], context.evidence_ids,
        _sha(canonical_bytes({"query": fixture["query"],
                              "evidence_ids": context.evidence_ids})),
        _sha(fixture["draft_text"].encode("utf-8")), _sha(fixture_raw),
        "deterministic-synthetic-draft", _sha(b"w8-draft-adapter-v1"),
    )
    draft = extract_generated_candidates(context, generated).draft
    if len(draft.claims) != len(fixture["reviews"]):
        raise ValueError("incomplete_demo_review")
    reviews = []
    audits = []
    for claim, source in zip(draft.claims, fixture["reviews"]):
        if (type(source) is not dict or set(source) != {
                "text", "citation_ids", "cited_set_support", "rationale"}
                or claim.text != source["text"]
                or list(claim.citation_ids) != source["citation_ids"]):
            raise ValueError("demo_review_drift")
        relevance = tuple("relevant" for _ in claim.citation_ids)
        reviews.append(ReviewedCandidate(
            claim.claim_id, claim.text, "authored-synthetic-demo-review",
            source["rationale"], "atomic_factual", relevance,
            source["cited_set_support"],
        ))
        if claim.citation_ids:
            audits.append(CitationAudit(
                claim.claim_id, "authored-synthetic-demo-review",
                source["rationale"], relevance, source["cited_set_support"],
            ))
    s1 = render_s1(context, draft, citation_audits=tuple(audits))
    review = ReviewBatch(draft.sha256, _sha(canonical_bytes(s1.to_record())),
                         tuple(reviews))
    backend = DeterministicDemoNLI()
    verifier = SyntheticV3Verifier(DevelopmentV2(backend))
    s2 = run_s2(context, draft, s1, review, verifier)
    inventory_before = build_operational_inventory(context)
    fork = canonical_bytes({
        "incident_id": bundle.incident_id, "tenant_id": bundle.tenant_id,
        "retrieval_sha256": inventory_before["retrieval_sha256"],
        "s2_report_sha256": _sha(canonical_bytes(s2)),
        "operational_inventory_status": "NOT_ACCESSED_S2",
    })
    inventory, omission = check_operational_omissions(context, s2, fork)
    rounds = ()
    if fixture["repair"] == "add_first_unmentioned":
        candidates = [item for item in inventory["facts"]
                      if item["observability"] == "observable" and
                      any(finding["fact_id"] == item["fact_id"] and
                          finding["outcome"] == "candidate_unmentioned"
                          for finding in omission["findings"])]
        if not candidates:
            raise ValueError("demo_repair_fact_unavailable")
        fact = candidates[0]
        action = RepairAction(
            "add", None, fact["fact_id"], fact["statement"],
            tuple(fact["evidence_ids"]), "authored-synthetic-demo-review",
            "Explicit synthetic source-record add proposal",
            tuple("relevant" for _ in fact["evidence_ids"]), "supported",
        )
        rounds = (RepairRound((action,)),)
    plan = RepairPlan(
        _sha(fork), _sha(canonical_bytes(omission)),
        "authored-synthetic-demo-review", "Fixed synthetic demo plan", rounds,
    )
    s3 = run_s3(context, s2, fork, inventory, omission, plan,
                verifier if rounds else None)
    report = build_final_report(s1, review, s2, s3, inventory, omission, fork)
    report["w8_demo"] = {
        "version": VERSION, "case": case, "mode": "SYNTHETIC_OFFLINE",
        "draft_adapter": "DETERMINISTIC_FIXTURE_NOT_LLM_INFERENCE",
        "nli_adapter": "FIXED_LOGITS_NOT_MODEL_INFERENCE",
        "model_trace_id_note": "W5 contract identifier only; pinned checkpoint was not executed",
        "nli_calls": backend.calls, "fixture_sha256": _sha(fixture_raw),
        "source_evidence_sha256": {event.evidence_id: event.provenance.sha256
                                   for event in events},
        "research_status": "NOT_RUN", "analyst_review_status": "PENDING_AUTHENTICATED_REVIEW",
        "splunk_status": "OFFLINE_SYNTHETIC_EXPORT_ONLY",
    }
    return report
