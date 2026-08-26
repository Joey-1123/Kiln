"""Path containment utilities.

Windows-safe: uses os.path.realpath + os.path.commonpath instead of
Path.resolve() + relative_to(), which breaks on Windows 8.3 short names.
All untrusted/user-supplied paths that must stay inside a root go through
these helpers.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathEscapeError(Exception):
    """A path tried to escape its allowed root."""


def contained_path(root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> Path:
    """Resolve ``candidate`` and require it to live inside ``root``.

    Returns the resolved absolute path. Raises PathEscapeError if the
    candidate escapes the root (including via symlink traversal, which
    realpath resolves before comparison).
    """
    root_real = os.path.realpath(str(root))
    candidate_real = os.path.realpath(str(candidate))
    try:
        common = os.path.commonpath([root_real, candidate_real])
    except ValueError as exc:  # mixed drives on Windows
        raise PathEscapeError(f"{candidate!r} is not inside {root!r}") from exc
    if common != root_real:
        raise PathEscapeError(f"{candidate!r} escapes allowed root {root!r}")
    return Path(candidate_real)


def atomic_write(target: Path, data: bytes) -> None:
    """Write bytes to ``target`` atomically via mkstemp + os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = _mkstemp_in(target.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _mkstemp_in(directory: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(prefix=".kiln-tmp-", dir=str(directory))


def reject_symlink(path: str | os.PathLike[str]) -> None:
    """Raise if any component of ``path`` is a symlink or junction."""
    current = Path(path)
    for part in [current, *current.parents]:
        if part.is_symlink():
            raise PathEscapeError(f"symlinked path component rejected: {part}")
