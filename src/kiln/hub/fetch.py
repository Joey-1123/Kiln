"""Resumable model downloads via huggingface_hub (imported lazily)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from kiln.hub.auth import load_token
from kiln.hub.preflight import preflight


def probe_model_size(repo_id: str, token: str | None = None) -> int:
    """Total size in bytes of all files in an HF model repo (no download).

    Raises huggingface_hub errors verbatim (repo missing, gated, etc.);
    callers map them to friendly errors.
    """
    from huggingface_hub import HfApi

    info = HfApi(token=token).model_info(repo_id, files_metadata=True)
    total = 0
    for sibling in info.siblings or []:
        if sibling.size:
            total += sibling.size
    if total == 0:
        raise ValueError(f"repo {repo_id!r} reports no file sizes; cannot preflight")
    return total


def fetch_model(
    repo_id: str,
    dest: Path,
    *,
    token: str | None = None,
    allow_patterns: list[str] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> Path:
    """Download a model snapshot into ``dest``, resuming any prior attempt.

    snapshot_download resumes per-file by default and verifies integrity via
    etag metadata, so an interrupted `kiln fetch` continues where it left off.
    """
    resolved_token = token or load_token()
    model_bytes = probe_model_size(repo_id, token=resolved_token)
    preflight(repo_id, str(dest), model_bytes)

    from huggingface_hub import snapshot_download

    if progress_cb:
        progress_cb(f"downloading {repo_id} ({model_bytes / 1e9:.2f} GB)")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(dest),
        token=resolved_token,
        allow_patterns=allow_patterns,
    )
    return dest
