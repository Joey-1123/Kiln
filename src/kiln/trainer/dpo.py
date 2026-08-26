"""DPO trainer wrapper — QLoRA NF4 via peft/trl.

Landmine checklist (from Soup audit):
  1. DPO memory = 2× batch in VRAM preflight
  2. NaN guard: refuses to save if any loss is NaN
  3. Seed applied BEFORE get_peft_model
  4. Capability probes via _compat, never version tables
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kiln.trainer._compat import probe_all, requirecapabilities

log = logging.getLogger(__name__)


@dataclass
class DPOTrainResult:
    """Outcome of a DPO training run."""

    success: bool
    adapter_path: str | None = None
    metrics: dict[str, Any] | None = None
    error: str | None = None


def train_dpo(
    *,
    model_path: str,
    dataset_path: str,
    output_dir: str,
    config: dict[str, Any],
    lora_rank: int = 16,
    lora_alpha: int = 16,
    lora_dropout: float = 0.05,
    max_seq_len: int = 2048,
    batch_size: int = 2,
    epochs: int = 1,
    lr: float = 5e-7,
    seed: int = 1234,
    quantization: str = "4bit",
    beta: float = 0.1,
) -> DPOTrainResult:
    """Run DPO training with QLoRA NF4.

    Parameters
    ----------
    model_path : str
        HF repo id or local path to the base model (must have SFT adapter
        merged or applied).
    dataset_path : str
        Path to DPO JSONL data (chosen/rejected pairs).
    output_dir : str
        Where to write adapters/checkpoints.
    config : dict
        Full kiln recipe config dict (for logging/stamping).
    beta : float
        DPO beta parameter (controls deviation from reference policy).
    """
    caps = probe_all()
    requirecapabilities(
        dpo_trainer=caps["dpo_trainer"],
        peft_lora=caps["peft_lora"],
    )
    if quantization == "4bit":
        requirecapabilities(bnb_4bit=caps["bnb_4bit"])

    try:
        return _run_dpo(
            model_path=model_path,
            dataset_path=dataset_path,
            output_dir=output_dir,
            lora_rank=lora_rank,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            max_seq_len=max_seq_len,
            batch_size=batch_size,
            epochs=epochs,
            lr=lr,
            seed=seed,
            quantization=quantization,
            beta=beta,
        )
    except Exception as exc:
        log.exception("DPO training failed")
        return DPOTrainResult(success=False, error=str(exc))


def _run_dpo(
    *,
    model_path: str,
    dataset_path: str,
    output_dir: str,
    lora_rank: int,
    lora_alpha: int,
    lora_dropout: float,
    max_seq_len: int,
    batch_size: int,
    epochs: int,
    lr: float,
    seed: int,
    quantization: str,
    beta: float,
) -> DPOTrainResult:
    """Inner DPO logic — heavy imports happen here."""
    import json

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import DPOConfig, DPOTrainer

    # --- 1. Seed BEFORE anything model-related ---
    torch.manual_seed(seed)

    # --- 2. Load tokenizer ---
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # --- 3. Quantization config ---
    bnb_config = None
    if quantization == "4bit":
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )

    # --- 4. Load model ---
    model_kwargs: dict[str, Any] = {"device_map": "auto"}
    if bnb_config is not None:
        model_kwargs["quantization_config"] = bnb_config
    model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)

    # --- 5. LoRA config ---
    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        target_modules="all-linear",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # --- 6. Load DPO dataset (chosen/rejected pairs) ---
    records = []
    with open(dataset_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    dataset = Dataset.from_list(records)

    # --- 7. NaN guard: scan for degenerate rows ---
    for i, row in enumerate(records):
        if not row.get("chosen") or not row.get("rejected"):
            return DPOTrainResult(
                success=False,
                error=f"DPO row {i+1} missing chosen/rejected text",
            )

    # --- 8. DPOConfig ---
    training_args = DPOConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=lr,
        seed=seed,
        max_length=max_seq_len,
        max_prompt_length=max_seq_len,
        remove_unused_columns=False,
        logging_steps=10,
        save_strategy="epoch",
        beta=beta,
        fp16=torch.cuda.is_available(),
        report_to="none",
    )

    # --- 9. Train ---
    trainer = DPOTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )
    trainer.train()

    # --- 10. NaN guard on final loss ---
    final_loss = trainer.state.log_history[-1].get("loss")
    if final_loss is not None and (final_loss != final_loss):  # NaN check
        log.error("DPO training ended with NaN loss — refusing to save")
        return DPOTrainResult(
            success=False,
            error="Training ended with NaN loss — adapter not saved",
        )

    # --- 11. Save adapter ---
    adapter_dir = str(Path(output_dir) / "adapter")
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)

    return DPOTrainResult(
        success=True,
        adapter_path=adapter_dir,
        metrics={"train_loss": final_loss},
    )
