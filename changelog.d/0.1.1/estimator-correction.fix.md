V2-5.x — QLoRA VRAM estimator correction (`src/kiln/utils/budget.py`). The flat
`estimate_vram_bytes()` never priced the trainable-parameter AdamW moments or a
fixed runtime/scratch workspace, so its QLoRA figures were 2–3× too optimistic
(e.g. 7B ≈ 3.9 GB vs the community 8–12 GB figure). It now models memory as
additive components — base (NF4, frozen) + trainable (LoRA fp16) + optimizer
(AdamW fp32 m+v, trainable params only) + activation + runtime — exposed via an
auditable `_vram_budget()` breakdown with named constants. The streaming path
(`estimate_streaming_vram_bytes`) now divides only the layer-divisible base term
across layers while preserving the active/fixed training-state and runtime costs.
The `plan:` config block adds configurable feasibility thresholds
(`recommended_fraction`, `possible_fraction`, `minimum_vram_bytes`), and
`kiln.plan.classify_fit()` classifies a run as Recommended / Possible
(constrained settings) / Likely OOM / Unsupported; `PlanResult` carries the
verdict and `format_plan` renders it. Both public estimator signatures are
unchanged; verdict policy is excluded from the recipe `config_sha`.