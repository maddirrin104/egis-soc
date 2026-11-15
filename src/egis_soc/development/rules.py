"""Conservative W4 V0 rules for a controlled synthetic claim grammar.

Free-form prose and incomplete or conflicting records abstain. These rules do
not infer an event from absence and never interpret log text as instructions.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Mapping

from .contract import RuleTrace, VerifierInput, VerifierOutput


VERSION = "w4-v0-structured-synthetic-1"
_ATOM = re.compile(
    r"record=(?P<record>[A-Za-z0-9_.:-]+); "
    r"event=(?P<event>[A-Za-z0-9_.:-]+); "
    r"actor=(?P<actor>[A-Za-z0-9_.:-]+); "
    r"host=(?P<host>[A-Za-z0-9_.:-]+); "
    r"time=(?P<time>\S+); "
    r"outcome=(?P<outcome>[A-Za-z0-9_.:-]+)",
    re.ASCII,
)
_GROUPS = (
    ("entity", ("actor", "host")),
    ("temporal", ("time",)),
    ("event_semantic", ("event", "outcome")),
)
_EVENT_KEYS = {"event": "event_type", "actor": "actor", "host": "host",
               "outcome": "outcome"}


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_without_timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _trace(group: str, outcome: str, ids: tuple[str, ...], reason: str) -> RuleTrace:
    return RuleTrace(f"{VERSION}:{group}", outcome, ids, reason)


class SyntheticV0Rules:
    """Compare all asserted fields against one exact record identity only."""

    def evaluate(self, request: VerifierInput) -> VerifierOutput:
        if not isinstance(request, VerifierInput):
            raise TypeError("verifier_input_required")
        checks = request.citation_checks
        citation_valid = all(check.valid for check in checks)
        citation_present = bool(checks)
        citation_trace = _trace(
            "citation", "pass" if citation_valid and citation_present else "insufficient",
            tuple(check.evidence_id for check in checks if check.valid),
            ("CITATIONS_IN_FIXED_SET" if citation_valid and citation_present else
             "NO_CITATION" if not citation_present else "INVALID_CITATION_ID"),
        )
        match = _ATOM.fullmatch(request.pair.claim)
        if match is None:
            return self._unresolved(request, citation_trace, "MALFORMED_CLAIM")
        atom = match.groupdict()
        try:
            atom["time"] = _utc(atom["time"])
        except ValueError:
            return self._unresolved(request, citation_trace, "MALFORMED_CLAIM_TIME")

        # The record reference must be explicit in each contributing event.
        matched_rows = []
        for item in request.evidence:
            event = request.data.resolve(item.evidence_id,
                                         incident_id=request.pair.incident_id,
                                         tenant_id=request.pair.tenant_id)
            if event["event_data"].get("record_ref") == atom["record"]:
                matched_rows.append((item.evidence_id, event))
        matched = tuple(matched_rows)
        if not matched:
            return self._unresolved(request, citation_trace, "NO_MATCHED_RECORD")

        if citation_valid and citation_present:
            cited = set(request.citation_ids)
            matched_ids = {evidence_id for evidence_id, _ in matched}
            if not cited <= matched_ids:
                citation_trace = _trace("citation", "insufficient",
                                        request.citation_ids, "IRRELEVANT_CITATION")

        traces = [citation_trace]
        for group, fields in _GROUPS:
            values: dict[str, dict[str, list[str]]] = {field: {} for field in fields}
            malformed = False
            for evidence_id, event in matched:
                body = event["event_data"]
                if not isinstance(body, Mapping):
                    malformed = True
                    continue
                for field in fields:
                    value = event.get("timestamp_utc") if field == "time" else body.get(_EVENT_KEYS[field])
                    if value is None:
                        continue
                    if not isinstance(value, str) or not value.strip():
                        malformed = True
                        continue
                    if field == "time":
                        try:
                            value = _utc(value)
                        except ValueError:
                            malformed = True
                            continue
                    values[field].setdefault(value, []).append(evidence_id)
            ids = tuple(evidence_id for evidence_id, _ in matched
                        if any(evidence_id in sources for field_values in values.values()
                               for sources in field_values.values()))
            if malformed:
                traces.append(_trace(group, "insufficient", ids, "MALFORMED_EVIDENCE_FIELD"))
            elif any(len(values[field]) > 1 for field in fields):
                traces.append(_trace(group, "insufficient", ids, "CONFLICTING_RECORD_FIELDS"))
            elif any(not values[field] for field in fields):
                traces.append(_trace(group, "insufficient", ids, "MISSING_RECORD_FIELD"))
            elif any(next(iter(values[field])) != atom[field]
                     and next(iter(values[field])).casefold() == atom[field].casefold()
                     for field in fields):
                # Without a source-specific identity policy, case-only changes
                # cannot prove either exact support or a semantic refutation.
                traces.append(_trace(group, "insufficient", ids, "CASE_VARIANT_UNRESOLVED"))
            elif any(next(iter(values[field])) != atom[field] for field in fields):
                traces.append(_trace(group, "contradiction", ids, "DIRECT_FIELD_MISMATCH"))
            else:
                traces.append(_trace(group, "pass", ids, "ALL_ASSERTED_FIELDS_MATCH"))

        factual = tuple(traces[1:])
        if any(trace.outcome == "insufficient" for trace in factual):
            prediction, reason = "insufficient", "UNRESOLVED_RULE_EVIDENCE"
        elif any(trace.outcome == "contradiction" for trace in factual):
            prediction, reason = "contradicted", "DIRECT_FIELD_REFUTATION"
        else:
            prediction, reason = "supported", "FULL_FIELD_SUPPORT"
        return VerifierOutput(
            request=request, arm="V0", prediction=prediction,
            review_required=(prediction == "insufficient"
                             or citation_trace.outcome != "pass"),
            decision_reason=reason, rule_trace=tuple(traces),
            citation_checks=checks,
        )

    @staticmethod
    def _unresolved(request: VerifierInput, citation_trace: RuleTrace,
                    reason: str) -> VerifierOutput:
        traces = (citation_trace, *(
            _trace(group, "not_applicable", (), reason) for group, _ in _GROUPS))
        return VerifierOutput(
            request=request, arm="V0", prediction="insufficient",
            review_required=True, decision_reason=reason,
            rule_trace=traces, citation_checks=request.citation_checks,
        )
