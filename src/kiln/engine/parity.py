"""CPU↔GPU parity oracle (A8) — torch-free comparison core.

The oracle compares a *live* cross-backend generation against a
*reference* generation record produced by a pinned-torch fixture
generator (``tools/gen_parity_fixture.py``).  Cross-engine bit-exactness
is impossible (native torch float vs llama.cpp/GGUF int8), so the gate
uses two complementary checks:

* **logit-window tolerance** — top-k token-id set overlap (Jaccard) at
  each decoding step, and
* **task-level equivalence** — top-1 token match rate plus a bounded
  normalized edit distance over the decoded token sequence.

``GenerationRecord`` / ``ParityFixture`` / ``ParityReport`` are plain
(torch-free) dataclasses so the *consumption* side never imports heavy
deps — keeping the gate honest and rot-resistant (plan §8.1 / A8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParityTolerance:
    """Thresholds for a passing parity check."""

    top1_token_match_min: float = 0.99
    topk_window_k: int = 10
    topk_window_overlap_min: float = 0.8
    task_edit_distance_max: float = 0.05
    require_logit_window: bool = True


@dataclass
class GenerationRecord:
    """One decoding run: token ids plus, optionally, per-step top-k logits."""

    tokens: list[int]
    topk_token_ids: list[list[int]] = field(default_factory=list)
    topk_probs: list[list[float]] = field(default_factory=list)

    def has_logits(self) -> bool:
        return bool(self.topk_token_ids) and len(self.topk_token_ids) == len(self.tokens)


@dataclass
class ParityReport:
    backend: str
    capacity: int
    top1_match: float
    topk_overlap: float
    edit_distance: float
    passed: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class ParityFixture:
    name: str
    model: str
    prompts: list[str]
    capacities: list[int]
    temperature: float
    tolerance: ParityTolerance
    reference: dict[int, GenerationRecord]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParityFixture":
        tol_raw = data.get("tolerance") or {}
        tol_fields = {k: v for k, v in tol_raw.items() if k in ParityTolerance.__dataclass_fields__}
        tolerance = ParityTolerance(**tol_fields)

        reference: dict[int, GenerationRecord] = {}
        for cap_str, rec in (data.get("reference") or {}).items():
            reference[int(cap_str)] = GenerationRecord(
                tokens=list(rec["tokens"]),
                topk_token_ids=[list(x) for x in rec.get("topk_token_ids", [])],
                topk_probs=[list(x) for x in rec.get("topk_probs", [])],
            )

        return cls(
            name=data["name"],
            model=data["model"],
            prompts=list(data.get("prompts", [])),
            capacities=[int(c) for c in data.get("capacities", [])],
            temperature=float(data.get("temperature", 0.0)),
            tolerance=tolerance,
            reference=reference,
        )

    @classmethod
    def load(cls, path: str | Path) -> "ParityFixture":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def levenshtein_ratio(a: list[int], b: list[int]) -> float:
    """Normalized edit distance in [0,1]; 0 == identical, 1 == completely different."""
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[len(b)] / max(len(a), len(b))


def topk_overlap(ref_ids: list[int], live_ids: list[int]) -> float:
    """Jaccard overlap of two top-k token-id sets."""
    rs, ls = set(ref_ids), set(live_ids)
    union = rs | ls
    if not union:
        return 1.0
    return len(rs & ls) / len(union)


def compare_to_reference(
    reference: GenerationRecord,
    live: GenerationRecord,
    tolerance: ParityTolerance,
    *,
    backend: str,
    capacity: int,
) -> ParityReport:
    m = min(len(reference.tokens), len(live.tokens))
    top1 = sum(1 for i in range(m) if reference.tokens[i] == live.tokens[i]) / m if m else 0.0
    edit = levenshtein_ratio(reference.tokens, live.tokens)

    notes: list[str] = []
    if reference.has_logits() and live.has_logits():
        steps = min(len(reference.topk_token_ids), len(live.topk_token_ids))
        k = tolerance.topk_window_k
        overlaps = [
            topk_overlap(reference.topk_token_ids[i][:k], live.topk_token_ids[i][:k])
            for i in range(steps)
        ]
        window = sum(overlaps) / steps if steps else 1.0
    else:
        # No logits captured: when the tolerance requires the logit window the
        # parity check cannot be asserted, so it must fail rather than pass silently.
        window = 0.0
        if tolerance.require_logit_window:
            notes.append("logit window required but not captured; parity cannot be asserted")
        else:
            notes.append("logit window not captured; relying on task-level equivalence")

    passed = (
        top1 >= tolerance.top1_token_match_min
        and edit <= tolerance.task_edit_distance_max
        and (not tolerance.require_logit_window or window >= tolerance.topk_window_overlap_min)
    )
    notes.append(f"top1={top1:.3f} window={window:.3f} edit={edit:.3f}")
    return ParityReport(
        backend=backend,
        capacity=capacity,
        top1_match=top1,
        topk_overlap=window,
        edit_distance=edit,
        passed=passed,
        notes=notes,
    )


@dataclass
class ParityOracle:
    tolerance: ParityTolerance = field(default_factory=ParityTolerance)

    def evaluate(
        self,
        fixture: ParityFixture,
        results: dict[str, dict[int, GenerationRecord]],
    ) -> list[ParityReport]:
        """Evaluate every live backend result against the fixture reference.

        ``results`` maps backend name -> {capacity: GenerationRecord}.
        """
        tol = self.tolerance or fixture.tolerance
        reports: list[ParityReport] = []
        for backend, by_cap in results.items():
            for cap in fixture.capacities:
                ref = fixture.reference.get(cap)
                live = by_cap.get(cap)
                if ref is None or live is None:
                    reports.append(
                        ParityReport(
                            backend=backend,
                            capacity=cap,
                            top1_match=0.0,
                            topk_overlap=0.0,
                            edit_distance=1.0,
                            passed=False,
                            notes=[f"missing record for capacity {cap}"],
                        )
                    )
                    continue
                reports.append(
                    compare_to_reference(ref, live, tol, backend=backend, capacity=cap)
                )
        return reports

    @staticmethod
    def all_passed(reports: list[ParityReport]) -> bool:
        return all(r.passed for r in reports)
