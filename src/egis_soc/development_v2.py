"""W3 V2 pretrained NLI baseline adapter for scoped development evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .development_data import DevelopmentData
from .development_retrieval import DevelopmentRetriever, _passage


VERSION = "w3-v2-development-1"
MODEL_ID = "cross-encoder/nli-distilroberta-base"
MODEL_REVISION = "b14d131f9d32668a5e6a982729b57ff6ed5dfcbd"
MODEL_LICENSE = "Apache-2.0"
MAX_TOKENS = 512
NLI_LABELS = ("contradiction", "entailment", "neutral")
LABEL_MAP = {"contradiction": "contradicted",
             "entailment": "supported", "neutral": "insufficient"}


@dataclass(frozen=True)
class NLIPair:
    pair_id: str
    incident_id: str
    tenant_id: str
    claim: str
    evidence_ids: tuple[str, ...]
    gold_status: str = "NOT_GOLD"


class NLIBackend(Protocol):
    def score(self, premise: str, hypothesis: str) -> tuple[tuple[float, float, float], bool]: ...


class TransformersNLIBackend:
    """Local pinned model; no evidence text is sent to a remote inference API."""

    def __init__(self) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, trust_remote_code=False)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, trust_remote_code=False)
        id2label = {int(key): value.casefold()
                    for key, value in self.model.config.id2label.items()}
        if tuple(id2label.get(index) for index in range(3)) != NLI_LABELS:
            raise ValueError("pinned_nli_label_mapping_changed")
        self.model.eval()

    def score(self, premise: str, hypothesis: str) -> tuple[tuple[float, float, float], bool]:
        import torch

        untruncated = self.tokenizer(premise, hypothesis, truncation=False)
        truncated = len(untruncated["input_ids"]) > MAX_TOKENS
        features = self.tokenizer(premise, hypothesis, padding=False,
                                  truncation=True, max_length=MAX_TOKENS,
                                  return_tensors="pt")
        with torch.no_grad():
            logits = self.model(**features).logits[0].tolist()
        if len(logits) != 3:
            raise ValueError("pinned_nli_logit_count_changed")
        return (tuple(float(value) for value in logits), truncated)


def _probabilities(logits: tuple[float, float, float]) -> dict[str, float]:
    if len(logits) != 3 or any(not math.isfinite(value) for value in logits):
        raise ValueError("invalid_nli_logits")
    ceiling = max(logits)
    weights = [math.exp(value - ceiling) for value in logits]
    total = sum(weights)
    return {label: weights[index] / total for index, label in enumerate(NLI_LABELS)}


class DevelopmentV2:
    def __init__(self, backend: NLIBackend | None = None) -> None:
        self.backend = backend if backend is not None else TransformersNLIBackend()

    def predict(self, data: DevelopmentData, pair: NLIPair) -> dict:
        DevelopmentRetriever(data)
        if (pair.incident_id != data.incident_id or pair.tenant_id != data.tenant_id
                or not pair.pair_id or not pair.claim.strip()
                or len(pair.evidence_ids) != len(set(pair.evidence_ids))
                or pair.gold_status != "NOT_GOLD"):
            raise ValueError("invalid_development_nli_pair_scope")
        if not pair.evidence_ids:
            return {"version": VERSION, "pair_id": pair.pair_id,
                    "prediction": "insufficient", "scores": None,
                    "reason": "EMPTY_EVIDENCE", "truncated": False,
                    "model_called": False, "model_id": MODEL_ID,
                    "model_revision": MODEL_REVISION,
                    "status": "DEVELOPMENT_DIAGNOSTIC_NOT_GOLD"}
        premise = "\n---\n".join(_passage(data.resolve(
            evidence_id, incident_id=pair.incident_id, tenant_id=pair.tenant_id))
            for evidence_id in pair.evidence_ids)
        logits, truncated = self.backend.score(premise, pair.claim)
        scores = _probabilities(logits)
        choice = NLI_LABELS[max(range(3), key=lambda index: logits[index])]
        return {"version": VERSION, "pair_id": pair.pair_id,
                "prediction": LABEL_MAP[choice], "scores": scores,
                "reason": "PINNED_NLI_ARGMAX", "truncated": truncated,
                "model_called": True, "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "status": "DEVELOPMENT_DIAGNOSTIC_NOT_GOLD"}
