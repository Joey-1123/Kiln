"""Hermetic grammar-constraint layer for constrained decoding (J).

This module is deliberately **torch- and xgrammar-free at import time** so
the light control plane (and ``test_cli_startup_is_light.py``) stays green.
It owns two responsibilities:

* **Grammar detection** — ``detect_kind`` classifies a user-supplied grammar
  string into ``json_schema`` | ``regex`` | ``ebnf`` using pure-Python rules
  that are fully unit-testable on any box.
* **Constraint orchestration** — ``GrammarConstraint`` lazily builds the real
  xgrammar stack (TokenizerInfo → GrammarCompiler → GrammarMatcher) only when
  a backend actually needs to constrain decoding. If xgrammar is unavailable
  the constructor raises :class:`GrammarUnavailableError` — the fail-closed
  guarantee: a requested grammar is **never** silently ignored.

Actual token-mask application happens in the CUDA backend's decode loop; this
module only supplies the matcher primitives (``accept`` / ``is_terminated`` /
``reset``) it needs.
"""

from __future__ import annotations

import re
from typing import Any

GrammarKind = str  # "json_schema" | "regex" | "ebnf"


class GrammarUnavailableError(RuntimeError):
    """Raised when a grammar is requested but xgrammar is not installed.

    This is the fail-closed path: the engine/backend must surface it as an
    error rather than falling back to unconstrained decoding.
    """


# Detection rules (documented; see detect_kind):
#   - a leading '{' or '['  -> JSON Schema
#   - a leading '^' or '('   -> regex
#   - a '<name> ::= ...' rule -> EBNF
# Leading whitespace is ignored. A non-empty string matching none of these
# is *unknown* and must be rejected (fail closed), never guessed.
_JSON_PREFIXES: tuple[str, ...] = ("{", "[")
_REGEX_PREFIXES: tuple[str, ...] = ("^", "(")
_EBNF_RULE: re.Pattern[str] = re.compile(r"<[^<>]+>\s*::=\s*\S")


def detect_kind(grammar: str) -> GrammarKind | None:
    """Classify a grammar string, or return ``None`` if unknown/empty.

    Returns one of ``"json_schema"``, ``"regex"``, ``"ebnf"``, or ``None``.

    The caller (engine/backend) is responsible for *failing closed* on a
    non-empty string that returns ``None`` — i.e. raising rather than
    guessing — because an unrecognised grammar cannot be constrained.
    """
    s = grammar.lstrip()
    if not s:
        return None
    if s.startswith(_JSON_PREFIXES):
        return "json_schema"
    if _EBNF_RULE.search(grammar) is not None:
        return "ebnf"
    if s.startswith(_REGEX_PREFIXES):
        return "regex"
    return None


class GrammarConstraint:
    """A lazily-built xgrammar constraint for one generation.

    ``compile`` performs the heavy construction (importing ``xgrammar`` and
    building the matcher against a HuggingFace tokenizer) and may be invoked
    at most once.  Until then the object carries only the grammar string and
    its detected kind, so constructing it is cheap and torch-free.
    """

    def __init__(self, grammar: str) -> None:
        self._grammar = grammar
        self._kind: GrammarKind | None = detect_kind(grammar)
        self._matcher: Any = None
        self._bitmask: Any = None
        self._compiler: Any = None

    @property
    def grammar(self) -> str:
        return self._grammar

    @property
    def kind(self) -> GrammarKind | None:
        return self._kind

    @property
    def is_compiled(self) -> bool:
        return self._matcher is not None

    def compile(self, tokenizer: Any, vocab_size: int | None = None) -> None:
        """Build the xgrammar matcher for ``tokenizer``. Fail-closed.

        Raises :class:`GrammarUnavailableError` if xgrammar is not installed,
        and a ``ValueError`` if the grammar string cannot be classified
        (ambiguous/unknown non-empty string). Idempotent once compiled.
        """
        if self._matcher is not None:
            return
        if self._kind is None:
            raise ValueError(
                "Cannot compile grammar: unrecognised or empty grammar string "
                f"{self._grammar!r}"
            )

        try:
            import xgrammar as xgr
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise GrammarUnavailableError(
                "Constrained decoding requested (grammar supported at runtime) but "
                'xgrammar is not installed. Install with: pip install "kiln-cli[grammar]"'
            ) from exc

        kwargs: dict[str, Any] = {}
        if vocab_size is not None:
            kwargs["vocab_size"] = vocab_size
        tokenizer_info = xgr.TokenizerInfo.from_huggingface(tokenizer, **kwargs)
        compiler = xgr.GrammarCompiler(tokenizer_info)

        if self._kind == "json_schema":
            compiled = compiler.compile_json_schema(self._grammar)
        elif self._kind == "regex":
            compiled = compiler.compile_regex(self._grammar)
        else:
            compiled = compiler.compile_grammar(self._grammar)

        self._compiler = compiler
        self._matcher = xgr.GrammarMatcher(compiled)
        self._bitmask = xgr.allocate_token_bitmask(
            1, tokenizer_info.vocab_size
        )

    def fill_next_token_bitmask(self) -> Any:
        """Fill and return the next-token bitmask for the current state."""
        if self._matcher is None:
            raise RuntimeError("GrammarConstraint not compiled")
        self._matcher.fill_next_token_bitmask(self._bitmask)
        return self._bitmask

    def accept_token(self, token_id: int) -> None:
        """Advance the matcher with the sampled token."""
        if self._matcher is None:
            raise RuntimeError("GrammarConstraint not compiled")
        self._matcher.accept_token(token_id)

    def is_terminated(self) -> bool:
        """Whether the matcher has matched the whole grammar (generation done)."""
        if self._matcher is None:
            raise RuntimeError("GrammarConstraint not compiled")
        return self._matcher.is_terminated()

    def reset(self) -> None:
        """Reset the matcher to its initial state (for reuse)."""
        if self._matcher is not None:
            self._matcher.reset()
