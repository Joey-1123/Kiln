V2 — adapter registry with lineage (`src/kiln/trainer/registry.py`). Records each
adapter's base model and parent so a lineage chain can be reconstructed. Guards
against missing parents and cycles. Foundation for the recipe/adapter catalog.
