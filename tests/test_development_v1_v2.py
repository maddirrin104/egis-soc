"""Synthetic W3 baseline contracts; no private labels or model download in tests."""

import math
import tempfile
import unittest
from pathlib import Path

from egis_soc.development_data import DevelopmentData
from egis_soc.development_v1 import DevelopmentPair, DevelopmentV1
from egis_soc.development_v2 import DevelopmentV2, NLIPair


def corpus(*, partition="train"):
    events = tuple({
        "evidence_id": f"EV-{index}", "incident_id": "SYN-INC",
        "tenant_id": "SYN-TENANT", "source_ref": f"synthetic:{index}",
        "timestamp_utc": f"2026-01-01T00:00:{index:02d}+00:00",
        "event_data": {"message": message},
    } for index, message in enumerate((
        "process alpha observed", "process beta observed", "network gamma observed",
        "file delta observed", "registry epsilon observed", "service zeta observed"), 1))
    return DevelopmentData("SYN-INC", "SYN-TENANT", partition, "SYNTHETIC",
                           "synthetic", None, events)


class FakeBackend:
    def __init__(self, logits=(0.0, 3.0, 1.0), truncated=False):
        self.logits = logits
        self.truncated = truncated
        self.calls = 0

    def score(self, premise, hypothesis):
        self.calls += 1
        assert "process alpha observed" in premise
        assert hypothesis
        return self.logits, self.truncated


class DevelopmentBaselineTests(unittest.TestCase):
    def test_v1_three_class_fit_prediction_and_hash_bound_serialization(self):
        data = corpus()
        labels = ("supported", "contradicted", "insufficient") * 2
        samples = tuple((data, DevelopmentPair(
            f"PAIR-{index}", data.incident_id, data.tenant_id, f"claim {index}",
            (f"EV-{index}",), label, "SYNTHETIC_KNOWN_ANSWER"))
            for index, label in enumerate(labels, 1))
        model = DevelopmentV1().fit(samples)
        first = model.predict(*samples[0])
        self.assertEqual(first["training_label_provenance"], "SYNTHETIC_KNOWN_ANSWER")
        self.assertEqual(first["prediction_status"], "DEVELOPMENT_DIAGNOSTIC_NOT_GOLD")
        self.assertAlmostEqual(sum(first["probabilities"].values()), 1.0)
        self.assertIn(first["prediction"], labels)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "v1.joblib"
            digest = model.save(path)
            loaded = DevelopmentV1.load(path, expected_sha256=digest)
            self.assertEqual(loaded.predict(*samples[0]), first)
            with self.assertRaises(ValueError):
                DevelopmentV1.load(path, expected_sha256="0" * 64)
            with self.assertRaises(FileExistsError):
                model.save(path)

    def test_v1_rejects_gold_foreign_scope_test_and_mixed_label_sources(self):
        data = corpus()
        pair = DevelopmentPair("P", data.incident_id, data.tenant_id, "claim",
                               ("EV-1",), "supported", "SYNTHETIC_KNOWN_ANSWER")
        with self.assertRaises(ValueError):
            DevelopmentV1().fit(((data, pair),))
        from egis_soc.development_v1 import pair_text
        for bad in (pair.__class__("P", "OTHER", data.tenant_id, "claim", ("EV-1",),
                                   "supported", "SYNTHETIC_KNOWN_ANSWER"),
                    pair.__class__("P", data.incident_id, data.tenant_id, "claim", ("EV-1",),
                                   "supported", "SYNTHETIC_KNOWN_ANSWER", "GOLD")):
            with self.assertRaises(ValueError):
                pair_text(data, bad)
        with self.assertRaises(ValueError):
            pair_text(corpus(partition="test"), pair)

    def test_v2_mapping_empty_evidence_truncation_and_scope(self):
        data = corpus()
        backend = FakeBackend(truncated=True)
        model = DevelopmentV2(backend)
        pair = NLIPair("P", data.incident_id, data.tenant_id, "alpha was observed", ("EV-1",))
        result = model.predict(data, pair)
        self.assertEqual(result["prediction"], "supported")
        self.assertTrue(result["truncated"])
        self.assertAlmostEqual(sum(result["scores"].values()), 1.0)
        self.assertEqual(backend.calls, 1)
        empty = model.predict(data, NLIPair("EMPTY", data.incident_id,
                                            data.tenant_id, "claim", ()))
        self.assertEqual((empty["prediction"], empty["model_called"]),
                         ("insufficient", False))
        self.assertEqual(backend.calls, 1)
        backend.logits = (4.0, 0.0, 1.0)
        self.assertEqual(model.predict(data, pair)["prediction"], "contradicted")
        backend.logits = (0.0, 1.0, 4.0)
        self.assertEqual(model.predict(data, pair)["prediction"], "insufficient")
        backend.logits = (math.nan, 0.0, 0.0)
        with self.assertRaises(ValueError):
            model.predict(data, pair)
        with self.assertRaises(ValueError):
            model.predict(data, NLIPair("P", "FOREIGN", data.tenant_id,
                                        "claim", ("EV-1",)))
        with self.assertRaises(ValueError):
            model.predict(corpus(partition="OOD"), pair)


if __name__ == "__main__":
    unittest.main()
