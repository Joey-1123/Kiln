V2 (A5) — LFRU memory tier (`src/kiln/engine/cache_tier.py`), the
Least-Frequently-Recent-Used pattern: a cold (LFU) band promotes
items to a hot (LRU) band after `promotion_threshold` accesses. Dependency-
free and unit-tested; this is the primitive Kiln's future expert/weight banks
will sit behind. Predictive prefetch wiring stays deferred per the plan.
