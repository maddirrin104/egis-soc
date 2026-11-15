"""W5-04 synthetic S2: reviewed-claim V3 boundary and one common fork.

Only an explicit synthetic development review can admit generated candidates to
V3. The original draft and every failed/removed assertion remain in the trace.
No operational fact inventory, evaluation gold, or S3 action enters this stage.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from egis_soc.development.contract import VerifierInput, VerifierOutput
from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION, NLIPair
from egis_soc.integrity import canonical_bytes

from .atomization import verify_claim_archive
from .contract import RetrievedIncident, SyntheticDraft
from .generation import GenerationConfig
from .s1 import S1Report, verify_s1_archive


VERSION = "w5-04-synthetic-s2-1"
STATUS = "SYNTHETIC_S2_DEVELOPMENT_NOT_GOLD"
REVIEW_KIND = "AUTHORED_SYNTHETIC_ENGINEERING_REVIEW_NOT_GOLD"
FILES = ("retrieval.json", "draft.json", "review.json", "verification.json",
         "s2_report.json", "fork.json")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip()


def _digest(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class ReviewedCandidate:
    claim_id: str
    original_text: str
    reviewer_id: str
    rationale: str
    decision: str  # atomic_factual or requires_review
    citation_relevance: tuple[str, ...]
    cited_set_support: str  # reviewed cited combination, never S/C/I gold

    def __post_init__(self) -> None:
        if (not all(_nonempty(item) for item in
                    (self.claim_id, self.original_text, self.reviewer_id,
                     self.rationale))
                or self.decision not in {"atomic_factual", "requires_review"}
                or type(self.citation_relevance) is not tuple
                or any(item not in {"relevant", "irrelevant", "not_assessed"}
                       for item in self.citation_relevance)
                or self.cited_set_support not in
                {"supported", "contradicted", "insufficient", "not_assessed"}):
            raise ValueError("invalid_s2_candidate_review")


@dataclass(frozen=True)
class ReviewedRevision:
    source_claim_id: str
    action: str  # qualify or correct; the text is a new claim, not relabeling
    text: str
    citation_ids: tuple[str, ...]
    reviewer_id: str
    rationale: str
    citation_relevance: tuple[str, ...]
    cited_set_support: str

    def __post_init__(self) -> None:
        if (not all(_nonempty(item) for item in
                    (self.source_claim_id, self.text, self.reviewer_id,
                     self.rationale))
                or self.action not in {"qualify", "correct"}
                or type(self.citation_ids) is not tuple
                or not self.citation_ids
                or any(not _nonempty(item) for item in self.citation_ids)
                or len(self.citation_ids) != len(set(self.citation_ids))
                or type(self.citation_relevance) is not tuple
                or any(item not in {"relevant", "irrelevant", "not_assessed"}
                       for item in self.citation_relevance)
                or self.cited_set_support not in
                {"supported", "contradicted", "insufficient", "not_assessed"}):
            raise ValueError("invalid_s2_revision")


@dataclass(frozen=True)
class ReviewBatch:
    draft_sha256: str
    s1_sha256: str
    candidates: tuple[ReviewedCandidate, ...]
    revisions: tuple[ReviewedRevision, ...] = ()
    review_kind: str = REVIEW_KIND
    version: str = VERSION

    def __post_init__(self) -> None:
        if (not _digest(self.draft_sha256) or not _digest(self.s1_sha256)
                or type(self.candidates) is not tuple or not self.candidates
                or any(type(item) is not ReviewedCandidate for item in self.candidates)
                or type(self.revisions) is not tuple
                or any(type(item) is not ReviewedRevision for item in self.revisions)
                or self.review_kind != REVIEW_KIND or self.version != VERSION):
            raise ValueError("invalid_s2_review_batch")

    def to_record(self) -> dict:
        return json.loads(canonical_bytes(asdict(self)))

    @classmethod
    def from_record(cls, record: dict) -> ReviewBatch:
        if type(record) is not dict or set(record) != {
                "draft_sha256", "s1_sha256", "candidates", "revisions",
                "review_kind", "version"}:
            raise ValueError("invalid_s2_review_record")
        try:
            candidates = tuple(ReviewedCandidate(
                **{**item, "citation_relevance": tuple(item["citation_relevance"])})
                for item in record["candidates"])
            revisions = tuple(ReviewedRevision(
                **{**item, "citation_ids": tuple(item["citation_ids"]),
                   "citation_relevance": tuple(item["citation_relevance"])})
                for item in record["revisions"])
            result = cls(record["draft_sha256"], record["s1_sha256"],
                         candidates, revisions, record["review_kind"], record["version"])
            if result.to_record() != record:
                raise ValueError("invalid_s2_review_record")
            return result
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid_s2_review_record") from None


def _review_gate(context: RetrievedIncident, draft: SyntheticDraft,
                 s1: S1Report, review: ReviewBatch) -> None:
    if (not isinstance(context, RetrievedIncident)
            or not isinstance(draft, SyntheticDraft)
            or draft.source_kind != "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD"
            or not isinstance(s1, S1Report) or type(review) is not ReviewBatch
            or draft.incident_id != context.bundle.incident_id
            or draft.tenant_id != context.bundle.tenant_id
            or draft.retrieved_evidence_ids != context.evidence_ids
            or s1.incident_id != draft.incident_id or s1.tenant_id != draft.tenant_id
            or s1.draft_sha256 != draft.sha256
            or s1.retrieved_evidence_ids != context.evidence_ids
            or s1.original_draft_text != draft.text
            or review.draft_sha256 != draft.sha256
            or review.s1_sha256 != _sha(canonical_bytes(s1.to_record()))):
        raise ValueError("s2_fixed_input_mismatch")
    if (tuple(item.claim_id for item in review.candidates)
            != tuple(claim.claim_id for claim in draft.claims)
            or tuple(item.claim_id for item in s1.claims)
            != tuple(claim.claim_id for claim in draft.claims)):
        raise ValueError("s2_incomplete_or_reordered_review")
    fixed = set(context.evidence_ids)
    revisions = {item.source_claim_id: item for item in review.revisions}
    if (len(revisions) != len(review.revisions)
            or not set(revisions) <= {claim.claim_id for claim in draft.claims}):
        raise ValueError("s2_duplicate_or_foreign_revision")
    for candidate, source_claim, s1_claim in zip(review.candidates,
                                                 draft.claims, s1.claims):
        if (candidate.original_text != source_claim.text
                or s1_claim.text != source_claim.text
                or (source_claim.span_start, source_claim.span_end)
                != (s1_claim.span_start, s1_claim.span_end)
                or source_claim.evidence_ids != context.evidence_ids
                or tuple(item.evidence_id for item in s1_claim.citations)
                != source_claim.citation_ids
                or not set(source_claim.citation_ids) <= fixed
                or len(candidate.citation_relevance) != len(source_claim.citation_ids)):
            raise ValueError("s2_review_claim_or_scope_mismatch")
        if (candidate.cited_set_support == "supported"
                and (not source_claim.citation_ids
                     or any(item != "relevant" for item in
                            candidate.citation_relevance))):
            raise ValueError("s2_invalid_cited_support_review")
        revision = revisions.get(source_claim.claim_id)
        if revision is not None:
            if (candidate.decision != "atomic_factual"
                    or revision.text == source_claim.text
                    or not set(revision.citation_ids) <= fixed
                    or len(revision.citation_relevance) != len(revision.citation_ids)
                    or (revision.cited_set_support == "supported"
                        and any(item != "relevant" for item in
                                revision.citation_relevance))):
                raise ValueError("s2_revision_not_reviewed_or_outside_scope")


def _verify(context: RetrievedIncident, verifier: SyntheticV3Verifier, *,
            source_claim_id: str, claim_id: str, variant: str,
            text: str, citation_ids: tuple[str, ...]) -> dict:
    pair = NLIPair(claim_id, context.bundle.incident_id,
                   context.bundle.tenant_id, text, context.evidence_ids)
    request = VerifierInput.from_synthetic_data(
        context.data, pair, citation_ids=citation_ids)
    premise = "\n---\n".join(item.text for item in request.evidence)
    try:
        output = verifier.predict(request)
    except Exception:
        output = None
    if output is not None and (type(output) is not VerifierOutput
                               or output.request is not request
                               or output.arm != "V3"):
        raise ValueError("s2_unmatched_v3_output")
    failed = output is None
    return {
        "source_claim_id": source_claim_id, "claim_id": claim_id,
        "variant": variant, "text": text,
        "evidence_ids": list(context.evidence_ids),
        "citation_ids": list(citation_ids),
        "premise_sha256": _sha(premise.encode("utf-8")),
        "prediction": "insufficient" if failed else output.prediction,
        "review_required": True if failed else output.review_required,
        "decision_reason": "VERIFIER_FAILURE" if failed else output.decision_reason,
        "rule_trace": ([{"rule_id": VERSION + ":inference_boundary",
                         "outcome": "insufficient", "evidence_ids": [],
                         "reason": "VERIFIER_FAILURE"}]
                       if failed else [asdict(trace) for trace in output.rule_trace]),
        "citation_checks": [asdict(check) for check in request.citation_checks],
        "nli_scores_decimal": (None if failed else
                               {key: format(value, ".17g")
                                for key, value in output.nli_scores.items()}),
        "model_id": None if failed else output.model_id,
        "model_revision": None if failed else output.model_revision,
        "truncated": False if failed else output.truncated,
        "policy_version": verifier.policy.version,
        "policy_sha256": verifier.policy.sha256,
        "failure_tag": "VERIFIER_FAILURE" if failed else None,
    }


def _eligible(assessment: dict, citation_ids: tuple[str, ...],
              relevance: tuple[str, ...], cited_set_support: str) -> bool:
    return (assessment["prediction"] == "supported"
            and not assessment["review_required"]
            and assessment["failure_tag"] is None
            and bool(citation_ids)
            and all(item["valid"] for item in assessment["citation_checks"])
            and len(relevance) == len(citation_ids)
            and all(item == "relevant" for item in relevance)
            and cited_set_support == "supported")


def run_s2(context: RetrievedIncident, draft: SyntheticDraft, s1: S1Report,
           review: ReviewBatch, verifier: SyntheticV3Verifier) -> dict:
    """Verify once per reviewed factual candidate; reverify each proposed edit."""
    _review_gate(context, draft, s1, review)
    if type(verifier) is not SyntheticV3Verifier:
        raise ValueError("s2_v3_verifier_required")
    revisions = {item.source_claim_id: item for item in review.revisions}
    assessments = []
    decisions = []
    final_claims = []
    for source_claim, candidate in zip(draft.claims, review.candidates):
        if candidate.decision != "atomic_factual":
            decisions.append({"source_claim_id": source_claim.claim_id,
                              "action": "abstain", "reason": "ATOMICITY_OR_TYPE_REVIEW",
                              "final_claim_id": None, "review_required": True})
            continue
        original = _verify(context, verifier,
                           source_claim_id=source_claim.claim_id,
                           claim_id=source_claim.claim_id, variant="initial",
                           text=source_claim.text,
                           citation_ids=source_claim.citation_ids)
        assessments.append(original)
        revision = revisions.get(source_claim.claim_id)
        if original["failure_tag"] is not None:
            action, reason, final_id = "abstain", "VERIFIER_FAILURE", None
        elif revision is not None:
            if _eligible(original, source_claim.citation_ids,
                         candidate.citation_relevance,
                         candidate.cited_set_support):
                raise ValueError("s2_revision_of_eligible_claim")
            new_id = "W5S2C-" + _sha(canonical_bytes({
                "source_claim_id": source_claim.claim_id,
                "action": revision.action, "text": revision.text,
                "citation_ids": revision.citation_ids}))[:20]
            revised = _verify(context, verifier,
                              source_claim_id=source_claim.claim_id,
                              claim_id=new_id, variant="revised",
                              text=revision.text,
                              citation_ids=revision.citation_ids)
            assessments.append(revised)
            if _eligible(revised, revision.citation_ids,
                         revision.citation_relevance,
                         revision.cited_set_support):
                action, reason, final_id = revision.action, "REVERIFIED_SUPPORTED", new_id
                final_claims.append({"claim_id": new_id,
                                     "source_claim_id": source_claim.claim_id,
                                     "text": revision.text,
                                     "citation_ids": list(revision.citation_ids),
                                     "evidence_ids": list(context.evidence_ids),
                                     "prediction": "supported",
                                     "review_required": False})
            else:
                action, reason, final_id = "abstain", "REVISION_UNRESOLVED", None
        elif _eligible(original, source_claim.citation_ids,
                       candidate.citation_relevance,
                       candidate.cited_set_support):
            action, reason, final_id = "keep", "V3_AND_CITATIONS_SUPPORTED", source_claim.claim_id
            final_claims.append({"claim_id": source_claim.claim_id,
                                 "source_claim_id": source_claim.claim_id,
                                 "text": source_claim.text,
                                 "citation_ids": list(source_claim.citation_ids),
                                 "evidence_ids": list(context.evidence_ids),
                                 "prediction": "supported",
                                 "review_required": False})
        elif (original["prediction"] == "contradicted"
              and original["decision_reason"] == "DIRECT_RULE_REFUTATION"
              and any(trace["outcome"] == "contradiction"
                      for trace in original["rule_trace"])):
            action, reason, final_id = "remove", "DIRECT_EVIDENCE_REFUTATION", None
        else:
            action, reason, final_id = "abstain", "UNRESOLVED_OR_UNCITED", None
        decisions.append({"source_claim_id": source_claim.claim_id,
                          "action": action, "reason": reason,
                          "final_claim_id": final_id,
                          "review_required": final_id is None})
    return {
        "version": VERSION, "status": STATUS,
        "incident_id": draft.incident_id, "tenant_id": draft.tenant_id,
        "draft_id": draft.draft_id, "draft_sha256": draft.sha256,
        "retrieved_evidence_ids": list(context.evidence_ids),
        "s1_sha256": review.s1_sha256,
        "review_kind": review.review_kind,
        "verifier_policy_version": verifier.policy.version,
        "verifier_policy_sha256": verifier.policy.sha256,
        "verification": assessments, "decisions": decisions,
        "final_claims": final_claims,
        "verification_status": "V3_SYNTHETIC_DEVELOPMENT_ONLY",
        "gold_status": "NOT_GOLD",
    }


def _validate_report(context: RetrievedIncident, draft: SyntheticDraft,
                     review: ReviewBatch, report: dict) -> None:
    """Check that archived decisions cannot promote a non-supported assertion."""
    keys = {"version", "status", "incident_id", "tenant_id", "draft_id",
            "draft_sha256", "retrieved_evidence_ids", "s1_sha256",
            "review_kind", "verifier_policy_version", "verifier_policy_sha256",
            "verification", "decisions", "final_claims", "verification_status",
            "gold_status"}
    if (type(report) is not dict or set(report) != keys
            or report["version"] != VERSION or report["status"] != STATUS
            or report["incident_id"] != draft.incident_id
            or report["tenant_id"] != draft.tenant_id
            or report["draft_id"] != draft.draft_id
            or report["draft_sha256"] != draft.sha256
            or report["retrieved_evidence_ids"] != list(context.evidence_ids)
            or report["s1_sha256"] != review.s1_sha256
            or report["review_kind"] != review.review_kind
            or report["verification_status"] != "V3_SYNTHETIC_DEVELOPMENT_ONLY"
            or report["gold_status"] != "NOT_GOLD"
            or not _nonempty(report["verifier_policy_version"])
            or not _digest(report["verifier_policy_sha256"])
            or type(report["verification"]) is not list
            or type(report["decisions"]) is not list
            or type(report["final_claims"]) is not list
            or len(report["decisions"]) != len(draft.claims)):
        raise ValueError("invalid_s2_report_structure")
    checks = report["verification"]
    decisions = report["decisions"]
    finals = report["final_claims"]
    final_by_id = {item.get("claim_id"): item for item in finals
                   if type(item) is dict}
    if len(final_by_id) != len(finals):
        raise ValueError("invalid_s2_final_claim_set")
    position = 0
    premise_sha256 = _sha("\n---\n".join(hit.passage for hit in
                                         context.hits).encode("utf-8"))
    revisions = {item.source_claim_id: item for item in review.revisions}
    for source_claim, candidate, decision in zip(draft.claims,
                                                  review.candidates, decisions):
        if (type(decision) is not dict
                or set(decision) != {"source_claim_id", "action", "reason",
                                     "final_claim_id", "review_required"}
                or decision["source_claim_id"] != source_claim.claim_id
                or decision["action"] not in
                {"keep", "remove", "abstain", "qualify", "correct"}
                or type(decision["review_required"]) is not bool
                or decision["review_required"] !=
                (decision["final_claim_id"] is None)):
            raise ValueError("invalid_s2_decision")
        if candidate.decision != "atomic_factual":
            if decision != {"source_claim_id": source_claim.claim_id,
                            "action": "abstain",
                            "reason": "ATOMICITY_OR_TYPE_REVIEW",
                            "final_claim_id": None, "review_required": True}:
                raise ValueError("unreviewed_s2_claim_promoted")
            continue
        if position >= len(checks):
            raise ValueError("missing_s2_verification")
        initial = checks[position]
        position += 1
        _validate_assessment(initial, source_claim.claim_id,
                             source_claim.claim_id, "initial", source_claim.text,
                             source_claim.citation_ids, context.evidence_ids,
                             premise_sha256, report)
        revision = revisions.get(source_claim.claim_id)
        eligible_initial = _eligible(initial, source_claim.citation_ids,
                                     candidate.citation_relevance,
                                     candidate.cited_set_support)
        if initial["failure_tag"] is not None:
            expected_action, expected_reason, expected_id = (
                "abstain", "VERIFIER_FAILURE", None)
        elif revision is not None:
            if eligible_initial or position >= len(checks):
                raise ValueError("invalid_s2_revision_verification")
            revised = checks[position]
            position += 1
            new_id = "W5S2C-" + _sha(canonical_bytes({
                "source_claim_id": source_claim.claim_id,
                "action": revision.action, "text": revision.text,
                "citation_ids": revision.citation_ids}))[:20]
            _validate_assessment(revised, source_claim.claim_id, new_id,
                                 "revised", revision.text, revision.citation_ids,
                                 context.evidence_ids, premise_sha256, report)
            if _eligible(revised, revision.citation_ids,
                         revision.citation_relevance,
                         revision.cited_set_support):
                expected_action, expected_reason, expected_id = (
                    revision.action, "REVERIFIED_SUPPORTED", new_id)
            else:
                expected_action, expected_reason, expected_id = (
                    "abstain", "REVISION_UNRESOLVED", None)
        elif eligible_initial:
            expected_action, expected_reason, expected_id = (
                "keep", "V3_AND_CITATIONS_SUPPORTED", source_claim.claim_id)
        elif (initial["prediction"] == "contradicted"
              and initial["decision_reason"] == "DIRECT_RULE_REFUTATION"
              and any(trace["outcome"] == "contradiction"
                      for trace in initial["rule_trace"])):
            expected_action, expected_reason, expected_id = (
                "remove", "DIRECT_EVIDENCE_REFUTATION", None)
        else:
            expected_action, expected_reason, expected_id = (
                "abstain", "UNRESOLVED_OR_UNCITED", None)
        if (decision["action"], decision["reason"], decision["final_claim_id"]) != (
                expected_action, expected_reason, expected_id):
            raise ValueError("s2_decision_does_not_follow_verification")
        if expected_id is not None:
            final = final_by_id.get(expected_id)
            expected_text = (source_claim.text if expected_action == "keep"
                             else revision.text)
            expected_citations = (source_claim.citation_ids if expected_action == "keep"
                                  else revision.citation_ids)
            if final != {"claim_id": expected_id,
                         "source_claim_id": source_claim.claim_id,
                         "text": expected_text,
                         "citation_ids": list(expected_citations),
                         "evidence_ids": list(context.evidence_ids),
                         "prediction": "supported", "review_required": False}:
                raise ValueError("s2_final_claim_not_reverified")
    if (position != len(checks)
            or {item["final_claim_id"] for item in decisions
                if item["final_claim_id"] is not None} != set(final_by_id)):
        raise ValueError("unmatched_s2_verification_or_final_claim")


def _validate_assessment(item: dict, source_id: str, claim_id: str,
                         variant: str, text: str, citations: tuple[str, ...],
                         evidence_ids: tuple[str, ...], premise_sha256: str,
                         report: dict) -> None:
    keys = {"source_claim_id", "claim_id", "variant", "text", "evidence_ids",
            "citation_ids", "premise_sha256", "prediction", "review_required",
            "decision_reason", "rule_trace", "citation_checks",
            "nli_scores_decimal", "model_id", "model_revision", "truncated",
            "policy_version", "policy_sha256", "failure_tag"}
    if (type(item) is not dict or set(item) != keys
            or item["source_claim_id"] != source_id or item["claim_id"] != claim_id
            or item["variant"] != variant or item["text"] != text
            or item["evidence_ids"] != list(evidence_ids)
            or item["citation_ids"] != list(citations)
            or item["premise_sha256"] != premise_sha256
            or item["prediction"] not in
            {"supported", "contradicted", "insufficient"}
            or type(item["review_required"]) is not bool
            or not _nonempty(item["decision_reason"])
            or type(item["rule_trace"]) is not list
            or not item["rule_trace"]
            or item["citation_checks"] != [
                {"evidence_id": evidence_id, "valid": True,
                 "reason": "IN_FIXED_SET"} for evidence_id in citations]
            or item["policy_version"] != report["verifier_policy_version"]
            or item["policy_sha256"] != report["verifier_policy_sha256"]
            or type(item["truncated"]) is not bool):
        raise ValueError("invalid_s2_verification_record")
    if item["failure_tag"] is not None:
        if (item["failure_tag"] != "VERIFIER_FAILURE"
                or item["prediction"] != "insufficient"
                or not item["review_required"]
                or item["decision_reason"] != "VERIFIER_FAILURE"
                or item["nli_scores_decimal"] is not None
                or item["model_id"] is not None
                or item["model_revision"] is not None):
            raise ValueError("invalid_s2_failure_fallback")
    elif (type(item["nli_scores_decimal"]) is not dict
          or set(item["nli_scores_decimal"]) !=
          {"contradiction", "entailment", "neutral"}
          or item["model_id"] != MODEL_ID
          or item["model_revision"] != MODEL_REVISION):
        raise ValueError("missing_s2_model_trace")


def _source_records(context: RetrievedIncident, draft: SyntheticDraft,
                    s1: S1Report, review: ReviewBatch, report: dict) -> dict[str, bytes]:
    by_id = {event.evidence_id: event for event in context.events}
    retrieval = {
        "incident_id": context.bundle.incident_id,
        "tenant_id": context.bundle.tenant_id,
        "query": context.query,
        "evidence": [{"evidence_id": hit.evidence_id,
                      "passage": hit.passage, "source_ref": hit.source_ref,
                      "timestamp_utc": hit.timestamp_utc,
                      "raw_sha256": by_id[hit.evidence_id].provenance.sha256}
                     for hit in context.hits],
    }
    draft_record = {
        "draft_id": draft.draft_id, "draft_sha256": draft.sha256,
        "incident_id": draft.incident_id, "tenant_id": draft.tenant_id,
        "original_text": draft.text,
        "retrieved_evidence_ids": list(draft.retrieved_evidence_ids),
        "claims": [{"claim_id": claim.claim_id, "text": claim.text,
                    "span_start": claim.span_start, "span_end": claim.span_end,
                    "citation_ids": list(claim.citation_ids),
                    "citation_marker_spans": [list(span) for span in
                                              claim.citation_marker_spans],
                    "review_reasons": list(claim.review_reasons)}
                   for claim in draft.claims],
        "s1_sha256": _sha(canonical_bytes(s1.to_record())),
    }
    records = {
        "retrieval.json": canonical_bytes(retrieval),
        "draft.json": canonical_bytes(draft_record),
        "review.json": canonical_bytes(review.to_record()),
        "verification.json": canonical_bytes(report["verification"]),
        "s2_report.json": canonical_bytes(report),
    }
    fork = {"version": VERSION, "status": STATUS,
            "incident_id": draft.incident_id, "tenant_id": draft.tenant_id,
            "retrieval_sha256": _sha(records["retrieval.json"]),
            "draft_sha256": _sha(records["draft.json"]),
            "review_sha256": _sha(records["review.json"]),
            "verification_sha256": _sha(records["verification.json"]),
            "s2_report_sha256": _sha(records["s2_report.json"]),
            "operational_inventory_status": "NOT_ACCESSED_S2"}
    records["fork.json"] = canonical_bytes(fork)
    return records


def _source_hashes(source_draft: Path, source_claims: Path,
                   source_s1: Path) -> dict[str, str]:
    return {name: _sha((path / "manifest.json").read_bytes()) for name, path in
            (("w5_01", source_draft), ("w5_02", source_claims),
             ("w5_03", source_s1))}


def _code_hashes() -> dict[str, str]:
    from egis_soc.development import contract as w4_contract
    from egis_soc.development import fusion, rules
    from egis_soc import development_v2
    result = {"w5_s2": _sha(Path(__file__).read_bytes())}
    result.update({name: _sha(Path(module.__file__).read_bytes()) for name, module in
                   (("w4_contract", w4_contract), ("w4_fusion", fusion),
                    ("w4_rules", rules), ("w3_v2", development_v2))})
    return result


def _manifest(records: dict[str, bytes], source_hashes: dict[str, str],
              backend_binding: dict[str, str], policy_version: str,
              policy_sha256: str) -> dict:
    return {"version": VERSION, "status": STATUS,
            "source_manifest_sha256": source_hashes,
            "output_sha256": {name: _sha(data) for name, data in records.items()},
            "code_sha256": _code_hashes(),
            "backend_binding": backend_binding,
            "policy_version": policy_version,
            "policy_sha256": policy_sha256,
            "gold_status": "NOT_GOLD",
            "research_result": "NOT_RUN_SYNTHETIC_DEVELOPMENT_ONLY"}


def _read_inputs(context: RetrievedIncident, config: GenerationConfig,
                 source_draft: Path, source_claims: Path,
                 source_s1: Path) -> tuple[SyntheticDraft, S1Report]:
    result = verify_claim_archive(context, config, source_draft, source_claims)
    s1 = verify_s1_archive(context, config, source_draft, source_claims,
                           source_s1)
    return result.draft, s1


def create_s2_archive(context: RetrievedIncident, config: GenerationConfig,
                      source_draft: Path, source_claims: Path,
                      source_s1: Path, review: ReviewBatch,
                      verifier: SyntheticV3Verifier,
                      backend_binding: dict[str, str], target: Path) -> dict:
    """Create one immutable fork only after every source and review check."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w5_04_archive_already_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w5_04_archive_parent_required")
    if (type(backend_binding) is not dict or not backend_binding
            or any(not _nonempty(key) or not _nonempty(value)
                   for key, value in backend_binding.items())):
        raise ValueError("invalid_s2_backend_binding")
    paths = tuple(Path(path) for path in (source_draft, source_claims, source_s1))
    draft, s1 = _read_inputs(context, config, *paths)
    report = run_s2(context, draft, s1, review, verifier)
    _validate_report(context, draft, review,
                     json.loads(canonical_bytes(report)))
    records = _source_records(context, draft, s1, review, report)
    manifest = _manifest(records, _source_hashes(*paths), backend_binding,
                         verifier.policy.version, verifier.policy.sha256)
    target.mkdir(exist_ok=False)
    for name, raw in (*records.items(), ("manifest.json", canonical_bytes(manifest))):
        with (target / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return json.loads(canonical_bytes(report))


def verify_s2_archive(context: RetrievedIncident, config: GenerationConfig,
                      source_draft: Path, source_claims: Path,
                      source_s1: Path, review: ReviewBatch,
                      backend_binding: dict[str, str],
                      target: Path) -> dict:
    """Offline hash/contract check. This does not claim a model replay."""
    target = Path(target)
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} != set(FILES) | {"manifest.json"}
            or any((target / name).is_symlink() or not (target / name).is_file()
                   for name in (*FILES, "manifest.json"))):
        raise ValueError("invalid_w5_04_archive_file_set")
    paths = tuple(Path(path) for path in (source_draft, source_claims, source_s1))
    draft, s1 = _read_inputs(context, config, *paths)
    raw = {name: (target / name).read_bytes() for name in FILES}
    try:
        records = {name: json.loads(data) for name, data in raw.items()}
        archived_review = ReviewBatch.from_record(records["review.json"])
        if archived_review != review:
            raise ValueError("w5_04_review_source_drift")
        _review_gate(context, draft, s1, review)
        report = records["s2_report.json"]
        _validate_report(context, draft, review, report)
        fork = records["fork.json"]
        manifest_raw = (target / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid_w5_04_archive_record") from None
    expected_records = _source_records(context, draft, s1, review, report)
    if (raw != expected_records
            or any(raw[name] != canonical_bytes(records[name]) for name in FILES)
            or manifest_raw != canonical_bytes(manifest)
            or records["verification.json"] != report.get("verification")
            or report.get("draft_sha256") != draft.sha256
            or report.get("s1_sha256") != review.s1_sha256
            or report.get("retrieved_evidence_ids") != list(context.evidence_ids)
            or report.get("incident_id") != context.bundle.incident_id
            or report.get("tenant_id") != context.bundle.tenant_id
            or report.get("status") != STATUS
            or fork != {"version": VERSION, "status": STATUS,
                        "incident_id": draft.incident_id,
                        "tenant_id": draft.tenant_id,
                        "retrieval_sha256": _sha(raw["retrieval.json"]),
                        "draft_sha256": _sha(raw["draft.json"]),
                        "review_sha256": _sha(raw["review.json"]),
                        "verification_sha256": _sha(raw["verification.json"]),
                        "s2_report_sha256": _sha(raw["s2_report.json"]),
                        "operational_inventory_status": "NOT_ACCESSED_S2"}
            or manifest != _manifest(raw, _source_hashes(*paths),
                                     backend_binding, report["verifier_policy_version"],
                                     report["verifier_policy_sha256"])):
        raise ValueError("w5_04_archive_drift")
    return report


def read_common_fork(context: RetrievedIncident, config: GenerationConfig,
                     source_draft: Path, source_claims: Path, source_s1: Path,
                     review: ReviewBatch, backend_binding: dict[str, str],
                     target: Path, *,
                     arm: str) -> bytes:
    """Both S2 and prospective S3 consume this identical verified fork blob."""
    if arm not in {"S2", "S3"}:
        raise ValueError("invalid_s2_fork_arm")
    verify_s2_archive(context, config, source_draft, source_claims,
                      source_s1, review, backend_binding, target)
    return (Path(target) / "fork.json").read_bytes()
