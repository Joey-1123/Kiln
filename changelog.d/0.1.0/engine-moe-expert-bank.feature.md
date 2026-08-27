V2 (A9) — MoE expert offload / hybrid CPU↔GPU banks (`src/kiln/engine/expert_bank.py`).
`ExpertBank` manages expert weight residency under a GPU budget with three
strategies (offload / hybrid / cpu). The GPU-resident set is tracked by the LFRU
tier (plan A5) so eviction honours the same cold-LFU / hot-LRU policy, and the
decode-only expert-budget guard (plan A8) blocks trimming outside the decode
phase. Weight movement is delegated to an injectable mover callback so the
placement policy is fully testable without a GPU.
