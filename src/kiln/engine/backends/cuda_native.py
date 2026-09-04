"""CUDA backend — native torch + transformers NF4.

Heavy imports (torch, transformers, bitsandbytes) happen ONLY inside
functions, never at module level.  This keeps the startup-light probe green.
"""

from __future__ import annotations

import logging
from typing import Any

from kiln.engine.backends import BackendInfo, register_backend
from kiln.engine.parity import GenerationRecord

log = logging.getLogger(__name__)

_INFO = BackendInfo(
    name="cuda",
    device_family="nvidia",
    supports_gpu=True,
    supports_cpu=False,
    supports_streaming=True,
    supports_tools=True,
    supports_nf4=True,
    supports_gptq=True,
    supports_continuous_batching=True,
    supports_cuda_graph=True,
    supports_triton=True,
    supports_offload=True,
    supports_grammar=True,
    requires_cuda=True,
    requires_torch=True,
    description="Native torch+Triton, NF4/GPTQ quantization, batched + CUDA-graph + offload",
)

# ROCm alias — same class; the inference path is device-agnostic (self._model.device),
# so this backend serves AMD hardware via the shared CUDABackend implementation.
_INFO_ROC = BackendInfo(
    name="roc",
    device_family="amd",
    supports_gpu=True,
    supports_cpu=False,
    supports_streaming=True,
    supports_tools=True,
    supports_nf4=True,
    supports_gptq=True,
    supports_continuous_batching=True,
    supports_cuda_graph=True,
    supports_triton=True,
    supports_offload=True,
    supports_grammar=True,
    requires_cuda=True,
    requires_torch=True,
    description="AMD ROCm alias (HIP) — native torch+Triton, NF4/GPTQ, batched + offload",
)


def register() -> None:
    """Register the CUDA backend (never imports torch)."""
    register_backend(_INFO)
    # ROCm alias shares the same device-agnostic backend class.
    register_backend(_INFO_ROC)

