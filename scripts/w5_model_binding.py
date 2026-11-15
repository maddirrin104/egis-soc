"""Offline W5 model binding from the public synthetic W4 archive only.

This deliberately avoids private W2/W3 review modules during synthetic checks.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from egis_soc.development_v2 import MODEL_ID, MODEL_REVISION
from egis_soc.integrity import canonical_bytes


ROOT = Path(__file__).resolve().parents[1]
W4 = ROOT / "experiments" / "w4_matched_synthetic_v1"
W4_MANIFEST_SHA256 = "4e0d32dc51ac029d3d90ddfe71d7945dfff9f72c4d264f7c0a96f7111efb9684"
DEFAULT_CACHE = Path("D:/ml-for-cs/egis-w2-backup/hf-model-cache")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and not path.is_junction()


def _cache_file(path: Path, cache: Path) -> bool:
    if path.is_symlink():
        return path.is_file() and path.resolve().is_relative_to(cache.resolve())
    return _regular(path)


def pinned_binding() -> dict[str, str]:
    """Check the pinned synthetic W4 source/model bytes without private data."""
    manifest_path = W4 / "manifest.json"
    if not _regular(manifest_path) or _sha(manifest_path) != W4_MANIFEST_SHA256:
        raise ValueError("w5_w4_synthetic_manifest_changed")
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if (manifest_raw != canonical_bytes(manifest)
            or manifest.get("model_id") != MODEL_ID
            or manifest.get("model_revision") != MODEL_REVISION
            or manifest.get("dataset_kind") != "authored_synthetic_train"
            or manifest.get("gold_status") != "NOT_GOLD"):
        raise ValueError("w5_w4_synthetic_binding_invalid")
    for rel, digest in manifest["code_sha256"].items():
        path = ROOT / rel
        if not _regular(path) or _sha(path) != digest:
            raise ValueError("w5_w4_source_hash_changed")
    for rel, digest in (("tests/fixtures/w4_matched_synthetic_v1.json",
                         manifest["fixture_sha256"]),
                        ("experiments/w4_matched_synthetic_v1/result.json",
                         manifest["result_sha256"])):
        path = ROOT / rel
        if not _regular(path) or _sha(path) != digest:
            raise ValueError("w5_w4_synthetic_result_changed")
    cache = Path(os.environ.get("EGIS_W5_MODEL_CACHE", str(DEFAULT_CACHE)))
    snapshot = (cache / "hub" / "models--cross-encoder--nli-distilroberta-base"
                / "snapshots" / MODEL_REVISION)
    if (not snapshot.is_dir() or snapshot.is_symlink()
            or snapshot.is_junction()):
        raise ValueError("w5_pinned_model_cache_missing")
    hashes = manifest["model_cache_file_sha256"]
    if type(hashes) is not dict or not hashes:
        raise ValueError("w5_w4_synthetic_binding_invalid")
    for name, digest in hashes.items():
        path = snapshot / name
        if (type(name) is not str or "/" in name or "\\" in name
                or not _cache_file(path, cache) or _sha(path) != digest):
            raise ValueError("w5_pinned_model_cache_changed")
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return {"kind": "pinned_local_transformers_nli",
            "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
            **{"cache/" + name: digest for name, digest in hashes.items()}}
