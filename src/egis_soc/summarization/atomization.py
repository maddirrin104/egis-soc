"""W5-02 conservative synthetic claim/citation extraction from a saved draft.

Sentence boundaries are mechanical candidate boundaries. Every generated atom
retains a review warning; this stage never decides factual support or gold.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from egis_soc.integrity import canonical_bytes

from . import contract as w5_contract
from .contract import AtomicDraftClaim, RetrievedIncident, SyntheticDraft
from .generation import GeneratedDraft, GenerationConfig, verify_archive


VERSION = "w5-02-synthetic-atomization-1"
STATUS = "SYNTHETIC_CANDIDATES_NOT_GOLD_NOT_VERIFIED"
_MARKERS_AT_END = re.compile(r"(?:\s*\[[^\[\]]+\])+$")
_MARKER = re.compile(r"\[([^\[\]]+)\]")
_CITATION_ID = re.compile(r"[A-Za-z0-9_.:-]+\Z", re.ASCII)
_COMPOUND = re.compile(r"\b(?:and|or|but)\b|;", re.IGNORECASE)
_MODAL = re.compile(r"\b(?:may|might|could|possibly|likely|perhaps)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|no|never|without)\b", re.IGNORECASE)
_EVIDENCE_LIMIT = re.compile(
    r"^(?:the\s+)?(?:available\s+)?evidence\s+"
    r"(?:does\s+not|cannot|fails\s+to)\s+"
    r"(?:show|establish|prove)\b", re.IGNORECASE)


class AtomizationFailure(ValueError):
    """Fail-closed extraction error, with no implicit S/C/I judgment."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Split terminal punctuation only when followed by whitespace or end."""
    start = 0
    depth = 0
    spans = []
    for index, char in enumerate(text):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth < 0:
                raise AtomizationFailure("UNBALANCED_CITATION_MARKER")
        if (depth == 0 and char in ".!?"
                and (index + 1 == len(text) or text[index + 1].isspace())):
            left = start
            while left <= index and text[left].isspace():
                left += 1
            if left <= index:
                spans.append((left, index + 1))
            start = index + 1
    if depth:
        raise AtomizationFailure("UNBALANCED_CITATION_MARKER")
    left = start
    while left < len(text) and text[left].isspace():
        left += 1
    if left < len(text):
        spans.append((left, len(text)))
    return tuple(spans)


def _one_claim(text: str, start: int, end: int,
               fixed_ids: tuple[str, ...], draft_id: str) -> AtomicDraftClaim:
    segment = text[start:end]
    core = segment[:-1] if segment[-1] in ".!?" else segment
    marker_match = _MARKERS_AT_END.search(core)
    citations = []
    marker_spans = []
    if marker_match is not None:
        prefix = core[:marker_match.start()].rstrip()
        for match in _MARKER.finditer(core, marker_match.start()):
            ids = [item.strip() for item in match.group(1).split(",")]
            if not ids or any(_CITATION_ID.fullmatch(item) is None for item in ids):
                raise AtomizationFailure("MALFORMED_CITATION_ID")
            citations.extend(ids)
            marker_spans.append((start + match.start(), start + match.end()))
    else:
        prefix = core.rstrip()
    if "[" in prefix or "]" in prefix:
        raise AtomizationFailure("CITATION_POSITION_UNRESOLVED")
    if not prefix.strip():
        raise AtomizationFailure("EMPTY_ATOMIC_CANDIDATE")
    if len(citations) != len(set(citations)):
        raise AtomizationFailure("DUPLICATE_CITATION_ID")
    if not set(citations) <= set(fixed_ids):
        raise AtomizationFailure("CITATION_OUTSIDE_FIXED_EVIDENCE")
    claim_start = start
    claim_end = start + len(prefix)
    claim_text = text[claim_start:claim_end]
    reasons = ["AUTO_SEGMENTATION_UNVERIFIED"]
    if not citations:
        reasons.append("UNCITED_FACTUAL_CANDIDATE")
    if _COMPOUND.search(claim_text):
        reasons.append("COMPOUND_BOUNDARY_REVIEW")
    if _MODAL.search(claim_text):
        reasons.append("MODALITY_REVIEW")
    if _NEGATION.search(claim_text):
        reasons.append("NEGATION_REVIEW")
    if _EVIDENCE_LIMIT.search(claim_text):
        reasons.append("CLAIM_TYPE_REVIEW")
    identifier = _sha(f"{draft_id}|{claim_start}|{claim_end}|{claim_text}".encode("utf-8"))
    return AtomicDraftClaim(
        "W5C1-" + identifier[:20], claim_text, claim_start, claim_end,
        fixed_ids, tuple(citations), "factual_candidate", tuple(reasons),
        tuple(marker_spans))


@dataclass(frozen=True)
class AtomizationResult:
    draft: SyntheticDraft
    source_request_sha256: str
    source_response_sha256: str
    source_config_sha256: str
    version: str = VERSION
    status: str = STATUS

    @property
    def review_count(self) -> int:
        return sum(bool(claim.review_reasons) for claim in self.draft.claims)


