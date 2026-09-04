"""Hermetic grammar-constraint tests (J) — run on any box, no torch/xgrammar.

These prove detection, validation, fail-closed behavior, and masking-loop
*orchestration*. Actual CUDA token-mask application is covered separately by
``tests/test_grammar_gpu.py`` (@pytest.mark.gpu) — the orchestration test here
explicitly does NOT claim real masking works.

The fail-closed path (grammar requested but xgrammar unavailable) is exercised
in a fresh subprocess with a meta-path finder that blocks ``xgrammar`` import —
the same sentinel technique used by ``test_supervisor_import_safety.py`` — so
it reflects the real import machinery rather than an in-process patch.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from kiln.engine.grammar_constraint import (
    GrammarConstraint,
    detect_kind,
)

_IMPORT_FROM = "src"


def _blocking_subprocess(body: str) -> str:
    script = (
        "import sys\n"
        "class _Blocker:\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname.split('.')[0] == 'xgrammar':\n"
        "            raise ImportError('xgrammar is blocked for this test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        + body
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": _IMPORT_FROM},
        timeout=60,
    )
    return result.stdout, result.stderr, result.returncode


class TestDetectKind:
    def test_detects_json_schema_object(self):
        assert detect_kind('{"type": "object"}') == "json_schema"

    def test_detects_json_schema_array(self):
        assert detect_kind("[1, 2, 3]") == "json_schema"

    def test_detects_json_schema_ignores_leading_whitespace(self):
        assert detect_kind('   {"type": "object"}') == "json_schema"

    def test_detects_regex_caret(self):
        assert detect_kind("^[a-z]+$") == "regex"

    def test_detects_regex_parenthesis(self):
        assert detect_kind(r"(foo|bar)+") == "regex"

    def test_detects_ebnf_rule(self):
        assert detect_kind("<S> ::= 'a' | 'b'") == "ebnf"

    def test_unknown_non_empty_returns_none(self):
        assert detect_kind("this is not a grammar") is None

    def test_empty_returns_none(self):
        assert detect_kind("") is None

    def test_whitespace_only_returns_none(self):
        assert detect_kind("   ") is None

    def test_ebnf_precedence_over_regex_prefix(self):
        # A '<name> ::=' rule wins even if the string also starts with '('.
        assert detect_kind("(<S> ::= 'a')") == "ebnf"


class TestGrammarConstraintCompile:
    def test_kind_and_grammar_exposed_without_import(self):
        c = GrammarConstraint("^[0-9]+$")
        assert c.kind == "regex"
        assert c.grammar == "^[0-9]+$"
        assert not c.is_compiled

    def test_fill_bitmask_before_compile_raises(self):
        c = GrammarConstraint("^[0-9]+$")
        with pytest.raises(RuntimeError):
            c.fill_next_token_bitmask()

    def test_compile_raises_unknown_grammar(self):
        c = GrammarConstraint("not a grammar at all")
        with pytest.raises(ValueError):
            c.compile(tokenizer=object())

    def test_compile_fails_closed_when_xgrammar_blocked(self):
        """Fail-closed: non-empty grammar + xgrammar unavailable -> error.

        Runs in a subprocess with a meta-path finder that raises on any
        ``xgrammar`` import, exactly like the torch-free-zone sentinel.
        """
        body = (
            "from kiln.engine.grammar_constraint import GrammarConstraint, "
            "GrammarUnavailableError\n"
            "c = GrammarConstraint('^[0-9]+$')\n"
            "try:\n"
            "    c.compile(tokenizer=object(), vocab_size=32000)\n"
            "except GrammarUnavailableError:\n"
            "    print('FAIL_CLOSED_OK')\n"
            "else:\n"
            "    raise SystemExit('did not fail closed')\n"
        )
        out, err, code = _blocking_subprocess(body)
        assert code == 0, err
        assert "FAIL_CLOSED_OK" in out


class _StubMatcher:
    """Minimal double matching the GrammarConstraint surface used in a loop."""

    def __init__(self):
        self.accepted: list[int] = []
        self.terminated = False

    def fill_next_token_bitmask(self, bitmask):
        bitmask["filled"] = True

    def accept_token(self, token_id):
        self.accepted.append(token_id)
        if len(self.accepted) >= 3:
            self.terminated = True

    def is_terminated(self):
        return self.terminated

    def reset(self):
        self.accepted = []
        self.terminated = False


class _StubConstraint(GrammarConstraint):
    """GrammarConstraint whose compile() installs a stub matcher (no xgrammar)."""

    def compile(self, tokenizer=None, vocab_size=None):
        self._matcher = _StubMatcher()
        self._bitmask = {"filled": False}


class TestMaskingLoopOrchestration:
    def test_mask_accept_terminate_cycle_in_order(self):
        """ORCHESTRATION ONLY — the mask→accept→terminate cycle runs in order.

        Intentionally uses a stub matcher, NOT xgrammar. Real masking is covered
        by test_grammar_gpu (CUDA). Constructing the constraint never imports
        xgrammar.
        """
        c = _StubConstraint("^[a-z]+$")
        c.compile()

        sampled = [7, 42, 99]
        accept_count = 0
        for tid in sampled:
            bitmask = c.fill_next_token_bitmask()
            assert bitmask["filled"]  # mask produced before sampling
            c.accept_token(tid)  # accepted after sampling
            accept_count += 1
            if c.is_terminated():
                break

        assert c._matcher.accepted == sampled
        assert accept_count == 3
        assert c.is_terminated()

    def test_reset_clears_termination_for_reuse(self):
        c = _StubConstraint("^[a-z]+$")
        c.compile()
        c.accept_token(1)
        c.accept_token(2)
        c.accept_token(3)
        assert c.is_terminated()

        c.reset()
        assert c.is_terminated() is False
        assert c._matcher.accepted == []


class _StubCudaModel:
    """Minimal fake of the CUDA backend's loaded model + tokenizer."""

    class _Config:
        vocab_size = 128

    config = _Config()
    device = "cpu"

    def __init__(self):
        self.logits = None

    def __call__(self, **kwargs):
        return type("Out", (), {"logits": self.logits})()


