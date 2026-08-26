"""HF token storage for gated models (`kiln login`).

Precedence: HF_TOKEN env var > stored token file.
Token file lives under the platform config dir with restrictive permissions
(0600 on POSIX). On Windows, file ACLs are not restricted per-user by chmod;
we document this instead of pretending.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from kiln.utils.platform import is_windows


def config_root() -> Path:
    """Kiln's config root (~/.kiln), overridable via KILN_HOME."""
    override = os.environ.get("KILN_HOME")
    if override:
        return Path(override)
    return Path.home() / ".kiln"


def token_path() -> Path:
    return config_root() / "token"


def load_token() -> str | None:
    """Resolve the HF token: env first, then the stored token file."""
    env_token = os.environ.get("HF_TOKEN")
    if env_token:
        return env_token
    p = token_path()
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def save_token(token: str) -> Path:
    """Persist the token with 0600 on POSIX; returns its path."""
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token.strip() + "\n", encoding="utf-8")
    if not is_windows():
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    return p


def clear_token() -> bool:
    """Remove the stored token. Returns True if a token file existed."""
    p = token_path()
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
