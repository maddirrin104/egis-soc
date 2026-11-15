"""Known-answer W3 harness tests keep weak labels outside metric truth."""

import json
import tempfile
import unittest
from pathlib import Path

from egis_soc.development_benchmark import (
    ClassificationCase, RetrievalCase, classification_metrics, retrieval_metrics,
    write_experiment_log,
)


class DevelopmentBenchmarkTests(unittest.TestCase):
    def test_retrieval_known_answer_and_weak_label_denial(self):
        result = retrieval_metrics((
            RetrievalCase("Q1", ("EV-1", "EV-2"), ("EV-3", "EV-1", "EV-2")),
            RetrievalCase("Q2", ("EV-5",), ("EV-4", "EV-6")),
        ))
        self.assertEqual(result["gold_evidence_count"], 3)
        self.assertAlmostEqual(result["recall_at_5_micro"], 2 / 3)
        self.assertAlmostEqual(result["recall_at_10_micro"], 2 / 3)
        self.assertAlmostEqual(result["mrr"], 0.25)
        with self.assertRaises(ValueError):
            retrieval_metrics((RetrievalCase("PDS", ("EV-1",), ("EV-1",),
                                             "AI_REVIEWED_DEV"),))

    def test_three_class_f1_and_create_only_log(self):
        cases = (ClassificationCase("A", "supported", "supported"),
                 ClassificationCase("B", "contradicted", "insufficient"),
                 ClassificationCase("C", "insufficient", "insufficient"))
        result = classification_metrics(cases)
        self.assertEqual(result["case_count"], 3)
        self.assertEqual(result["confusion_matrix"]["contradicted"]["insufficient"], 1)
        self.assertAlmostEqual(result["macro_f1"], (1 + 0 + 2 / 3) / 3)
        with self.assertRaises(ValueError):
            classification_metrics((ClassificationCase("PDS", "supported",
                                                        "supported", "AI_REVIEWED_DEV"),))
        retrieval = retrieval_metrics((RetrievalCase("Q", ("E",), ("E",)),))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run.json"
            digest = write_experiment_log(path, retrieval=retrieval,
                                          classification=result,
                                          code_sha256={"module": "a" * 64}, seed=31)
            self.assertEqual(len(digest), 64)
            record = json.loads(path.read_bytes())
            self.assertEqual(record["real_pilot_recall_f1"],
                             "NOT_RUN_NO_HUMAN_REVIEWED_GOLD")
            with self.assertRaises(FileExistsError):
                write_experiment_log(path, retrieval=retrieval,
                                     classification=result,
                                     code_sha256={"module": "a" * 64}, seed=31)


if __name__ == "__main__":
    unittest.main()