class _StubTokenizer:
    vocab_size = 128

    def __call__(self, prompt, return_tensors="pt"):
        import torch

        class _Batch:
            def __init__(self):
                self.input_ids = torch.zeros(1, 4, dtype=torch.long)

            def __getitem__(self, key):
                return getattr(self, key)

            def to(self, device):
                return self

        return _Batch()

    def decode(self, ids, skip_special_tokens=True):
        if isinstance(ids, int):
            return f"<{ids}>"
        return "".join(f"<{t}>" for t in ids)


class TestCudaStreamingGrammarOrchestration:
    """ORCHESTRATION ONLY — CUDA streaming wiring, no real masking.

    Verifies generate_stream calls the constraint's mask→accept→terminate cycle
    and applies the bitmask to logits pre-softmax, using a stub constraint and
    a stub torch model. Never imports xgrammar at module scope.
    """

    def test_streaming_masks_accepts_and_terminates(self, monkeypatch):
        import torch

        from kiln.engine.backends.cuda_native import CUDABackend
        from kiln.engine.grammar_constraint import GrammarConstraint

        # Stub xgrammar so the in-loop import resolves, and record mask applies.
        applied = []

        class _FakeXgrammar:
            @staticmethod
            def apply_token_bitmask_inplace(logits, bitmask):
                applied.append(logits.shape[0])

        import sys

        fake = _FakeXgrammar()
        sys.modules["xgrammar"] = fake

        backend = CUDABackend()
        model = _StubCudaModel()
        model.logits = type("L", (), {})()
        model.logits = torch.randn(1, 1, 128)
        backend._model = model
        backend._tokenizer = _StubTokenizer()
        real_call = model.__call__

        def call(**kwargs):
            out = real_call(**kwargs)
            out.logits = model.logits
            return out

        model.__call__ = call

        # Inject a stub constraint (GrammarConstraint subclass, no real compile).
        class _LocalStub(GrammarConstraint):
            def __init__(self, grammar):
                super().__init__(grammar)
                self._matcher = _StubMatcher()
                self._is_compiled = True

            @property
            def is_compiled(self):
                return True

            def fill_next_token_bitmask(self):
                return torch.zeros(1, 8, dtype=torch.bool)

        stub = _LocalStub("^[a-z]+$")
        backend._grammar_constraint = lambda g: stub

        gen = backend.generate_stream(
            "hi", max_tokens=10, temperature=0.0, grammar="^[a-z]+$"
        )
        tokens = list(gen)

        assert applied  # bitmask applied at least once
        assert stub._matcher.accepted  # tokens accepted
        # stub terminates after 3 accepts
        assert len(tokens) <= 3
        # last emitted finish_reason is stop
        assert tokens[-1][1] == "stop"
        del sys.modules["xgrammar"]
