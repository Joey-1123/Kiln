"""CPU backend — llama.cpp via llama-cpp-python.

Heavy import (llama_cpp) happens ONLY inside functions.
"""

from __future__ import annotations

import logging
from typing import Any

from kiln.engine.backends import BackendInfo, register_backend
from kiln.engine.parity import GenerationRecord

log = logging.getLogger(__name__)

_INFO = BackendInfo(
    name="cpu",
    supports_gpu=False,
    supports_cpu=True,
    supports_streaming=True,
    supports_tools=False,  # tools not yet implemented for CPU
    supports_nf4=False,
    supports_gptq=False,
    supports_gguf=True,
    supports_continuous_batching=True,
    supports_cuda_graph=False,
    supports_triton=False,
    requires_cuda=False,
    requires_torch=False,
    description="llama.cpp via llama-cpp-python, GGUF format, batched (CPU)",
)


def register() -> None:
    """Register the CPU backend (never imports llama_cpp)."""
    register_backend(_INFO)


class CPUBackend:
    """CPU inference backend using llama.cpp.

    All heavy imports are inside methods.
    """

    def __init__(self) -> None:
        self._llm: Any = None
        self._model_path: str = ""

    @property
    def is_loaded(self) -> bool:
        """Whether a model is currently loaded in this backend."""
        return self._llm is not None

    @property
    def model_path(self) -> str:
        """Path of the currently loaded model, or None."""
        return self._model_path

    def load_model(self, model_path: str, *, n_ctx: int = 4096, n_threads: int = 4) -> None:
        """Load a GGUF model."""
        from llama_cpp import Llama

        log.info("Loading CPU model: %s (n_ctx=%d)", model_path, n_ctx)
        self._llm = Llama(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads)
        self._model_path = model_path
        log.info("Model loaded: %s", model_path)

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: tuple[str, ...] = (),
    ) -> str:
        """Generate text from a prompt (non-streaming)."""
        if self._llm is None:
            raise RuntimeError("No model loaded")

        result = self._llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=list(stop) if stop else None,
        )
        return result["choices"][0]["text"]

    def generate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: tuple[str, ...] = (),
    ):
        """Generate text token-by-token (streaming generator).

        Yields (token_text, finish_reason_or_none).
        """
        if self._llm is None:
            raise RuntimeError("No model loaded")

        finish_reason = None
        for chunk in self._llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=list(stop) if stop else None,
            stream=True,
        ):
            text = chunk["choices"][0]["text"]
            finish_reason = chunk["choices"][0].get("finish_reason")
            yield text, finish_reason if finish_reason != "stop" else None

        if finish_reason == "stop":
            yield "", "stop"

    def unload(self) -> None:
        """Release model from memory."""
        self._llm = None
        self._model_path = ""

    def generate_parity(
        self,
        prompt: str,
        *,
        max_tokens: int = 64,
        temperature: float = 0.0,
        topk: int = 10,
        n_ctx: int = 4096,
    ) -> GenerationRecord:
        """Decode while capturing top-k logits for the parity oracle.

        Uses llama.cpp ``logprobs`` to recover the top-k token ids and
        probabilities per step. Token ids are recovered by re-tokenizing
        the decoded text (llama.cpp returns top tokens as strings).
        """
        if self._llm is None:
            raise RuntimeError("No model loaded")

        result = self._llm.create_completion(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=1.0,
            logprobs=topk,
            stream=False,
        )
        choice = result["choices"][0]
        text = choice.get("text", "")
        tokens = list(self._llm.tokenize(text.encode("utf-8"))) if text else []

        topk_ids: list[list[int]] = []
        topk_probs: list[list[float]] = []
        lp = (choice.get("logprobs") or {}).get("top_logprobs") or []
        for step in lp:
            ids: list[int] = []
            probs: list[float] = []
            for tok_str, logp in list(step.items())[:topk]:
                tid = self._llm.tokenize(tok_str.encode("utf-8"))
                ids.append(int(tid[0]) if tid else -1)
                probs.append(float(logp))
            topk_ids.append(ids)
            topk_probs.append(probs)

        return GenerationRecord(
            tokens=tokens,
            topk_token_ids=topk_ids,
            topk_probs=topk_probs,
        )
