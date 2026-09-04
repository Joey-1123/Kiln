J constrained decoding — xgrammar-backed grammar decoding, fail-closed. A
requested `grammar` on a generate call now flows gateway→engine→backend and
constrains sampling instead of being silently ignored. A new hermetic
`GrammarConstraint` layer (`engine/grammar_constraint.py`) lazily imports
xgrammar and auto-detects the grammar format from its shape — JSON Schema,
regular expression, or EBNF — via `detect_kind()`. The engine rejects any
non-empty grammar with a `grammar_unsupported` error (instead of falling back
to unconstrained output) when the active backend cannot constrain decoding. The
CUDA backend advertises `supports_grammar`, masks out-of-grammar tokens
pre-softmax per step, and accepts decoded tokens until the grammar terminates
`(Engine.stop)`. Installing the new `[grammar]` extra adds `xgrammar>=0.2.5`
(kept out of `[serve]`). Real masking is validated by a GPU-only integration
test (`-m gpu`, `tests/test_grammar_gpu.py`); CPU wiring and safety are covered
by `tests/test_grammar_constraint.py`. Grammar requests fail fast and loudly —
never an unconstrained fallback.
