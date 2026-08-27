V2 — elastic VRAM rebalance (`LFRUTier.rebalance`). Evicts coldest entries down to a
target residency fraction so the scheduler can free headroom before a new allocation
instead of OOM-ing. Unit-tested.