def extract_generated_candidates(context: RetrievedIncident,
                                 generated: GeneratedDraft) -> AtomizationResult:
    """Derive reviewable candidates; never assign support labels or use gold."""
    if (not isinstance(context, RetrievedIncident)
            or not isinstance(generated, GeneratedDraft)
            or generated.status != "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD"
            or generated.incident_id != context.bundle.incident_id
            or generated.tenant_id != context.bundle.tenant_id
            or generated.evidence_ids != context.evidence_ids):
        raise AtomizationFailure("GENERATED_DRAFT_SCOPE_MISMATCH")
    spans = _sentence_spans(generated.text)
    if not spans:
        raise AtomizationFailure("EMPTY_GENERATED_DRAFT")
    claims = tuple(_one_claim(generated.text, start, end,
                              context.evidence_ids, generated.draft_id)
                   for start, end in spans)
    draft = SyntheticDraft(
        generated.draft_id, generated.incident_id, generated.tenant_id,
        generated.text, generated.evidence_ids, claims,
        generator_id=f"{generated.model_name}@{generated.model_digest}",
        source_kind="SYNTHETIC_LOCAL_GENERATED_NOT_GOLD")
    return AtomizationResult(draft, generated.request_sha256,
                             generated.response_sha256,
                             generated.config_sha256)


def _result_record(result: AtomizationResult) -> dict:
    return {"version": VERSION, "status": STATUS,
            "draft_id": result.draft.draft_id,
            "draft_sha256": result.draft.sha256,
            "source_kind": result.draft.source_kind,
            "incident_id": result.draft.incident_id,
            "tenant_id": result.draft.tenant_id,
            "source_request_sha256": result.source_request_sha256,
            "source_response_sha256": result.source_response_sha256,
            "source_config_sha256": result.source_config_sha256,
            "evidence_ids": list(result.draft.retrieved_evidence_ids),
            "claim_count": len(result.draft.claims),
            "review_count": result.review_count,
            "claims": [{"claim_id": claim.claim_id, "claim_type": claim.claim_type,
                        "text": claim.text, "span_start": claim.span_start,
                        "span_end": claim.span_end,
                        "evidence_ids": list(claim.evidence_ids),
                        "citation_ids": list(claim.citation_ids),
                        "citation_marker_spans": [list(item) for item in
                                                  claim.citation_marker_spans],
                        "review_reasons": list(claim.review_reasons)}
                       for claim in result.draft.claims]}


def _manifest(result_raw: bytes, source_manifest_sha: str) -> dict:
    return {"version": VERSION, "status": STATUS,
            "result_sha256": _sha(result_raw),
            "source_w5_01_manifest_sha256": source_manifest_sha,
            "atomization_code_sha256": _sha(Path(__file__).read_bytes()),
            "contract_code_sha256": _sha(Path(w5_contract.__file__).read_bytes()),
            "gold_status": "NOT_GOLD",
            "verification_status": "NOT_RUN_PRE_VERIFICATION"}


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def create_claim_archive(context: RetrievedIncident, config: GenerationConfig,
                         source_directory: Path, target_directory: Path) -> AtomizationResult:
    """Bind candidate claims to a verified W5-01 archive, then create-only."""
    target_directory = Path(target_directory)
    if target_directory.exists() or target_directory.is_symlink():
        raise FileExistsError("w5_02_claim_archive_already_exists")
    if not target_directory.parent.is_dir() or target_directory.parent.is_symlink():
        raise ValueError("w5_02_archive_parent_required")
    generated = verify_archive(context, config, source_directory)
    result = extract_generated_candidates(context, generated)
    raw = canonical_bytes(_result_record(result))
    source_manifest_sha = _sha((Path(source_directory) / "manifest.json").read_bytes())
    manifest = _manifest(raw, source_manifest_sha)
    target_directory.mkdir(exist_ok=False)
    _write_new(target_directory / "claims.json", raw)
    _write_new(target_directory / "manifest.json", canonical_bytes(manifest))
    return result


def verify_claim_archive(context: RetrievedIncident, config: GenerationConfig,
                         source_directory: Path, target_directory: Path) -> AtomizationResult:
    """Re-extract exact candidates from the original draft; no model call."""
    target_directory = Path(target_directory)
    if (not target_directory.is_dir() or target_directory.is_symlink()
            or {item.name for item in target_directory.iterdir()} !=
            {"claims.json", "manifest.json"}):
        raise ValueError("invalid_w5_02_archive_file_set")
    claim_path = target_directory / "claims.json"
    manifest_path = target_directory / "manifest.json"
    if claim_path.is_symlink() or manifest_path.is_symlink():
        raise ValueError("w5_02_archive_symlink")
    generated = verify_archive(context, config, source_directory)
    result = extract_generated_candidates(context, generated)
    raw = canonical_bytes(_result_record(result))
    source_manifest_sha = _sha((Path(source_directory) / "manifest.json").read_bytes())
    if (claim_path.read_bytes() != raw
            or manifest_path.read_bytes() != canonical_bytes(
                _manifest(raw, source_manifest_sha))):
        raise ValueError("w5_02_claim_archive_drift")
    return result
