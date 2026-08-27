A8 — CPU↔GPU parity oracle promoted to a hard release gate. The torch-free
comparison core (`src/kiln/engine/parity.py`) checks both logit-window
top-k overlap (Jaccard) and task-level equivalence (top-1 match + bounded
normalized edit distance), since native-torch float and llama.cpp/GGUF int8
are not bit-exact across engines. Fixture *generation* (`tools/gen_parity_fixture.py`,
pinned torch, CI-only) is strictly separated from torch-free *consumption*
(`tests/test_parity_oracle.py`), and the `parity-oracle` CI job regenerates
fixtures every run so the gate cannot silently rot. The live gate runs both
engines at cache capacities `{1, 2, 8}` (where eviction bugs hide) and is a
required release job (run on push / `parity`-labeled PRs / manual dispatch).