class CUDABackend:
    """CUDA inference backend using transformers + NF4.

    All heavy imports are inside methods.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._tokenizer: Any = None
        self._model_path: str = ""

    @property
    def is_loaded(self) -> bool:
        """Whether a model is currently loaded in this backend."""
        return self._model is not None

    @property
    def model_path(self) -> str:
        """Path of the currently loaded model, or None."""
        return self._model_path

    def load_model(self, model_path: str, *, quantization: str = "none") -> None:
        """Load a model with the requested quantization scheme.

        ``none`` loads fp16; ``4bit``/``8bit`` apply bitsandbytes at load time;
        ``gptq``/``awq`` load pre-quantized artifacts (their config.json carries
        the quantizer config).  Unknown schemes raise a mapped USAGE error.
        """
        from transformers import AutoModelForCausalLM, AutoTokenizer

        from kiln.quant.apply import build_quant_spec, resolve_load_quant_config

        spec = build_quant_spec(quantization)
        log.info("Loading CUDA model: %s (quantization=%s)", model_path, quantization)

        if spec.name in ("gptq", "awq"):
            from kiln.quant import validate_artifact

            validate_artifact(model_path, spec.name)

        if spec.name == "gptq":
            try:
                from auto_gptq import AutoGPTQForCausalLM

                model = AutoGPTQForCausalLM.from_pretrained(model_path, device_map="auto")
                tokenizer = AutoTokenizer.from_pretrained(model_path)
                if tokenizer.pad_token is None:
                    tokenizer.pad_token = tokenizer.eos_token
                self._model = model
                self._tokenizer = tokenizer
                self._model_path = model_path
                log.info("Model loaded: %s", model_path)
                return
            except ImportError as exc:
                raise RuntimeError(
                    "GPTQ artifact requires auto-gptq: pip install \"kiln-cli[quant]\""
                ) from exc
        if spec.name == "awq":
            try:
                from awq import AutoAWQForCausalLM

                model = AutoAWQForCausalLM.from_pretrained(model_path, device_map="auto")
                tokenizer = AutoTokenizer.from_pretrained(model_path)
                if tokenizer.pad_token is None:
                    tokenizer.pad_token = tokenizer.eos_token
                self._model = model
                self._tokenizer = tokenizer
                self._model_path = model_path
                log.info("Model loaded: %s", model_path)
                return
            except ImportError:
                pass

        tokenizer = AutoTokenizer.from_pretrained(model_path)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model_kwargs: dict[str, Any] = {"device_map": "auto"}
        quant_config = resolve_load_quant_config(spec)
        if quant_config is not None:
            model_kwargs["quantization_config"] = quant_config

        model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)
        self._model = model
        self._tokenizer = tokenizer
        self._model_path = model_path
        log.info("Model loaded: %s", model_path)

    def load_moe_experts(
        self,
        model_dir: str,
        *,
        strategy: str = "offload",
        gpu_capacity_bytes: int = 8 << 30,
    ) -> Any:
        """Wire the MoE expert topology for ``model_dir`` to real GPU weights.

        Resolves the model's safely sharded expert tensors (B6-1), binds a real
        mover (B6-2) that loads shard bytes onto this model's device, and builds
        an :class:`ExpertBank` (B6-3) driven by it. Returns the bank; the caller
        (engine / CI gate) calls ``ensure_resident`` during decode to physically
        move experts onto the GPU.

        All heavy imports are lazy so the startup-light probe stays green.
        """
        from kiln.engine.expert_bank import ExpertBank, Strategy
        from kiln.engine.expert_mover import TorchExpertMover
        from kiln.engine.moe_forward import MoeForward
        from kiln.engine.safetensors_store import SafetensorsExpertStore

        store = SafetensorsExpertStore(model_dir)
        device = str(self._model.device) if self._model is not None else None
        mover = TorchExpertMover(store.expert_blobs(), device=device)
        bank = ExpertBank(
            gpu_capacity_bytes=gpu_capacity_bytes,
            strategy=Strategy[strategy],
            mover=mover.move,
        )
        store.populate(bank)

        # Bind the decode-phase compute block to this backend's bank + mover so
        # ``routed_forward`` can turn a routing decision into real projection
        # matmuls from the resident weights (B6 forward). The hidden size is
        # taken from the widest expert dim so the identity fallback is sized
        # correctly when a projection tensor is absent.
        hidden = max((getattr(e, "dims", 0) for e in bank.experts.values()), default=0)
        forward = MoeForward(bank, mover=mover, hidden_size=hidden)
        self._expert_mover = mover
        self._moe_forward = forward
        self._moe_bank = bank
        return bank

    @property
    def expert_mover(self) -> Any:
        """The last :class:`TorchExpertMover` created by :meth:`load_moe_experts`."""
        return getattr(self, "_expert_mover", None)

    @property
    def moe_forward(self) -> Any:
        """The :class:`MoeForward` bound to the last :meth:`load_moe_experts`."""
        return getattr(self, "_moe_forward", None)

    @property
    def moe_bank(self) -> Any:
        """The :class:`ExpertBank` built by the last :meth:`load_moe_experts`."""
        return getattr(self, "_moe_bank", None)

    def routed_forward(
        self,
        hidden: Any,
        expert_ids: list[str],
        scores: list[float],
    ) -> Any:
        """Route ``hidden`` through the bound MoE forward (decode phase).

        This is the CPU-testable surface the engine calls for a real MoE layer
        step: it ensures the routed experts are resident in the bank and returns
        the routed expert projection output with the same shape as ``hidden``.
        """
        fwd = self.moe_forward
        if fwd is None:
            raise RuntimeError("No MoE experts loaded (call load_moe_experts first)")
        return fwd.routed(hidden, expert_ids, scores)

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: tuple[str, ...] = (),
        grammar: str = "",
    ) -> str:
        """Generate text from a prompt (non-streaming)."""
        import torch

        if self._model is None:
            raise RuntimeError("No model loaded")

        if grammar:
            # Constrained decoding needs per-token masking, so reuse the
            # streaming loop and join the emitted tokens.
            return "".join(
                tok for tok, _ in self.generate_stream(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop=stop,
                    grammar=grammar,
                )
            )

        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=temperature > 0,
                stop_sequences=list(stop) if stop else None,
            )
        # Decode only new tokens
        new_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True)

    def generate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: tuple[str, ...] = (),
        grammar: str = "",
    ):
        """Generate text token-by-token (streaming generator).

        Yields (token_text, finish_reason_or_none).
        """
        import torch

        if self._model is None:
            raise RuntimeError("No model loaded")

        constraint = self._grammar_constraint(grammar)

        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        generated: list[int] = []
        finish_reason = None

        with torch.no_grad():
            for _ in range(max_tokens):
                model_inputs = {
                    "input_ids": torch.cat(
                        [inputs["input_ids"], torch.tensor([generated], device=self._model.device)],
                        dim=-1,
                    ),
                    "attention_mask": torch.ones(
                        1,
                        inputs["input_ids"].shape[-1] + len(generated),
                        device=self._model.device,
                        dtype=torch.long,
                    ),
                }
                outputs = self._model(**model_inputs)
                next_token_logits = outputs.logits[0, -1, :]

                # Constrained decoding: mask out-of-grammar tokens pre-softmax.
                if constraint is not None and constraint.is_compiled:
                    import xgrammar as xgr

                    bitmask = constraint.fill_next_token_bitmask()
                    xgr.apply_token_bitmask_inplace(
                        next_token_logits.unsqueeze(0),
                        bitmask.to(next_token_logits.device),
                    )

                if temperature > 0:
                    next_token_logits = next_token_logits / temperature
                probs = torch.softmax(next_token_logits, dim=-1)
                if top_p < 1.0:
                    sorted_probs, sorted_indices = torch.sort(probs, descending=True)
                    cumsum = torch.cumsum(sorted_probs, dim=-1)
                    mask = cumsum - sorted_probs > top_p
                    sorted_probs[mask] = 0.0
                    probs = torch.zeros_like(probs).scatter(0, sorted_indices, sorted_probs)
                next_token_id = torch.multinomial(probs, 1).item()
                token_text = self._tokenizer.decode([next_token_id])
                generated.append(next_token_id)

                if constraint is not None and constraint.is_compiled:
                    constraint.accept_token(next_token_id)
                    if constraint.is_terminated():
                        finish_reason = "stop"
                        yield token_text, finish_reason
                        return

                # Check stop sequences
                generated_text = self._tokenizer.decode(generated)
                for s in stop:
                    if s in generated_text:
                        finish_reason = "stop"
                        yield token_text, finish_reason
                        return

                yield token_text, None

        finish_reason = "length"
        yield "", finish_reason

    def unload(self) -> None:
        """Release model from memory."""
        import gc

        self._model = None
        self._tokenizer = None
        self._model_path = ""
        gc.collect()

    def _grammar_constraint(self, grammar: str):
        """Build (lazily) a GrammarConstraint for ``grammar``, or None.

        Failures to compile a *requested* grammar surface as exceptions
        (GrammarUnavailableError / ValueError) — never a silent unconstrained
        fallback.
        """
        from kiln.engine.grammar_constraint import GrammarConstraint

        if not grammar:
            return None
        vocab_size = getattr(self._model.config, "vocab_size", None)
        c = GrammarConstraint(grammar)
        c.compile(tokenizer=self._tokenizer, vocab_size=vocab_size)
        return c

    def generate_parity(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        temperature: float = 0.0,
        topk: int = 10,
    ) -> GenerationRecord:
        """Greedy decode capturing per-step top-k logits for the parity oracle.

        Greedy (temperature 0) is used because the oracle compares the
        argmax path; sampling is non-deterministic across engines.
        """
        import torch

        if self._model is None:
            raise RuntimeError("No model loaded")

        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        generated: list[int] = []
        topk_ids: list[list[int]] = []
        topk_probs: list[list[float]] = []

        with torch.no_grad():
            for _ in range(max_tokens):
                model_inputs = {
                    "input_ids": torch.cat(
                        [inputs["input_ids"], torch.tensor([generated], device=self._model.device)],
                        dim=-1,
                    ),
                    "attention_mask": torch.ones(
                        1,
                        inputs["input_ids"].shape[-1] + len(generated),
                        device=self._model.device,
                        dtype=torch.long,
                    ),
                }
                outputs = self._model(**model_inputs)
                next_logits = outputs.logits[0, -1, :]
                if temperature > 0:
                    next_logits = next_logits / temperature
                probs = torch.softmax(next_logits, dim=-1)
                k = min(topk, probs.shape[-1])
                top_p, top_i = torch.topk(probs, k)
                topk_ids.append(top_i.tolist())
                topk_probs.append(top_p.tolist())
                next_id = int(top_i[0])
                generated.append(next_id)
                if next_id == self._tokenizer.eos_token_id:
                    break

        return GenerationRecord(
            tokens=generated,
            topk_token_ids=topk_ids,
            topk_probs=topk_probs,
        )
