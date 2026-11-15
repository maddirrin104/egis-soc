"""W3-01 retrieval tests use generated, non-gold development events only."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from egis_soc.development_data import DevelopmentData
from egis_soc.development_retrieval import DevelopmentRetriever


def event(evidence_id: str, text: str, *, minute: int = 1,
          source_key: str = "SYN-01", host: str = "host-a") -> dict:
    return {
        "evidence_id": evidence_id, "incident_id": "SYN-INC-1",
        "tenant_id": "SYN-TENANT", "source_ref": f"source:{evidence_id}",
        "source_key": source_key, "timestamp_utc": f"2026-01-01T00:{minute:02d}:00+00:00",
        "host": host, "provider": "synthetic-provider", "event_data": {"message": text},
    }


def corpus(*events: dict) -> DevelopmentData:
    return DevelopmentData("SYN-INC-1", "SYN-TENANT", "train", "SYNTHETIC",
                           "synthetic", None, events)


class DevelopmentRetrievalTests(unittest.TestCase):
    def test_bm25_ranks_term_frequency_and_returns_provenance(self):
        retriever = DevelopmentRetriever(corpus(
            event("EV-1", "beacon beacon beacon"), event("EV-2", "beacon"),
            event("EV-3", "unrelated")))
        hits = retriever.search("beacon", incident_id="SYN-INC-1", tenant_id="SYN-TENANT")
        self.assertEqual([hit.evidence_id for hit in hits], ["EV-1", "EV-2"])
        self.assertGreater(hits[0].score, hits[1].score)
        self.assertEqual(hits[0].source_ref, "source:EV-1")
        self.assertEqual(hits[0].timestamp_utc, "2026-01-01T00:01:00+00:00")
        self.assertEqual(hits[0].provenance["source_ref"], hits[0].source_ref)
        self.assertNotIn("event_data", hits[0].provenance)
        with self.assertRaises(TypeError):
            hits[0].provenance["source_ref"] = "changed"

    def test_incident_tenant_and_input_partition_fail_closed(self):
        data = corpus(event("EV-1", "beacon"))
        retriever = DevelopmentRetriever(data)
        for incident, tenant in (("OTHER", "SYN-TENANT"), ("SYN-INC-1", "OTHER")):
            with self.assertRaises(PermissionError):
                retriever.search("beacon", incident_id=incident, tenant_id=tenant)
        for bad in (data.__class__(data.incident_id, data.tenant_id, "test", "SYNTHETIC",
                                   "synthetic", None, data.events),
                    data.__class__(data.incident_id, data.tenant_id, "train", "OOD",
                                   "synthetic", None, data.events)):
            with self.assertRaises(ValueError):
                DevelopmentRetriever(bad)
        with self.assertRaises(ValueError):
            DevelopmentRetriever(corpus(event("EV-1", "beacon", host="host-a")
                                        | {"tenant_id": "OTHER"}))

    def test_structured_filters_apply_before_scoring(self):
        retriever = DevelopmentRetriever(corpus(
            event("EV-1", "beacon beacon beacon", minute=1),
            event("EV-2", "beacon", minute=2, source_key="SYN-02", host="host-b"),
            event("EV-3", "beacon", minute=3, source_key="SYN-02", host="host-b")))
        scope = {"incident_id": "SYN-INC-1", "tenant_id": "SYN-TENANT"}
        self.assertEqual([hit.evidence_id for hit in retriever.search(
            "beacon", source_key="SYN-02", host="HOST-B", **scope)], ["EV-2", "EV-3"])
        self.assertEqual([hit.evidence_id for hit in retriever.search(
            "beacon", source_ref="source:EV-2", **scope)], ["EV-2"])
        start = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
        self.assertEqual([hit.evidence_id for hit in retriever.search(
            "beacon", start_utc=start, end_utc=end, **scope)], ["EV-2"])
        self.assertEqual(retriever.search("beacon", source_key="MISSING", **scope), ())

    def test_source_filter_excludes_invalid_outside_timestamp_before_parsing(self):
        outside = event("EV-OUTSIDE", "beacon", source_key="OTHER")
        outside["timestamp_utc"] = "unparseable external row"
        retriever = DevelopmentRetriever(corpus(
            outside, event("EV-IN", "beacon", source_key="ALLOWED")))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        hits = retriever.search("beacon", incident_id="SYN-INC-1",
                                tenant_id="SYN-TENANT", source_key="ALLOWED",
                                start_utc=start)
        self.assertEqual([hit.evidence_id for hit in hits], ["EV-IN"])

    def test_tie_order_is_stable_and_empty_query_has_no_hits(self):
        retriever = DevelopmentRetriever(corpus(event("EV-Z", "beacon"),
                                               event("EV-A", "beacon")))
        scope = {"incident_id": "SYN-INC-1", "tenant_id": "SYN-TENANT"}
        expected = ["EV-A", "EV-Z"]
        self.assertEqual([hit.evidence_id for hit in retriever.search("beacon", **scope)], expected)
        self.assertEqual([hit.evidence_id for hit in retriever.search("beacon", **scope)], expected)
        self.assertEqual([hit.evidence_id for hit in retriever.search("beacon", limit=1,
                                                                       **scope)], ["EV-A"])
        self.assertEqual(retriever.search("   ", **scope), ())

    def test_untrusted_text_is_only_tokenized_and_bounds_validate(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "must-not-exist"
            payload = f"__import__('pathlib').Path('{marker}').write_text('bad')"
            retriever = DevelopmentRetriever(corpus(event("EV-1", payload)))
            scope = {"incident_id": "SYN-INC-1", "tenant_id": "SYN-TENANT"}
            hits = retriever.search("write_text", **scope)
            self.assertEqual(len(hits), 1)
            self.assertIn("write_text", hits[0].passage)
            self.assertFalse(marker.exists())
            with self.assertRaises(ValueError):
                retriever.search("write_text", start_utc=datetime(2026, 1, 1), **scope)
            with self.assertRaises(ValueError):
                retriever.search("write_text", limit=0, **scope)


if __name__ == "__main__":
    unittest.main()
