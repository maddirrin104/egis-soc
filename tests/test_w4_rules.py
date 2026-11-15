"""W4-01 controlled synthetic rules: exact support, refutation and abstention."""

import unittest
from dataclasses import replace

from egis_soc.development import DevelopmentData, NLIPair, SyntheticV0Rules, VerifierInput


TIME = "2026-01-01T00:00:00+00:00"
CLAIM = f"record=R1; event=logon; actor=alice; host=WS01; time={TIME}; outcome=success"


def request_for(*bodies, claim=CLAIM, citation_ids=None):
    events = tuple({
        "evidence_id": f"E{index}", "incident_id": "SYN-W4",
        "tenant_id": "SYN-T", "source_ref": f"synthetic:{index}",
        "timestamp_utc": TIME, "event_data": dict(body),
    } for index, body in enumerate(bodies, 1))
    data = DevelopmentData("SYN-W4", "SYN-T", "train", "SYNTHETIC",
                           "synthetic", None, events)
    pair = NLIPair("P1", data.incident_id, data.tenant_id, claim,
                   tuple(event["evidence_id"] for event in events))
    if citation_ids is None:
        citation_ids = pair.evidence_ids
    return VerifierInput.from_synthetic_data(data, pair, citation_ids=citation_ids)


FULL = {"record_ref": "R1", "event_type": "logon", "actor": "alice",
        "host": "WS01", "outcome": "success"}


class SyntheticRuleTests(unittest.TestCase):
    def setUp(self):
        self.rules = SyntheticV0Rules()

    def test_full_support_and_citation_validity_are_separate(self):
        valid = self.rules.evaluate(request_for(FULL, citation_ids=("E1",)))
        self.assertEqual((valid.prediction, valid.review_required, valid.decision_reason),
                         ("supported", False, "FULL_FIELD_SUPPORT"))
        self.assertEqual(tuple(trace.outcome for trace in valid.rule_trace),
                         ("pass", "pass", "pass", "pass"))
        invalid_citation = self.rules.evaluate(request_for(FULL, citation_ids=("FOREIGN",)))
        self.assertEqual((invalid_citation.prediction, invalid_citation.review_required),
                         ("supported", True))
        self.assertEqual(invalid_citation.rule_trace[0].reason, "INVALID_CITATION_ID")
        no_citation = self.rules.evaluate(request_for(FULL, citation_ids=()))
        self.assertEqual((no_citation.prediction, no_citation.review_required),
                         ("supported", True))
        self.assertEqual(no_citation.rule_trace[0].reason, "NO_CITATION")
        irrelevant = self.rules.evaluate(request_for(
            FULL, dict(FULL, record_ref="R2"), citation_ids=("E1", "E2")))
        self.assertEqual((irrelevant.prediction, irrelevant.review_required),
                         ("supported", True))
        self.assertEqual(irrelevant.rule_trace[0].reason, "IRRELEVANT_CITATION")

    def test_multi_evidence_joins_only_explicit_same_record(self):
        first = {"record_ref": "R1", "actor": "alice", "host": "WS01"}
        second = {"record_ref": "R1", "event_type": "logon", "outcome": "success"}
        result = self.rules.evaluate(request_for(first, second))
        self.assertEqual(result.prediction, "supported")
        self.assertEqual(result.rule_trace[1].evidence_ids, ("E1",))
        self.assertEqual(result.rule_trace[3].evidence_ids, ("E2",))
        other_record = dict(second, record_ref="R2")
        self.assertEqual(self.rules.evaluate(request_for(first, other_record)).prediction,
                         "insufficient")

    def test_direct_refutation_requires_complete_unambiguous_record(self):
        result = self.rules.evaluate(request_for(dict(FULL, outcome="failure")))
        self.assertEqual((result.prediction, result.decision_reason),
                         ("contradicted", "DIRECT_FIELD_REFUTATION"))
        self.assertEqual(result.rule_trace[3].outcome, "contradiction")
        missing = dict(FULL, outcome="failure")
        missing.pop("actor")
        self.assertEqual(self.rules.evaluate(request_for(missing)).prediction, "insufficient")

    def test_conflict_missing_malformed_and_absence_abstain(self):
        conflict = self.rules.evaluate(request_for(FULL, dict(FULL, actor="bob")))
        self.assertEqual((conflict.prediction, conflict.review_required),
                         ("insufficient", True))
        self.assertEqual(conflict.rule_trace[1].reason, "CONFLICTING_RECORD_FIELDS")
        self.assertEqual(self.rules.evaluate(request_for({"record_ref": "R2"})).prediction,
                         "insufficient")
        malformed = self.rules.evaluate(request_for(FULL, claim="alice logged in"))
        self.assertEqual((malformed.prediction, malformed.decision_reason),
                         ("insufficient", "MALFORMED_CLAIM"))
        bad_time = self.rules.evaluate(request_for(FULL, claim=CLAIM.replace(TIME, "not-a-time")))
        self.assertEqual(bad_time.decision_reason, "MALFORMED_CLAIM_TIME")
        bad_field = self.rules.evaluate(request_for(dict(FULL, outcome=10)))
        self.assertEqual(bad_field.prediction, "insufficient")
        case_only = self.rules.evaluate(request_for(dict(FULL, host="ws01")))
        self.assertEqual((case_only.prediction, case_only.rule_trace[1].reason),
                         ("insufficient", "CASE_VARIANT_UNRESOLVED"))

    def test_cross_scope_is_rejected_before_rule_evaluation(self):
        request = request_for(FULL)
        event = dict(request.data.events[0], tenant_id="OTHER")
        with self.assertRaises(ValueError):
            VerifierInput.from_synthetic_data(replace(request.data, events=(event,)), request.pair)


if __name__ == "__main__":
    unittest.main()
