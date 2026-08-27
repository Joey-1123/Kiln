#!/usr/bin/env python3
"""Generate a pinned-torch parity fixture for the A8 cross-backend oracle.

CI-ONLY.  Builds a tiny random-init HF model + byte-level tokenizer and a
reference ``GenerationRecord`` (greedy, temp 0) at cache capacities
``{1, 2, 8}``, emitted as JSON for torch-free consumption by
``tests/test_parity_oracle.py``.

Generation is strictly separated from consumption (plan §8.1 / A8): this
script must run in the dedicated CI job so the gate cannot silently rot.
Regenerate on every release.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

SEED = 1337
N_LAYERS = 2
HIDDEN = 64
INTERMEDIATE = 128
VOCAB = 320
MAX_NEW_TOKENS = 16
TOPK = 10
CAPACITIES = [1, 2, 8]


def build_model(out_dir: Path) -> tuple[object, object]:
    """Create a tiny deterministic Llama-style model + tokenizer (offline)."""
    from tokenizers import Tokenizer
    from tokenizers.models import BPE
    from tokenizers.pre_tokenizers import ByteLevel
    from tokenizers.trainers import BpeTrainer
    from transformers import (
        LlamaConfig,
        LlamaForCausalLM,
        PreTrainedTokenizerFast,
    )

    # Deterministic tiny BPE tokenizer (byte-level, no network).
    tok = Tokenizer(BPE())
    tok.pre_tokenizer = ByteLevel()
    trainer = BpeTrainer(special_tokens=["<s>", "</s>", "<pad>"])
    tok.train_from_iterator([f"example prompt number {i}" for i in range(50)], trainer)
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=tok)
    tokenizer.pad_token = "<pad>"
    tokenizer.eos_token = "</s>"
    tokenizer.bos_token = "<s>"

    cfg = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=HIDDEN,
        intermediate_size=INTERMEDIATE,
        num_hidden_layers=N_LAYERS,
        num_attention_heads=4,
        num_key_value_heads=4,
        max_position_embeddings=64,
    )
    torch.manual_seed(SEED)
    model = LlamaForCausalLM(cfg)
    model.eval()

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    return model, tokenizer


def generate_reference(model, tokenizer, prompt: str, capacities, topk: int):
    """Greedy decode capturing per-step top-k; one record per capacity."""
    from transformers import GenerationConfig

    device = next(model.parameters()).device
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    records: dict[int, dict] = {}
    for cap in capacities:
        # cap selects the KV-cache/context window exercised for this record.
        cfg = GenerationConfig(
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            temperature=0.0,
            top_p=1.0,
            num_return_sequences=1,
            output_scores=True,
            return_dict_in_generate=True,
            max_length=inputs["input_ids"].shape[-1] + MAX_NEW_TOKENS,
            use_cache=True,
        )
        with torch.no_grad():
            out = model.generate(**inputs, generation_config=cfg)
        seq = out.sequences[0][inputs["input_ids"].shape[-1]:].tolist()
        scores = out.scores  # tuple of [1, vocab] logits per step
        topk_ids: list[list[int]] = []
        topk_probs: list[list[float]] = []
        for step_logits in scores:
            probs = torch.softmax(step_logits[0], dim=-1)
            k = min(topk, probs.shape[-1])
            top_p, top_i = torch.topk(probs, k)
            topk_ids.append(top_i.tolist())
            topk_probs.append(top_p.tolist())
        records[cap] = {
            "tokens": seq,
            "topk_token_ids": topk_ids,
            "topk_probs": topk_probs,
        }
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="path to write the fixture JSON")
    ap.add_argument("--model-dir", default=None, help="where to save the HF model")
    ap.add_argument("--prompt", default="The parity oracle checks that", help="prompt to decode")
    args = ap.parse_args()

    model_dir = Path(args.model_dir) if args.model_dir else Path(args.out).parent / "parity_model"
    model, tokenizer = build_model(model_dir)
    reference = generate_reference(model, tokenizer, args.prompt, CAPACITIES, TOPK)

    fixture = {
        "schema_version": 1,
        "name": "generated-tiny",
        "model": str(model_dir),
        "prompts": [args.prompt],
        "capacities": CAPACITIES,
        "temperature": 0.0,
        "tolerance": {
            "top1_token_match_min": 0.99,
            "topk_window_k": TOPK,
            "topk_window_overlap_min": 0.8,
            "task_edit_distance_max": 0.05,
            "require_logit_window": True,
        },
        "reference": reference,
    }
    Path(args.out).write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(f"wrote parity fixture: {args.out} (model at {model_dir})")


if __name__ == "__main__":
    main()
