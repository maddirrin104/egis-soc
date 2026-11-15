"""W3 V1 three-label TF-IDF/Logistic Regression for development data only."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .development_data import DevelopmentData
from .development_retrieval import DevelopmentRetriever, _passage


VERSION = "w3-v1-development-1"
SEED = 31031
LABELS = ("contradicted", "insufficient", "supported")
PROVENANCES = {"SYNTHETIC_KNOWN_ANSWER", "AI_REVIEWED_DEV"}


@dataclass(frozen=True)
class DevelopmentPair:
    pair_id: str
    incident_id: str
    tenant_id: str
    claim: str
    evidence_ids: tuple[str, ...]
    label: str | None
    annotation_source: str
    gold_status: str = "NOT_GOLD"


def pair_text(data: DevelopmentData, pair: DevelopmentPair) -> str:
    """Resolve the fixed evidence set within one incident before feature creation."""
    DevelopmentRetriever(data)
    if (pair.incident_id != data.incident_id or pair.tenant_id != data.tenant_id
            or not pair.pair_id or not pair.claim.strip()
            or not pair.evidence_ids or len(set(pair.evidence_ids)) != len(pair.evidence_ids)
            or pair.gold_status != "NOT_GOLD"
            or pair.annotation_source not in PROVENANCES):
        raise ValueError("invalid_development_pair_scope_or_provenance")
    passages = []
    for evidence_id in pair.evidence_ids:
        event = data.resolve(evidence_id, incident_id=pair.incident_id,
                             tenant_id=pair.tenant_id)
        passages.append(_passage(event))
    return "Claim: " + pair.claim + "\nEvidence:\n" + "\n---\n".join(passages)


class DevelopmentV1:
    """Fit/predict only; metric authority belongs to the separate harness."""

    def __init__(self) -> None:
        self.model: Any = None
        self.training_source: str | None = None
        self.training_lineages: tuple[str, ...] = ()
        self.training_provenance: str | None = None

    def fit(self, samples: tuple[tuple[DevelopmentData, DevelopmentPair], ...]
            ) -> "DevelopmentV1":
        if len(samples) < 6:
            raise ValueError("three_class_development_fit_needs_six_examples")
        sources = {data.source_dataset for data, _ in samples}
        provenances = {pair.annotation_source for _, pair in samples}
        if len(sources) != 1 or len(provenances) != 1:
            raise ValueError("mixed_development_source_or_label_provenance")
        source = next(iter(sources))
        provenance = next(iter(provenances))
        if ((source == "synthetic" and provenance != "SYNTHETIC_KNOWN_ANSWER")
                or (source == "PDS-01" and provenance != "AI_REVIEWED_DEV")
                or {pair.label for _, pair in samples} != set(LABELS)):
            raise ValueError("invalid_three_class_training_population")
        texts = [pair_text(data, pair) for data, pair in samples]
        labels = [pair.label for _, pair in samples]
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline

        self.model = Pipeline([
            ("tfidf", TfidfVectorizer(lowercase=True, ngram_range=(1, 2),
                                      token_pattern=r"(?u)\b\w+\b")),
            ("lr", LogisticRegression(max_iter=1000, random_state=SEED)),
        ])
        self.model.fit(texts, labels)
        self.training_source = source
        self.training_provenance = provenance
        self.training_lineages = tuple(sorted({data.lineage_group for data, _ in samples}))
        return self

    def predict(self, data: DevelopmentData, pair: DevelopmentPair) -> dict[str, Any]:
        if self.model is None:
            raise ValueError("development_v1_not_fitted")
        text = pair_text(data, pair)
        probabilities = self.model.predict_proba([text])[0]
        classes = list(self.model.classes_)
        return {
            "version": VERSION, "pair_id": pair.pair_id,
            "prediction": classes[max(range(len(classes)), key=lambda i: probabilities[i])],
            "probabilities": {label: float(probabilities[classes.index(label)]) for label in LABELS},
            "prediction_status": "DEVELOPMENT_DIAGNOSTIC_NOT_GOLD",
            "input_label_provenance": pair.annotation_source,
            "training_label_provenance": self.training_provenance,
            "training_source": self.training_source,
            "training_lineages": self.training_lineages,
        }

    def save(self, path: Path) -> str:
        """Write a create-only local model; loading requires an expected digest."""
        if self.model is None:
            raise ValueError("development_v1_not_fitted")
        path = Path(path)
        if path.is_symlink() or path.exists():
            raise FileExistsError("development_v1_model_already_exists")
        import joblib

        with path.open("xb") as stream:
            joblib.dump({"version": VERSION, "model": self.model,
                         "training_source": self.training_source,
                         "training_provenance": self.training_provenance,
                         "training_lineages": self.training_lineages}, stream)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str) -> "DevelopmentV1":
        """Only load an explicitly hash-pinned local artifact (joblib is executable)."""
        path = Path(path)
        if (path.is_symlink() or len(expected_sha256) != 64
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256):
            raise ValueError("untrusted_development_v1_model")
        import joblib

        stored = joblib.load(path)
        if stored.get("version") != VERSION:
            raise ValueError("development_v1_model_version_changed")
        result = cls()
        result.model = stored["model"]
        result.training_source = stored["training_source"]
        result.training_provenance = stored["training_provenance"]
        result.training_lineages = tuple(stored["training_lineages"])
        return result
