import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kiln.engine.backends import BackendInfo, clear_registry, register_backend, select_backend
from kiln.engine.gateway import create_gateway
from kiln.engine.messages import QueueTransport
from kiln.quant import validate_artifact


def test_select_backend_require_gptq():
    clear_registry()
    register_backend(BackendInfo(name="cpu", supports_gptq=False))
    register_backend(BackendInfo(name="cuda", supports_gptq=True, supports_gpu=True))
    assert select_backend(require_gptq=True).name == "cuda"
    clear_registry()
    register_backend(BackendInfo(name="cpu", supports_gptq=False))
    assert select_backend(require_gptq=True) is None


def test_select_backend_require_gguf():
    clear_registry()
    register_backend(BackendInfo(name="cpu", supports_gguf=True))
    register_backend(BackendInfo(name="cuda", supports_gguf=False, supports_gpu=True))
    assert select_backend(require_gguf=True).name == "cpu"


def test_validate_artifact_missing_dir(tmp_path: Path):
    from kiln.utils.errors import KilnError

    with pytest.raises(KilnError):
        validate_artifact(str(tmp_path / "nope"), "gptq")


def test_validate_artifact_missing_config(tmp_path: Path):
    from kiln.utils.errors import KilnError

    (tmp_path / "m").mkdir()
    with pytest.raises(KilnError):
        validate_artifact(str(tmp_path / "m"), "gptq")


def test_validate_artifact_gptq_without_qcfg(tmp_path: Path):
    from kiln.utils.errors import KilnError

    d = tmp_path / "gptq_m"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"model_type": "llama"}))
    with pytest.raises(KilnError) as exc:
        validate_artifact(str(d), "gptq")
    assert "lacks quantization_config" in str(exc.value.message)


def test_validate_artifact_gptq_with_qcfg(tmp_path: Path):
    d = tmp_path / "good"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"quantization_config": {"bits": 4}}))
    validate_artifact(str(d), "gptq")


def test_validate_artifact_awq_allows_missing_qcfg(tmp_path: Path):
    d = tmp_path / "awq_m"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"model_type": "llama"}))
    validate_artifact(str(d), "awq")


def test_gateway_rejects_unknown_quant():
    gw = create_gateway(transport=QueueTransport(), model_name="test")
    client = TestClient(gw)
    resp = client.post("/v1/load", json={"model_path": "/tmp/m", "quantization": "fp8"})
    assert resp.status_code == 400
    assert "invalid_quant" in resp.text


def test_gateway_accepts_valid_quant():
    gw = create_gateway(transport=QueueTransport(), model_name="test")
    client = TestClient(gw)
    resp = client.post("/v1/load", json={"model_path": "/tmp/m", "quantization": "none"})
    assert resp.status_code in (500, 504)
