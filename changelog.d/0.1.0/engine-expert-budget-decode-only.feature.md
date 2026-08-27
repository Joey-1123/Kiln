V2 (A8) — decode-only expert-budget guard (`src/kiln/engine/expert_budget.py`).
Mirrors the quarantined expert-budget rule (prefill corruption):
expert-budget trimming is permitted only in the decode phase; trimming
during prefill/idle raises `DecodeOnlyError`. Locks the V2 note that any
expert-trimming lever must be decode-only from day one.
