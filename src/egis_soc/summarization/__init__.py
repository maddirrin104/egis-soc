"""W5 synthetic summarization-stage contracts."""

from .contract import (
    AtomicDraftClaim, ClaimAssessment, RetrievedIncident, StructuredDraftReport,
    SyntheticDraft, retrieve_synthetic_incident, verify_synthetic_draft,
)
from .generation import (
    GeneratedDraft, GenerationConfig, GenerationFailure, OllamaLocalBackend,
    generate_and_archive, verify_archive,
)
from .atomization import (
    AtomizationFailure, AtomizationResult, create_claim_archive,
    extract_generated_candidates, verify_claim_archive,
)
from .s1 import (
    CitationAudit, S1Report, create_s1_archive, render_s1, verify_s1_archive,
)
from .s2 import (
    ReviewBatch, ReviewedCandidate, ReviewedRevision, create_s2_archive,
    read_common_fork, run_s2, verify_s2_archive,
)
from .omission import (
    build_operational_inventory, check_operational_omissions,
    create_omission_archive, verify_omission_archive,
)
from .s3 import (
    RepairAction, RepairPlan, RepairRound, create_s3_archive,
    run_s3, verify_s3_archive,
)
from .final_report import (
    build_final_report, create_final_archive, verify_final_archive,
)
from .review_api import ReviewApp, ReviewStore

__all__ = [
    "AtomicDraftClaim", "ClaimAssessment", "RetrievedIncident",
    "StructuredDraftReport", "SyntheticDraft", "retrieve_synthetic_incident",
    "verify_synthetic_draft",
    "GeneratedDraft", "GenerationConfig", "GenerationFailure",
    "OllamaLocalBackend", "generate_and_archive", "verify_archive",
    "AtomizationFailure", "AtomizationResult", "create_claim_archive",
    "extract_generated_candidates", "verify_claim_archive",
    "CitationAudit", "S1Report", "create_s1_archive", "render_s1",
    "verify_s1_archive",
    "ReviewBatch", "ReviewedCandidate", "ReviewedRevision",
    "create_s2_archive", "read_common_fork", "run_s2",
    "verify_s2_archive",
    "build_operational_inventory", "check_operational_omissions",
    "create_omission_archive", "verify_omission_archive",
    "RepairAction", "RepairPlan", "RepairRound",
    "create_s3_archive", "run_s3", "verify_s3_archive",
    "build_final_report", "create_final_archive", "verify_final_archive",
    "ReviewApp", "ReviewStore",
]
