"""GGUF export — convert merged safetensors to quantized GGUF.

Auto-downloads and builds llama.cpp if not present. Standard quantizations
only (Q4_K_M, Q5_K_M, Q8_0, F16); advanced IQ/UD ladder deferred to V2.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_KILN_DIR = Path.home() / ".kiln"
_LLAMA_CPP_DIR = _KILN_DIR / "llama.cpp"
_LLAMA_CPP_TAG = "b5270"
_LLAMA_CPP_REPO = "https://github.com/ggml-org/llama.cpp.git"

_QUANT_PROFILES: dict[str, str] = {
    "Q4_K_M": "Q4_K_M",
    "Q5_K_M": "Q5_K_M",
    "Q8_0": "Q8_0",
    "F16": "F16",
}

_SUBPROC_TIMEOUT = 30 * 60  # 30 min max per subprocess


@dataclass(frozen=True)
class GGUFResult:
    """Result of a GGUF export (path, quant, size)."""
    output_path: str
    quant: str
    size_bytes: int
    llama_cpp_dir: str


def list_quantizations() -> list[str]:
    """Return the supported GGUF quantization names."""
    return list(_QUANT_PROFILES.keys())


def _ensure_llama_cpp() -> Path:
    """Clone or update llama.cpp and build llama-quantize + convert script."""
    if _llama_quantize_exists(_LLAMA_CPP_DIR):
        return _LLAMA_CPP_DIR

    if _LLAMA_CPP_DIR.exists():
        shutil.rmtree(_LLAMA_CPP_DIR)

    _LLAMA_CPP_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "git", "clone", "--depth", "1",
            "--branch", _LLAMA_CPP_TAG,
            _LLAMA_CPP_REPO,
            str(_LLAMA_CPP_DIR),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )

    _build_llama_cpp(_LLAMA_CPP_DIR)
    return _LLAMA_CPP_DIR


def _llama_quantize_exists(base: Path) -> bool:
    candidates = [
        base / "llama-quantize",
        base / "llama-quantize.exe",
        base / "build" / "bin" / "llama-quantize",
        base / "build" / "bin" / "llama-quantize.exe",
    ]
    return any(c.is_file() for c in candidates)


def _convert_script_exists(base: Path) -> bool:
    return (base / "convert_hf_to_gguf.py").is_file()


def _build_llama_cpp(base: Path) -> None:
    build_dir = base / "build"
    build_dir.mkdir(exist_ok=True)

    subprocess.run(
        [
            "cmake", "-B", str(build_dir), "-S", str(base),
            "-DLLAMA_BUILD_TOOLS=ON",
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )

    nproc = os.cpu_count() or 4
    subprocess.run(
        [
            "cmake", "--build", str(build_dir), "-j", str(nproc),
        ],
        check=True,
        capture_output=True,
        timeout=1800,
    )


def _resolve_quantize_binary(base: Path) -> Path:
    candidates = [
        base / "llama-quantize",
        base / "llama-quantize.exe",
        base / "build" / "bin" / "llama-quantize",
        base / "build" / "bin" / "llama-quantize.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"llama-quantize not found in {base}. Build llama.cpp first."
    )


def _run_convert_to_f16(base: Path, model_dir: str, f16_out: str) -> None:
    script = base / "convert_hf_to_gguf.py"
    if not script.is_file():
        raise FileNotFoundError(
            f"convert_hf_to_gguf.py not found in {base}"
        )

    subprocess.run(
        [sys.executable, str(script), model_dir,
         "--outfile", f16_out, "--outtype", "f16"],
        check=True,
        capture_output=True,
        timeout=600,
    )


def _run_quantize(base: Path, f16_path: str, output: str, quant: str) -> None:
    binary = _resolve_quantize_binary(base)
    subprocess.run(
        [str(binary), f16_path, output, quant],
        check=True,
        capture_output=True,
        timeout=3600,
    )


def export_gguf(
    *,
    model_dir: str,
    output_dir: str,
    quant: str = "Q4_K_M",
    llama_cpp_dir: str | None = None,
) -> GGUFResult:
    """Convert HF model dir to quantized GGUF.

    1. convert_hf_to_gguf.py → f16 GGUF
    2. llama-quantize → final quantized GGUF
    """
    if quant not in _QUANT_PROFILES:
        raise ValueError(
            f"Unknown quantization {quant!r}. "
            f"Available: {', '.join(_QUANT_PROFILES)}"
        )

    model_path = Path(model_dir).resolve()
    if not model_path.is_dir():
        raise FileNotFoundError(f"Model directory not found: {model_path}")

    if not (model_path / "config.json").is_file():
        raise FileNotFoundError(
            f"Not a valid HF model directory (missing config.json): {model_path}"
        )

    if llama_cpp_dir:
        base = Path(llama_cpp_dir).resolve()
        if not _llama_quantize_exists(base):
            raise FileNotFoundError(
                f"llama-quantize not found in {base}. Build llama.cpp first."
            )
    else:
        base = _ensure_llama_cpp()

    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    stem = model_path.name
    gguf_name = f"{stem}.{quant}.gguf"
    output_file = out_path / gguf_name

    with tempfile.TemporaryDirectory(prefix=".kiln_gguf_") as staged:
        f16_path = os.path.join(staged, "model.f16.gguf")

        _run_convert_to_f16(base, str(model_path), f16_path)

        _run_quantize(base, f16_path, str(output_file), quant)

    if not output_file.is_file():
        raise RuntimeError(
            f"llama-quantize did not produce {gguf_name}"
        )

    size = output_file.stat().st_size
    return GGUFResult(
        output_path=str(output_file),
        quant=quant,
        size_bytes=size,
        llama_cpp_dir=str(base),
    )
