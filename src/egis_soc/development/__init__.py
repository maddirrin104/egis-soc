"""Public imports for train-only W3 development components.

Implementations stay at their hash-pinned paths until the private W2/W3
checkpoints are superseded by a separately verified snapshot.
"""

from egis_soc.development_benchmark import (
    ClassificationCase,
    RetrievalCase,
    classification_metrics,
    retrieval_metrics,
    write_experiment_log,
)
from egis_soc.development_benchmark_run import run_fixture, validate_fixture, verify_result
from egis_soc.development_data import (
    DevelopmentData,
    from_synthetic_fixture,
    load_private_pds01_group,
)
from egis_soc.development_retrieval import DevelopmentRetriever, RetrievalHit
from egis_soc.development_v1 import DevelopmentPair, DevelopmentV1
from egis_soc.development_v2 import DevelopmentV2, NLIPair
from egis_soc.development.qa import run_repeated_batch
from egis_soc.development.contract import (
    CitationCheck, OrderedEvidence, RuleTrace, VerifierInput, VerifierOutput,
    run_v2,
)
from egis_soc.development.fusion import FusionPolicy, SyntheticV3Verifier
from egis_soc.development.rules import SyntheticV0Rules

__all__ = [
    "ClassificationCase",
    "CitationCheck",
    "DevelopmentData",
    "DevelopmentPair",
    "DevelopmentRetriever",
    "DevelopmentV1",
    "DevelopmentV2",
    "FusionPolicy",
    "NLIPair",
    "OrderedEvidence",
    "RetrievalCase",
    "RetrievalHit",
    "RuleTrace",
    "SyntheticV0Rules",
    "SyntheticV3Verifier",
    "VerifierInput",
    "VerifierOutput",
    "classification_metrics",
    "from_synthetic_fixture",
    "load_private_pds01_group",
    "retrieval_metrics",
    "run_fixture",
    "run_repeated_batch",
    "run_v2",
    "validate_fixture",
    "verify_result",
    "write_experiment_log",
]
