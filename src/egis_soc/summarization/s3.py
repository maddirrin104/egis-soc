"""W5-06 synthetic S3 controlled repair from one verified S2 fork.

Operational candidates are review inputs, not gold. Changed/additional claims
must be exact source-observed propositions and pass a fresh V3/citation check.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from egis_soc.development.fusion import SyntheticV3Verifier
from egis_soc.development_v2 import MAX_TOKENS
from egis_soc.integrity import canonical_bytes

from .contract import RetrievedIncident
from .generation import GenerationConfig
from .omission import (
    _match, check_operational_omissions,
    verify_omission_archive,
)
from .s2 import (
    ReviewBatch, _eligible, _validate_assessment, _verify, verify_s2_archive,
)


VERSION = "w5-06-synthetic-s3-1"
STATUS = "SYNTHETIC_S3_REPAIR_NOT_GOLD"
POLICY = "w5-06-source-exact-v3-two-rounds-1"
REVIEW_KIND = "AUTHORED_SYNTHETIC_REPAIR_REVIEW_NOT_GOLD"
MAX_ROUNDS = 2
FILES = ("plan.json", "s3_report.json", "manifest.json")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip()


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value)


@dataclass(frozen=True)
class RepairAction:
    action: str  # add, remove, qualify, rewrite, abstain
    target_claim_id: str | None
    fact_id: str | None
    proposed_text: str | None
    citation_ids: tuple[str, ...]
    reviewer_id: str
    rationale: str
    citation_relevance: tuple[str, ...] = ()
    cited_set_support: str = "not_assessed"

    def __post_init__(self) -> None:
        if (self.action not in {"add", "remove", "qualify", "rewrite", "abstain"}
                or not _nonempty(self.reviewer_id)
                or not _nonempty(self.rationale)
                or type(self.citation_ids) is not tuple
                or type(self.citation_relevance) is not tuple
                or any(not _nonempty(item) for item in self.citation_ids)
                or len(set(self.citation_ids)) != len(self.citation_ids)
                or any(item not in {"relevant", "irrelevant", "not_assessed"}
                       for item in self.citation_relevance)):
            raise ValueError("invalid_s3_repair_action")
        if self.action in {"add", "qualify", "rewrite"}:
            if (not _nonempty(self.fact_id) or not _nonempty(self.proposed_text)
                    or not self.citation_ids
                    or len(self.citation_relevance) != len(self.citation_ids)
                    or any(item != "relevant" for item in self.citation_relevance)
                    or self.cited_set_support != "supported"
                    or (self.action == "add") != (self.target_claim_id is None)
                    or (self.target_claim_id is not None
                        and not _nonempty(self.target_claim_id))):
                raise ValueError("invalid_s3_evidence_backed_action")
        elif (self.proposed_text is not None or self.citation_ids
              or self.citation_relevance or self.cited_set_support != "not_assessed"
              or (self.action == "remove" and
                  (not _nonempty(self.target_claim_id) or self.fact_id is not None))
              or (self.action == "abstain" and
                  (self.target_claim_id is None) == (self.fact_id is None))
              or (self.fact_id is not None and not _nonempty(self.fact_id))
              or (self.target_claim_id is not None
                  and not _nonempty(self.target_claim_id))):
            raise ValueError("invalid_s3_no_assertion_action")


@dataclass(frozen=True)
class RepairRound:
    actions: tuple[RepairAction, ...]

    def __post_init__(self) -> None:
        if (type(self.actions) is not tuple or not self.actions
                or any(type(item) is not RepairAction for item in self.actions)):
            raise ValueError("invalid_s3_repair_round")


@dataclass(frozen=True)
class RepairPlan:
    fork_sha256: str
    omission_sha256: str
    author_id: str
    rationale: str
    rounds: tuple[RepairRound, ...] = ()
    policy_version: str = POLICY
    review_kind: str = REVIEW_KIND

    def __post_init__(self) -> None:
        if (not _digest(self.fork_sha256) or not _digest(self.omission_sha256)
                or not _nonempty(self.author_id) or not _nonempty(self.rationale)
                or type(self.rounds) is not tuple
                or len(self.rounds) > MAX_ROUNDS
                or any(type(item) is not RepairRound for item in self.rounds)
                or self.policy_version != POLICY or self.review_kind != REVIEW_KIND):
            raise ValueError("invalid_s3_repair_plan")

    def to_record(self) -> dict:
        return json.loads(canonical_bytes(asdict(self)))

    @classmethod
    def from_record(cls, record: dict) -> RepairPlan:
        if type(record) is not dict or set(record) != {
                "fork_sha256", "omission_sha256", "author_id", "rationale",
                "rounds", "policy_version", "review_kind"}:
            raise ValueError("invalid_s3_plan_record")
        try:
            rounds = tuple(RepairRound(tuple(RepairAction(
                **{**action, "citation_ids": tuple(action["citation_ids"]),
                   "citation_relevance": tuple(action["citation_relevance"])})
                for action in item["actions"])) for item in record["rounds"])
            plan = cls(record["fork_sha256"], record["omission_sha256"],
                       record["author_id"], record["rationale"], rounds,
                       record["policy_version"], record["review_kind"])
            if plan.to_record() != record:
                raise ValueError("invalid_s3_plan_record")
            return plan
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid_s3_plan_record") from None


def _new_id(plan: RepairPlan, round_index: int, action_index: int,
            action: RepairAction) -> str:
    return "W5S3C-" + _sha(canonical_bytes({
        "fork_sha256": plan.fork_sha256, "round": round_index,
        "action_index": action_index, "action": action.action,
        "target_claim_id": action.target_claim_id,
        "fact_id": action.fact_id, "text": action.proposed_text,
        "citation_ids": action.citation_ids}))[:20]


def _initial_claims(s2_report: dict) -> dict[str, dict]:
    result = {}
    for claim in s2_report["final_claims"]:
        result[claim["claim_id"]] = {
            **claim, "origin": "S2_FORK", "source_fact_id": None}
    if len(result) != len(s2_report["final_claims"]):
        raise ValueError("duplicate_s2_final_claim")
    return result


def _abstained_claims(s2_report: dict) -> dict[str, dict]:
    """Only S2-reviewed, V3-assessed abstentions may be repaired later."""
    latest = {}
    for assessment in s2_report["verification"]:
        latest[assessment["source_claim_id"]] = assessment
    result = {}
    for decision in s2_report["decisions"]:
        if decision["action"] != "abstain":
            continue
        assessment = latest.get(decision["source_claim_id"])
        if assessment is None:
            continue  # An unreviewed/non-atomic candidate never enters repair.
        result[assessment["claim_id"]] = {
            "claim_id": assessment["claim_id"],
            "source_claim_id": decision["source_claim_id"],
            "source_fact_id": None, "text": assessment["text"],
            "citation_ids": assessment["citation_ids"],
            "evidence_ids": assessment["evidence_ids"],
            "prediction": assessment["prediction"],
            "review_required": True, "origin": "S2_ABSTAINED"}
    return result


def _gate(context: RetrievedIncident, s2_report: dict, fork_bytes: bytes,
          inventory: dict, omission: dict, plan: RepairPlan) -> dict[str, dict]:
    """Reject all foreign/fabricated plan inputs before the first V3 call."""
    if type(context) is not RetrievedIncident or type(plan) is not RepairPlan:
        raise TypeError("s3_scoped_context_and_plan_required")
    expected_inventory, expected_omission = check_operational_omissions(
        context, s2_report, fork_bytes)
    if (inventory != expected_inventory or omission != expected_omission
            or plan.fork_sha256 != _sha(fork_bytes)
            or plan.omission_sha256 != _sha(canonical_bytes(omission))):
        raise ValueError("s3_parent_or_inventory_mismatch")
    facts = {item["fact_id"]: item for item in inventory["facts"]}
    findings = {item["fact_id"]: item for item in omission["findings"]}
    if len(facts) != len(inventory["facts"]) or len(findings) != len(facts):
        raise ValueError("s3_inventory_identity_mismatch")
    possible = {**_initial_claims(s2_report), **_abstained_claims(s2_report)}
    used_facts: set[str] = set()
    for round_index, repair_round in enumerate(plan.rounds, 1):
        touched: set[str] = set()
        for action_index, action in enumerate(repair_round.actions, 1):
            if action.target_claim_id is not None:
                if (action.target_claim_id not in possible
                        or action.target_claim_id in touched):
                    raise ValueError("s3_foreign_or_repeated_claim_target")
                touched.add(action.target_claim_id)
                if (action.action in {"qualify", "rewrite"}
                        and possible[action.target_claim_id]["origin"] !=
                        "S2_ABSTAINED"):
                    raise ValueError("s3_rewrite_requires_abstained_s2_claim")
                if (action.action == "remove"
                        and possible[action.target_claim_id]["origin"] ==
                        "S2_ABSTAINED"):
                    raise ValueError("s3_cannot_remove_absent_claim")
            if action.fact_id is not None and action.fact_id not in facts:
                raise ValueError("s3_foreign_or_fabricated_fact")
            if action.action in {"add", "qualify", "rewrite"}:
                fact = facts[action.fact_id]
                if (fact["observability"] != "observable"
                        or fact["statement"] != action.proposed_text
                        or tuple(fact["evidence_ids"]) != action.citation_ids
                        or not set(action.citation_ids) <= set(context.evidence_ids)
                        or action.fact_id in used_facts
                        or findings[action.fact_id]["outcome"] !=
                        "candidate_unmentioned"
                        or (action.action in {"qualify", "rewrite"} and
                            not set(fact["evidence_ids"]) & set(
                                possible[action.target_claim_id]["citation_ids"]))
                        or (action.target_claim_id is not None and
                            possible[action.target_claim_id]["text"] ==
                            action.proposed_text)):
                    raise ValueError("s3_unsupported_or_out_of_scope_proposal")
                used_facts.add(action.fact_id)
                new_id = _new_id(plan, round_index, action_index, action)
                if new_id in possible:
                    raise ValueError("s3_duplicate_repair_claim_id")
                if action.target_claim_id is not None:
                    old = possible.pop(action.target_claim_id)
                else:
                    old = None
                possible[new_id] = {"text": action.proposed_text,
                                    "origin": "S3_REVERIFIED_REPAIR",
                                    "source_claim_id": (None if old is None else
                                                        old["source_claim_id"])}
            elif action.action == "remove":
                possible.pop(action.target_claim_id)
            elif (action.action == "abstain" and action.fact_id is not None
                  and findings[action.fact_id]["outcome"] == "covered"):
                raise ValueError("s3_abstain_target_already_covered")
    return facts


def _token_count(verifier: SyntheticV3Verifier, premise: str,
                 text: str) -> int | None:
    tokenizer = getattr(verifier.nli.backend, "tokenizer", None)
    if tokenizer is None:
        return None
    try:
        count = len(tokenizer(premise, text, truncation=False)["input_ids"])
        return min(count, MAX_TOKENS) if type(count) is int and count >= 0 else None
    except Exception:
        return None


def _final_fact_statuses(inventory: dict, current: dict[str, dict]) -> dict[str, str]:
    result = {}
    for fact in inventory["facts"]:
        if fact["observability"] != "observable":
            status = "unknown"
        else:
            matches = {_match(fact, claim)["result"]
                       for claim in current.values()}
            if "conflict" in matches or "ambiguous" in matches:
                status = "unknown"
            elif "exact_match" in matches:
                status = "covered"
            else:
                status = "candidate_unmentioned"
        result[fact["fact_id"]] = status
    return result


def _review_queue(s2_report: dict, inventory: dict, omission: dict,
                  current: dict[str, dict], failed: list[dict]) -> list[dict]:
    original = {item["fact_id"]: item["outcome"]
                for item in omission["findings"]}
    final = _final_fact_statuses(inventory, current)
    return ([{"fact_id": None, "claim_id": item["source_claim_id"],
              "reason": "S2_ORIGINAL_REQUIRES_REVIEW"}
             for item in s2_report["decisions"] if item["review_required"]]
            + [{"fact_id": item["fact_id"], "claim_id": None,
                "reason": "OPERATIONAL_CANDIDATE_NOT_GOLD_OR_ADJUDICATED"}
               for item in omission["findings"] if item["review_required"]]
            + [{"fact_id": fact_id, "claim_id": None,
                "reason": "S3_REMOVED_PREVIOUS_SOURCE_COVERAGE"}
               for fact_id, status in final.items()
               if status == "candidate_unmentioned"
               and original[fact_id] == "covered"]
            + failed)


def run_s3(context: RetrievedIncident, s2_report: dict, fork_bytes: bytes,
           inventory: dict, omission: dict, plan: RepairPlan,
           verifier: SyntheticV3Verifier | None = None) -> dict:
    """Execute at most two reviewed synthetic rounds; stop on any failed add/edit."""
    facts = _gate(context, s2_report, fork_bytes, inventory, omission, plan)
    needs_v3 = any(action.action in {"add", "qualify", "rewrite"}
                   for repair_round in plan.rounds
                   for action in repair_round.actions)
    if needs_v3 and type(verifier) is not SyntheticV3Verifier:
        raise ValueError("s3_v3_verifier_required_for_repair")
    if verifier is not None and (type(verifier) is not SyntheticV3Verifier
                                or verifier.policy.version !=
                                s2_report["verifier_policy_version"]
                                or verifier.policy.sha256 !=
                                s2_report["verifier_policy_sha256"]):
        raise ValueError("s3_policy_differs_from_s2")
    current = _initial_claims(s2_report)
    abstained = _abstained_claims(s2_report)
    history: list[dict] = []
    verifications: list[dict] = []
    failed_review: list[dict] = []
    premise = "\n---\n".join(hit.passage for hit in context.hits)
    stopped = "NO_REPAIR_PROPOSAL"
    completed_rounds = 0
    for round_index, repair_round in enumerate(plan.rounds, 1):
        stopped = "PLAN_EXHAUSTED_REVIEW"
        for action_index, action in enumerate(repair_round.actions, 1):
            before = ((current.get(action.target_claim_id)
                       or abstained.get(action.target_claim_id))
                      if action.target_claim_id is not None else None)
            proposed_id = (_new_id(plan, round_index, action_index, action)
                           if action.action in {"add", "qualify", "rewrite"}
                           else None)
            record = {
                "round": round_index, "action_index": action_index,
                "action": action.action, "fact_id": action.fact_id,
                "before_claim_id": action.target_claim_id,
                "proposed_claim_id": proposed_id,
                "after_claim_id": None,
                "before_text": None if before is None else before["text"],
                "after_text": None,
                "before_evidence_ids": None if before is None else before["evidence_ids"],
                "after_evidence_ids": None,
                "before_citation_ids": None if before is None else before["citation_ids"],
                "after_citation_ids": None,
                "verification_index": None,
                "result": None,
            }
            if action.action == "remove":
                current.pop(action.target_claim_id)
                record["result"] = "removed"
            elif action.action == "abstain":
                record["result"] = "abstained"
                failed_review.append({"fact_id": action.fact_id,
                                      "claim_id": action.target_claim_id,
                                      "reason": "EXPLICIT_REPAIR_ABSTENTION"})
                stopped = "EXPLICIT_ABSTAIN"
            else:
                tokens = _token_count(verifier, premise, action.proposed_text)
                started = time.perf_counter_ns()
                assessment = _verify(
                    context, verifier,
                    source_claim_id=(action.target_claim_id or action.fact_id),
                    claim_id=proposed_id, variant=f"s3_round_{round_index}",
                    text=action.proposed_text,
                    citation_ids=action.citation_ids)
                latency = time.perf_counter_ns() - started
                record["verification_index"] = len(verifications)
                verifications.append({"round": round_index,
                                      "action_index": action_index,
                                      "nli_input_tokens": tokens,
                                      "v3_latency_ns": latency,
                                      "assessment": assessment})
                if _supported(assessment, action):
                    if before is not None:
                        current.pop(action.target_claim_id, None)
                        abstained.pop(action.target_claim_id, None)
                    current[proposed_id] = {
                        "claim_id": proposed_id,
                        "source_claim_id": (None if before is None else
                                            before["source_claim_id"]),
                        "source_fact_id": action.fact_id,
                        "text": action.proposed_text,
                        "citation_ids": list(action.citation_ids),
                        "evidence_ids": list(context.evidence_ids),
                        "prediction": "supported", "review_required": False,
                        "origin": "S3_REVERIFIED_REPAIR"}
                    record["after_claim_id"] = proposed_id
                    record["after_text"] = action.proposed_text
                    record["after_evidence_ids"] = list(context.evidence_ids)
                    record["after_citation_ids"] = list(action.citation_ids)
                    record["result"] = "reverified_supported"
                else:
                    record["result"] = "rejected_after_v3"
                    stopped = ("VERIFIER_FAILURE" if assessment["failure_tag"]
                               else "REPAIR_NOT_SUPPORTED")
                    failed_review.append({"fact_id": action.fact_id,
                                          "claim_id": action.target_claim_id,
                                          "reason": stopped})
            history.append(record)
            if stopped in {"EXPLICIT_ABSTAIN", "VERIFIER_FAILURE",
                           "REPAIR_NOT_SUPPORTED"}:
                break
        completed_rounds = round_index
        if stopped in {"EXPLICIT_ABSTAIN", "VERIFIER_FAILURE",
                       "REPAIR_NOT_SUPPORTED"}:
            break
    if completed_rounds and stopped == "PLAN_EXHAUSTED_REVIEW":
        pending = any(status == "candidate_unmentioned" for status in
                      _final_fact_statuses(inventory, current).values())
        if not pending:
            stopped = "NO_ACTIONABLE_OMISSION"
        elif completed_rounds == MAX_ROUNDS:
            stopped = "ROUND_CAP_REACHED"
    token_values = [item["nli_input_tokens"] for item in verifications]
    cost = {"v3_calls": len(verifications),
            "nli_input_tokens": (sum(token_values) if all(
                value is not None for value in token_values) else None),
            "nli_token_status": ("NO_CALLS" if not verifications else
                                 "MEASURED" if all(value is not None for value in
                                                   token_values) else "NOT_MEASURED"),
            "v3_latency_ns": sum(item["v3_latency_ns"] for item in verifications),
            "generation_calls": 0,
            "generation_input_tokens": 0,
            "generation_output_tokens": 0}
    return {"version": VERSION, "status": STATUS,
            "incident_id": context.bundle.incident_id,
            "tenant_id": context.bundle.tenant_id,
            "fork_sha256": _sha(fork_bytes),
            "omission_sha256": _sha(canonical_bytes(omission)),
            "inventory_sha256": _sha(canonical_bytes(inventory)),
            "plan_sha256": _sha(canonical_bytes(plan.to_record())),
            "policy_version": POLICY,
            "verifier_policy_version": s2_report["verifier_policy_version"],
            "verifier_policy_sha256": s2_report["verifier_policy_sha256"],
            "s2_final_claim_ids": [item["claim_id"] for item in
                                   s2_report["final_claims"]],
            "final_claims": list(current.values()),
            "history": history, "verifications": verifications,
            "executed_rounds": completed_rounds,
            "stop_reason": stopped,
            "review_queue": _review_queue(
                s2_report, inventory, omission, current, failed_review),
            "s3_only_cost": cost,
            "gold_status": "NOT_GOLD", "cfr_status": "NOT_SCORED"}


def _supported(assessment: dict, action: RepairAction) -> bool:
    return (_eligible(assessment, action.citation_ids,
                      action.citation_relevance, action.cited_set_support)
            and assessment["decision_reason"] == "FULL_RULE_AND_NLI_SUPPORT"
            and not assessment["truncated"]
            and all(item["outcome"] == "pass" for item in
                    assessment["rule_trace"]))


def _validate_report(context: RetrievedIncident, s2_report: dict,
                     fork_bytes: bytes, inventory: dict, omission: dict,
                     plan: RepairPlan, report: dict) -> None:
    """Replay claim lineage from archived V3 traces without calling the model."""
    _gate(context, s2_report, fork_bytes, inventory, omission, plan)
    keys = {"version", "status", "incident_id", "tenant_id", "fork_sha256",
            "omission_sha256", "inventory_sha256", "plan_sha256",
            "policy_version", "verifier_policy_version",
            "verifier_policy_sha256", "s2_final_claim_ids", "final_claims",
            "history", "verifications", "executed_rounds", "stop_reason",
            "review_queue", "s3_only_cost", "gold_status", "cfr_status"}
    if (type(report) is not dict or set(report) != keys
            or report["version"] != VERSION or report["status"] != STATUS
            or report["incident_id"] != context.bundle.incident_id
            or report["tenant_id"] != context.bundle.tenant_id
            or report["fork_sha256"] != _sha(fork_bytes)
            or report["omission_sha256"] != _sha(canonical_bytes(omission))
            or report["inventory_sha256"] != _sha(canonical_bytes(inventory))
            or report["plan_sha256"] != _sha(canonical_bytes(plan.to_record()))
            or report["policy_version"] != POLICY
            or report["verifier_policy_version"] !=
            s2_report["verifier_policy_version"]
            or report["verifier_policy_sha256"] !=
            s2_report["verifier_policy_sha256"]
            or report["s2_final_claim_ids"] != [
                item["claim_id"] for item in s2_report["final_claims"]]
            or type(report["history"]) is not list
            or type(report["verifications"]) is not list
            or type(report["final_claims"]) is not list
            or type(report["review_queue"]) is not list
            or type(report["executed_rounds"]) is not int
            or report["gold_status"] != "NOT_GOLD"
            or report["cfr_status"] != "NOT_SCORED"):
        raise ValueError("invalid_s3_report_structure")
    flat = [(round_index, action_index, action)
            for round_index, repair_round in enumerate(plan.rounds, 1)
            for action_index, action in enumerate(repair_round.actions, 1)]
    history = report["history"]
    traces = report["verifications"]
    if (len(history) > len(flat)
            or (not plan.rounds and (history or traces))):
        raise ValueError("invalid_s3_repair_history")
    current = _initial_claims(s2_report)
    abstained = _abstained_claims(s2_report)
    failed_review = []
    trace_index = 0
    premise_sha256 = _sha("\n---\n".join(
        hit.passage for hit in context.hits).encode("utf-8"))
    stopped = False
    for (round_index, action_index, action), item in zip(flat, history):
        if stopped or type(item) is not dict or set(item) != {
                "round", "action_index", "action", "fact_id",
                "before_claim_id", "proposed_claim_id", "after_claim_id",
                "before_text", "after_text", "before_evidence_ids",
                "after_evidence_ids", "before_citation_ids",
                "after_citation_ids", "verification_index", "result"}:
            raise ValueError("invalid_s3_repair_history")
        before = ((current.get(action.target_claim_id)
                   or abstained.get(action.target_claim_id))
                  if action.target_claim_id is not None else None)
        proposed_id = (_new_id(plan, round_index, action_index, action)
                       if action.action in {"add", "qualify", "rewrite"}
                       else None)
        expected = {
            "round": round_index, "action_index": action_index,
            "action": action.action, "fact_id": action.fact_id,
            "before_claim_id": action.target_claim_id,
            "proposed_claim_id": proposed_id, "after_claim_id": None,
            "before_text": None if before is None else before["text"],
            "after_text": None,
            "before_evidence_ids": None if before is None else before["evidence_ids"],
            "after_evidence_ids": None,
            "before_citation_ids": None if before is None else before["citation_ids"],
            "after_citation_ids": None,
            "verification_index": None, "result": None,
        }
        if action.action == "remove":
            current.pop(action.target_claim_id)
            expected["result"] = "removed"
        elif action.action == "abstain":
            expected["result"] = "abstained"
            failed_review.append({"fact_id": action.fact_id,
                                  "claim_id": action.target_claim_id,
                                  "reason": "EXPLICIT_REPAIR_ABSTENTION"})
            stopped = True
        else:
            if trace_index >= len(traces):
                raise ValueError("missing_s3_reverification")
            trace = traces[trace_index]
            if (type(trace) is not dict or set(trace) != {
                    "round", "action_index", "nli_input_tokens",
                    "v3_latency_ns", "assessment"}
                    or trace["round"] != round_index
                    or trace["action_index"] != action_index
                    or (trace["nli_input_tokens"] is not None and
                        (type(trace["nli_input_tokens"]) is not int or
                         trace["nli_input_tokens"] < 0))
                    or type(trace["v3_latency_ns"]) is not int
                    or trace["v3_latency_ns"] < 0):
                raise ValueError("invalid_s3_verification_cost")
            assessment = trace["assessment"]
            _validate_assessment(
                assessment, action.target_claim_id or action.fact_id,
                proposed_id, f"s3_round_{round_index}", action.proposed_text,
                action.citation_ids, context.evidence_ids,
                premise_sha256, report)
            expected["verification_index"] = trace_index
            trace_index += 1
            if _supported(assessment, action):
                if before is not None:
                    current.pop(action.target_claim_id, None)
                    abstained.pop(action.target_claim_id, None)
                current[proposed_id] = {
                    "claim_id": proposed_id,
                    "source_claim_id": (None if before is None else
                                        before["source_claim_id"]),
                    "source_fact_id": action.fact_id,
                    "text": action.proposed_text,
                    "citation_ids": list(action.citation_ids),
                    "evidence_ids": list(context.evidence_ids),
                    "prediction": "supported", "review_required": False,
                    "origin": "S3_REVERIFIED_REPAIR"}
                expected.update({"after_claim_id": proposed_id,
                                 "after_text": action.proposed_text,
                                 "after_evidence_ids": list(context.evidence_ids),
                                 "after_citation_ids": list(action.citation_ids),
                                 "result": "reverified_supported"})
            else:
                reason = ("VERIFIER_FAILURE" if assessment["failure_tag"]
                          else "REPAIR_NOT_SUPPORTED")
                expected["result"] = "rejected_after_v3"
                failed_review.append({"fact_id": action.fact_id,
                                      "claim_id": action.target_claim_id,
                                      "reason": reason})
                stopped = True
        if item != expected:
            raise ValueError("s3_lineage_does_not_follow_action")
    if trace_index != len(traces):
        raise ValueError("unmatched_s3_reverification")
    if len(history) != len(flat) and (not history or history[-1]["result"] not in
                                     {"abstained", "rejected_after_v3"}):
        raise ValueError("s3_plan_stopped_without_reason")
    executed_rounds = history[-1]["round"] if history else 0
    if not history:
        reason = "NO_REPAIR_PROPOSAL"
    elif history[-1]["result"] == "abstained":
        reason = "EXPLICIT_ABSTAIN"
    elif history[-1]["result"] == "rejected_after_v3":
        assessment = traces[-1]["assessment"]
        reason = ("VERIFIER_FAILURE" if assessment["failure_tag"]
                  else "REPAIR_NOT_SUPPORTED")
    else:
        pending = any(status == "candidate_unmentioned" for status in
                      _final_fact_statuses(inventory, current).values())
        reason = ("NO_ACTIONABLE_OMISSION" if not pending else
                  "ROUND_CAP_REACHED" if executed_rounds == MAX_ROUNDS else
                  "PLAN_EXHAUSTED_REVIEW")
    token_values = [item["nli_input_tokens"] for item in traces]
    cost = {"v3_calls": len(traces),
            "nli_input_tokens": (sum(token_values) if all(
                value is not None for value in token_values) else None),
            "nli_token_status": ("NO_CALLS" if not traces else
                                 "MEASURED" if all(value is not None for value in
                                                   token_values) else "NOT_MEASURED"),
            "v3_latency_ns": sum(item["v3_latency_ns"] for item in traces),
            "generation_calls": 0, "generation_input_tokens": 0,
            "generation_output_tokens": 0}
    if (report["executed_rounds"] != executed_rounds
            or report["stop_reason"] != reason
            or report["final_claims"] != list(current.values())
            or report["review_queue"] != _review_queue(
                s2_report, inventory, omission, current, failed_review)
            or report["s3_only_cost"] != cost):
        raise ValueError("s3_report_not_replayable")


def _read_sources(context: RetrievedIncident, config: GenerationConfig,
                  source_draft: Path, source_claims: Path, source_s1: Path,
                  review: ReviewBatch, backend_binding: dict[str, str],
                  source_s2: Path, source_omission: Path) -> tuple[dict, bytes, dict, dict]:
    s2 = verify_s2_archive(context, config, source_draft, source_claims,
                           source_s1, review, backend_binding, source_s2)
    omission = verify_omission_archive(
        context, config, source_draft, source_claims, source_s1, review,
        backend_binding, source_s2, source_omission)
    fork = (source_s2 / "fork.json").read_bytes()
    inventory = json.loads((source_omission / "inventory.json").read_bytes())
    if (omission["fork_sha256"] != _sha(fork)
            or omission["inventory_sha256"] != _sha(canonical_bytes(inventory))):
        raise ValueError("s3_source_archive_mismatch")
    return s2, fork, inventory, omission


def _manifest(records: dict[str, bytes], source_s2: Path,
              source_omission: Path, fork: bytes) -> dict:
    return {"version": VERSION, "status": STATUS,
            "source_s2_manifest_sha256": _sha((source_s2 / "manifest.json").read_bytes()),
            "source_omission_manifest_sha256": _sha(
                (source_omission / "manifest.json").read_bytes()),
            "source_fork_sha256": _sha(fork),
            "output_sha256": {name: _sha(raw) for name, raw in records.items()},
            "s3_code_sha256": _sha(Path(__file__).read_bytes()),
            "policy_version": POLICY,
            "gold_status": "NOT_GOLD",
            "research_result": "NOT_RUN_SYNTHETIC_DEVELOPMENT_ONLY"}


def create_s3_archive(context: RetrievedIncident, config: GenerationConfig,
                      source_draft: Path, source_claims: Path, source_s1: Path,
                      review: ReviewBatch, backend_binding: dict[str, str],
                      source_s2: Path, source_omission: Path, plan: RepairPlan,
                      verifier: SyntheticV3Verifier | None,
                      target: Path) -> dict:
    """Create a separate S3 run; the verified S2 and W5-05 archives stay fixed."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("w5_06_archive_already_exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("w5_06_archive_parent_required")
    paths = tuple(Path(item) for item in
                  (source_draft, source_claims, source_s1,
                   source_s2, source_omission))
    s2, fork, inventory, omission = _read_sources(
        context, config, *paths[:3], review, backend_binding, *paths[3:])
    report = run_s3(context, s2, fork, inventory, omission, plan, verifier)
    _validate_report(context, s2, fork, inventory, omission, plan,
                     json.loads(canonical_bytes(report)))
    records = {"plan.json": canonical_bytes(plan.to_record()),
               "s3_report.json": canonical_bytes(report)}
    records["manifest.json"] = canonical_bytes(_manifest(
        records, paths[3], paths[4], fork))
    target.mkdir(exist_ok=False)
    for name, raw in records.items():
        with (target / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return json.loads(records["s3_report.json"])


def verify_s3_archive(context: RetrievedIncident, config: GenerationConfig,
                      source_draft: Path, source_claims: Path, source_s1: Path,
                      review: ReviewBatch, backend_binding: dict[str, str],
                      source_s2: Path, source_omission: Path, plan: RepairPlan,
                      target: Path) -> dict:
    """Offline parent/hash/lineage check; recorded V3 outputs are not replayed."""
    target = Path(target)
    if (not target.is_dir() or target.is_symlink()
            or {item.name for item in target.iterdir()} != set(FILES)
            or any((target / name).is_symlink() or not (target / name).is_file()
                   for name in FILES)):
        raise ValueError("invalid_w5_06_archive_file_set")
    paths = tuple(Path(item) for item in
                  (source_draft, source_claims, source_s1,
                   source_s2, source_omission))
    s2, fork, inventory, omission = _read_sources(
        context, config, *paths[:3], review, backend_binding, *paths[3:])
    try:
        raw = {name: (target / name).read_bytes() for name in FILES}
        records = {name: json.loads(data) for name, data in raw.items()}
        archived_plan = RepairPlan.from_record(records["plan.json"])
        if archived_plan != plan:
            raise ValueError("s3_plan_source_drift")
        report = records["s3_report.json"]
        _validate_report(context, s2, fork, inventory, omission, plan, report)
        expected_manifest = _manifest(
            {name: raw[name] for name in ("plan.json", "s3_report.json")},
            paths[3], paths[4], fork)
        if (any(raw[name] != canonical_bytes(records[name]) for name in FILES)
                or records["manifest.json"] != expected_manifest):
            raise ValueError("s3_archive_drift")
        if not plan.rounds and report != run_s3(
                context, s2, fork, inventory, omission, plan):
            raise ValueError("s3_zero_round_replay_drift")
    except (KeyError, TypeError, ValueError, IndexError):
        raise ValueError("invalid_w5_06_archive_record") from None
    return report
