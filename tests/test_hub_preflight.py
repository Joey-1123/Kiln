"""Preflight math and auth storage — no network, no real disk dependency."""

from __future__ import annotations

import pytest

from kiln.hub.auth import clear_token, load_token, save_token, token_path
from kiln.hub.preflight import DiskPreflight, preflight
from kiln.utils.errors import KilnError


def _gb(n: int) -> int:
    return n * 1024**3


def test_preflight_ok_when_space_sufficient():
    report = preflight("org/model", "/tmp/dest", model_bytes=4_000_000_000,
                       free_space_fn=lambda _: _gb(100))
    assert report.ok
    assert report.required_bytes > report.model_bytes  # margin applied


def test_preflight_refuses_with_exact_numbers():
    with pytest.raises(KilnError) as excinfo:
        preflight("org/model", "/tmp/dest", model_bytes=_gb(50),
                  free_space_fn=lambda _: _gb(20))
    msg = str(excinfo.value)
    assert "org/model" in msg
    assert "free" in msg.lower()


def test_preflight_margin_is_max_5pct_or_512mib():
    small = DiskPreflight(repo_id="x", model_bytes=100_000_000, free_bytes=0, required_bytes=0)
    tiny_report = preflight("x", "/d", 100_000_000, free_space_fn=lambda _: 10**12)
    # 5% of 100 MB is 5 MB < 512 MiB -> margin must be 512 MiB
    assert tiny_report.required_bytes - 100_000_000 >= 512 * 1024 * 1024
    big_report = preflight("x", "/d", _gb(100), free_space_fn=lambda _: 10**12)
    # 5% of 100 GB is 5 GB > 512 MiB -> margin must be ~5%
    assert abs((big_report.required_bytes - _gb(100)) - _gb(5)) < 1_000_000
    del small


def test_token_roundtrip_and_env_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("KILN_HOME", str(tmp_path / ".kiln"))
    monkeypatch.delenv("HF_TOKEN", raising=False)

    assert load_token() is None
    path = save_token("hf_test_123")
    assert path == token_path()
    assert load_token() == "hf_test_123"

    monkeypatch.setenv("HF_TOKEN", "hf_env_token")
    assert load_token() == "hf_env_token"

    monkeypatch.delenv("HF_TOKEN")
    assert clear_token()
    assert not clear_token()  # second removal reports absence
    assert load_token() is None
