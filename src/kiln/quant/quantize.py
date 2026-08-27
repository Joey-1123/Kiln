"""`kiln quantize` — produce persistent GPTQ/AWQ artifacts from an fp16 model.

Control plane is torch-free: :class:`QuantJob` is validated without importing
torch.  The actual quantization runs in :func:`_run_quantize`, which lazy-imports
torch/transformers/auto-gptq/auto-awq only when executing.

Per the reference best-practice (Soup/FreeToken/colibri): a produced quant must be
independently verified, never trusted — the B5 serve load path + parity oracle gate
that (see tests).  Calibration data is required, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kiln.quant import QUANTIZE_SCHEMES
from kiln.utils.errors import KilnError
from kiln.utils.exitcodes import USAGE


@dataclass(frozen=True)
class QuantizeResult:
    """Outcome of a quantize run: scheme + produced artifact paths + sizes."""

    scheme: str
    output_paths: tuple[str, ...]
    sizes_bytes: tuple[int, ...]


@dataclass(frozen=True)
class QuantJob:
    """Torch-free description of a quantize run (validated at construction)."""

    scheme: str
    model_dir: str
    output_dir: str
    calibration_data: str
    bits: int = 4
    group_size: int = 128
    device: str = "auto"

    def __post_init__(self) -> None:
        if self.scheme not in QUANTIZE_SCHEMES:
            raise KilnError(
                message=f"Scheme {self.scheme!r} is not a quantize artifact scheme.",
                hint=(
                    "kiln quantize supports: "
                    + ", ".join(sorted(QUANTIZE_SCHEMES))
                    + ". Use none/4bit/8bit at serve/train time instead."
                ),
                exit_code=USAGE,
            )
        if not Path(self.model_dir).is_dir():
            raise KilnError(
                message=f"Model directory not found: {self.model_dir}",
                hint="Pass the path to a merged HF model directory.",
                exit_code=USAGE,
            )
        if not (Path(self.model_dir) / "config.json").is_file():
            raise KilnError(
                message=f"Not a valid HF model directory: {self.model_dir}",
                hint="The model directory must contain a config.json.",
                exit_code=USAGE,
            )
        if not Path(self.calibration_data).is_file():
            raise KilnError(
                message=f"Calibration data not found: {self.calibration_data}",
                hint="Provide a JSONL file with one text sample per line.",
                exit_code=USAGE,
            )


def _read_calibration_texts(path: str, max_samples: int = 128) -> list[str]:
    """Read calibration texts from a JSONL file (one text per line)."""
    import json

    texts: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= max_samples:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                text = obj.get("text") or obj.get("content") or ""
            except json.JSONDecodeError:
                text = line
            if text:
                texts.append(text)
    if not texts:
        raise KilnError(
            message="No usable calibration samples found.",
            hint="Calibration JSONL needs one non-empty text field or raw line per entry.",
            exit_code=USAGE,
        )
    return texts


def _run_gptq(job: QuantJob) -> QuantizeResult:
    """Quantize to GPTQ via auto-gptq (requires CUDA)."""
    from auto_gptq import AutoGPTQForCausalLM, BaseQuantizeConfig
    from datasets import Dataset
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(job.model_dir, use_fast=True)
    texts = _read_calibration_texts(job.calibration_data)
    tokenized = Dataset.from_dict({"text": texts}).map(
        lambda ex: tokenizer(ex["text"], truncation=True, max_length=2048),
        batched=False,
    )

    out_dir = str(Path(job.output_dir) / "gptq")
    quant_cfg = BaseQuantizeConfig(
        bits=job.bits,
        group_size=job.group_size,
        desc_act=False,
        damp_percent=0.01,
    )
    model = AutoGPTQForCausalLM.from_pretrained(job.model_dir, quantize_config=quant_cfg)
    model.quantize(tokenized)
    model.save_quantized(out_dir)
    tokenizer.save_pretrained(out_dir)

    size = sum(f.stat().st_size for f in Path(out_dir).rglob("*") if f.is_file())
    return QuantizeResult(scheme="gptq", output_paths=(out_dir,), sizes_bytes=(size,))


def _run_awq(job: QuantJob) -> QuantizeResult:
    """Quantize to AWQ via auto-awq, then emit a GGUF (CPU) as well."""
    from awq import AutoAWQForCausalLM
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(job.model_dir, use_fast=True)
    texts = _read_calibration_texts(job.calibration_data)

    awq_dir = str(Path(job.output_dir) / "awq")
    model = AutoAWQForCausalLM.from_pretrained(job.model_dir, low_memory=True)
    model.quantize(
        tokenizer,
        quant_config={"w_bit": job.bits, "q_group_size": job.group_size},
        calib_data=texts,
    )
    model.save_quantized(awq_dir)
    tokenizer.save_pretrained(awq_dir)

    out_paths = [awq_dir]
    sizes = [sum(f.stat().st_size for f in Path(awq_dir).rglob("*") if f.is_file())]

    # Also emit a GGUF for CPU serving (menu tags awq -> cpu).
    from kiln.export import export_gguf

    gguf = export_gguf(model_dir=awq_dir, output_dir=job.output_dir, quant="Q4_K_M")
    out_paths.append(gguf.output_path)
    sizes.append(gguf.size_bytes)

    return QuantizeResult(
        scheme="awq",
        output_paths=tuple(out_paths),
        sizes_bytes=tuple(sizes),
    )


def _run_quantize(job: QuantJob) -> QuantizeResult:
    """Dispatch to the scheme-specific quantizer (torch imported here)."""
    try:
        if job.scheme == "gptq":
            return _run_gptq(job)
        if job.scheme == "awq":
            return _run_awq(job)
    except ImportError as exc:
        raise KilnError(
            message=f"The {job.scheme} quantizer is not installed.",
            hint=f'Install it with: pip install "kiln-cli[quant]" ({exc.name})',
            exit_code=USAGE,
        ) from exc
    raise KilnError(
        message=f"Scheme {job.scheme!r} cannot be quantized by this command.",
        hint=f"Supported: {', '.join(sorted(QUANTIZE_SCHEMES))}",
        exit_code=USAGE,
    )
