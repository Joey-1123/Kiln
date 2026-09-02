"""MoE forward block — routes expert matmuls through the expert bank (plan B6).

This is the *forward* half of B6. B6-1/2 built the weight path
(:class:`~kiln.engine.safetensors_store.SafetensorsExpertStore` for discovery,
:class:`~kiln.engine.expert_mover.TorchExpertMover` for physical
cpu<->gpu<->disk movement). What was deferred is the *decode forward*: taking a
routing decision and actually computing the per-expert projections from the
resident weight tensors.

:class:`MoeForward` closes that gap. Given hidden states and a top-k routing
selection, it guarantees the chosen experts are resident in the bank (decode
phase), pulls their projection weights from the mover's live registry, and
performs the standard up/gate/down MoE matmuls aggregated by routing score.

Weight layout
-------------
Projection weights follow the ``nn.Linear`` convention ``(out_features,
in_features)``:
* ``up_proj`` / ``gate_proj``: ``(expert_dim, d_model)`` so ``x @ up.T`` maps
  hidden ``d_model`` -> expert space.
* ``down_proj``: ``(d_model, expert_dim)`` so ``inner @ down.T`` maps expert
  space back to hidden.

Matricial routing for one token x (d_model,) and routed set {(e_i, s_i)}:
``out = sum_i s_i * ( (x @ up_i.T) * (x @ gate_i.T) ) @ down_i.T ``

Design goals
------------
* **Deterministic and CPU-testable.** The matmul / add / transpose ops sit
  behind injectable seams so the whole block runs with plain torch on CPU or
  with mock tensors, without a GPU.
* **Parity-ready.** The eviction policy (all-resident vs a ``gpu_capacity_bytes``
  small enough to force evict-reload) must produce identical routed output, so
  the B6 parity gate can assert real equivalence instead of a vacuous one.
* **Lazy heavy imports.** torch is imported inside the compute paths only; the
  module imports cleanly in the torch-free control plane.

Projection weights are keyed in the mover registry by their safetensors name
(``layers.<L>.experts.<E>.up_proj.weight`` etc.), exactly as produced by
:meth:`SafetensorsExpertStore.expert_blobs`. The block resolves the projection
matrix for a given expert and projection type by rebuilding that key from the
path-style ``expert_id``, falling back to an identity projection when the
hidden size is supplied and a tensor is absent (unit-test path without a full
sharded model).
"""

from __future__ import annotations

from typing import Any, Callable

from kiln.engine.expert_bank import ExpertBank

# Projections a MoE expert owns; up/gate have shape (expert_dim, d_model),
# down has shape (d_model, expert_dim).
_UP = "up_proj"
_GATE = "gate_proj"
_DOWN = "down_proj"
_OUT_IN = ("up_proj", "gate_proj")  # (expert_dim, d_model): applied via x @ W.T
_OUT_IN_T = "down_proj"             # (d_model, expert_dim): applied via inner @ W.T


def _projection_key(expert_id: str, proj: str) -> str:
    """Rebuild an expert's safetensors key for a projection (best effort).

    ``expert_id`` is ``l<L>.e<E>``; a projected tensor key is
    ``layers.<L>.experts.<E>.<proj>.weight``.
    """
    layer, _, expert = expert_id.lstrip("l").partition(".")
    expert = expert.lstrip("e")
    return f"layers.{layer}.experts.{expert}.{proj}.weight"


class MoeForward:
    """Compute a routed MoE layer's expert projections from the bank.

    Parameters
    ----------
    bank:
        A decode-phase :class:`ExpertBank` whose resident tensors are held by a
        mover. The block calls ``ensure_resident`` for each routed expert, so
        under a GPU budget the bank (and its mover) will load/evict as needed.
    mover:
        The mover that physically holds the resident tensors. May be ``None``
        when the caller supplies tensors directly or uses synthetic (identity)
        projections.
    hidden_size:
        Input feature width (d_model). Used to build the identity projection
        when a weight tensor is not present in the mover (unit-test path).
    """

    def __init__(
        self,
        bank: ExpertBank,
        mover: Any = None,
        hidden_size: int = 0,
    ) -> None:
        self._bank = bank
        self._mover = mover
        self._hidden = hidden_size

    # -- tensor supply ------------------------------------------------------
    def _resident_tensors(self, expert_id: str) -> dict[str, Any]:
        """Return the mover's live tensors for ``expert_id`` (empty if none)."""
        if self._mover is None:
            return {}
        try:
            return dict(self._mover._resident_tensors.get(expert_id, {}))
        except AttributeError:
            return {}

    @staticmethod
    def _coerce(w: Any, library: str, ref: Any) -> Any:
        """Normalize a weight tensor ``w`` into the library/device of ``ref``."""
        from_lib = _library_kind(w)
        if from_lib == library:
            return w
        if library == "torch":
            import torch

            # ``ref`` is a torch tensor whenever library is "torch".
            return torch.as_tensor(w, device=ref.device)
        import numpy as np

        return w.detach().cpu().numpy() if _is_torch_tensor(w) else np.asarray(w)

    # -- forward ------------------------------------------------------------
    def routed(self, x: Any, expert_ids: list[str], scores: list[float]) -> Any:
        """Compute a routed MoE layer output for one ``x``.

        Parameters
        ----------
        x:
            Hidden states, shape ``(d_model,)`` or ``(seq, d_model)``.
        expert_ids:
            Top-k expert ids actually routed to for this token (decode phase).
        scores:
            Routing scores (e.g. softmaxed gate logits) of matching length.

        Returns
        -------
        ``sum_i s_i * ( (x @ up_i.T) * (x @ gate_i.T) ) @ down_i.T `` — the
        routed expert output, preserving the shape of ``x``.
        """
        matmul = _default_matmul(x)
        library = _library_kind(x)  # "torch" | "numpy" — identity synthesis must match
        self._ensure_resident(expert_ids)
        return self._route_one(x, expert_ids, scores, library, matmul)

    def routed_batch(
        self,
        x: Any,
        routes: list[tuple[list[str], list[float]]],
    ) -> Any:
        """Route every position of a ``(seq, d_model)`` buffer independently.

        A real MoE layer routes each sequence position through its own top-k
        expert set (multi-modal per-token routing). ``routes[i]`` is
        ``(expert_ids, scores)`` for position ``i``; all positions together must
        cover ``seq`` rows of ``x``. Returns a ``(seq, d_model)`` buffer with
        the per-position routed output.

        The union of all routed experts is ensured resident in one pass so a
        batch of tokens shares the resident window under the GPU budget.
        """
        seq = _n_rows(x)
        if len(routes) != seq:
            raise ValueError(
                f"expected {seq} routes (one per row) but got {len(routes)}"
            )
        matmul = _default_matmul(x)
        library = _library_kind(x)
        flat_ids: list[str] = []
        for ei, _ in routes:
            flat_ids.extend(ei)
        self._ensure_resident(flat_ids)

        outs = [
            self._route_one(_row(x, i), routes[i][0], routes[i][1], library, matmul)
            for i in range(seq)
        ]
        return _stack_rows(outs, library, ref=x)

    def _route_one(
        self,
        x: Any,
        expert_ids: list[str],
        scores: list[float],
        library: str,
        matmul: Callable,
    ) -> Any:
        """Routed expert projection for a single token ``x``."""
        result = None
        for i, eid in enumerate(expert_ids):
            score = scores[i]
            up, gate, down = self._weights_for(eid, library)
            # Ensure every weight operand lives in x's library/device so matmuls
            # never mix numpy ndarrays and torch tensors (mover can hand us
            # either depending on its device resolution).
            up, gate, down = (self._coerce(w, library, x) for w in (up, gate, down))
            # up/gate: (expert_dim, d_model) -> x @ W.T.
            x_up = matmul(x, _transpose(up))
            x_gate = matmul(x, _transpose(gate))
            inner = _multiply(x_up, x_gate)
            # down: (d_model, expert_dim) -> inner @ W.T.
            routed = matmul(inner, _transpose(down))
            term = _scale(routed, score)
            result = term if result is None else _add(result, term)
        return result if result is not None else _zero_like(x)

    def _ensure_resident(self, expert_ids: list[str]) -> None:
        """Ensure the routed experts are resident on the bank's gpu tier."""
        for eid in expert_ids:
            exp = self._bank.experts.get(eid)
            if exp is not None:
                self._bank.ensure_resident(exp)
            elif self._hidden <= 0:
                raise KeyError(
                    f"unknown expert {eid!r} and hidden_size=0 "
                    "(cannot synthesize identity projection)"
                )

    def _weights_for(self, eid: str, library: str) -> tuple[Any, Any, Any]:
        """Return ``(up, gate, down)`` weight tensors for ``eid``.

        Real weights come from the mover registry; when a projection is missing
        (no mover / synthetic topology) an identity matrix of the hidden size is
        used so the block can be exercised deterministically. The identity is
        built in the same library family as the input ``x`` so matmuls never
        mix numpy and torch operands.
        """
        resident = self._resident_tensors(eid)
        got: list[Any] = []
        for proj in (_UP, _GATE, _DOWN):
            key = _projection_key(eid, proj)
            tensor = resident.get(key)
            if tensor is not None:
                got.append(tensor)
            elif self._hidden > 0:
                got.append(_identity(self._hidden, library))
            else:
                raise KeyError(
                    f"expert {eid!r} has no {proj} tensor resident and "
                    "hidden_size=0 (cannot synthesize identity projection)"
                )
        return got[0], got[1], got[2]


# ---------------------------------------------------------------------------
# Gate: route raw logits to top-k expert ids + normalised scores
# ---------------------------------------------------------------------------


def route_experts(
    gate_logits: Any,
    expert_ids: list[str],
    top_k: int = 2,
) -> tuple[list[str], list[float]]:
    """Select top-k experts from raw gate logits and return normalised scores.

    This is the missing router primitive between the gate network's raw
    output (n_experts,) logits and :meth:`MoeForward.routed`.  It applies
    temperature-1 softmax in numpy (torch-free), selects the top-k experts,
    and renormalises scores so they sum to 1.0 across the selected set
    (standard MoE normalisation: ``score_i = softmax_i / sum(softmax)``).

    Parameters
    ----------
    gate_logits:
        Raw unnormalised logits, one per registered expert — a numpy array or
        list of length ``len(expert_ids)``.
    expert_ids:
        Ordered expert ids corresponding to the logit positions (must match
        the bank's ``experts`` keys).
    top_k:
        Number of experts to route to (default 2). Clamped to
        ``min(top_k, len(expert_ids))``.

    Returns
    -------
    ``(selected_ids, selected_scores)`` — the chosen expert ids and their
    renormalised routing scores (length ``top_k``).
    """
    import numpy as np

    logits = np.asarray(gate_logits, dtype=np.float64)
    k = min(top_k, len(expert_ids))
    if k == 0:
        return [], []
    # Numerically-stable softmax.
    logits -= logits.max()
    exp = np.exp(logits)
    probs = exp / exp.sum()
    top_idx = np.argpartition(probs, -k)[-k:]
    top_idx = top_idx[np.argsort(probs[top_idx])[::-1]]  # descending
    selected_ids = [expert_ids[i] for i in top_idx]
    selected_probs = probs[top_idx]
    # Renormalise so selected scores sum to 1.0.
    total = selected_probs.sum()
    selected_scores = (selected_probs / total).tolist()
    return selected_ids, selected_scores


# ---------------------------------------------------------------------------
# Default ops (torch or numpy, chosen from the tensor's type)
# ---------------------------------------------------------------------------


def _n_rows(x: Any) -> int:
    """Row count of a ``(seq, d_model)`` buffer (1 if a plain vector)."""
    shape = x.shape if hasattr(x, "shape") else None
    if shape is None or len(shape) == 1:
        return 1
    return int(shape[0])


def _row(x: Any, i: int) -> Any:
    """Slice row ``i`` of ``x`` (a plain vector returns itself)."""
    if hasattr(x, "shape") and len(x.shape) > 1:
        return x[i]
    if getattr(x, "ndim", 0) > 1:
        return x[i]
    return x


def _stack_rows(rows: list[Any], library: str, ref: Any) -> Any:
    """Stack per-row routed outputs back into a ``(seq, d_model)`` buffer."""
    if library == "torch":
        import torch

        return torch.stack(rows, dim=0)
    import numpy as np

    return np.stack(rows, axis=0)


def _default_matmul(x: Any) -> Callable:
    if _is_torch_tensor(x):
        import torch

        return torch.matmul
    import numpy as np

    return np.matmul


def _is_torch_tensor(v: Any) -> bool:
    return type(v).__module__ == "torch" and hasattr(v, "shape")


def _transpose(t: Any) -> Any:
    if _is_torch_tensor(t) and getattr(t, "dim", None):
        return t.T
    import numpy as np

    return np.asarray(t).T


def _multiply(a: Any, b: Any) -> Any:
    return a * b


def _add(a: Any, b: Any) -> Any:
    return a + b


def _scale(t: Any, factor: float) -> Any:
    return t * factor


def _zero_like(x: Any) -> Any:
    if _is_torch_tensor(x):
        return x * 0
    import numpy as np

    return np.zeros_like(x)


def _identity(n: int, library: str) -> Any:
    """Identity matrix ``(n, n)`` in the requested library family."""
    import numpy as np

    if library == "torch":
        import torch

        return torch.eye(n)
    return np.eye(n)


def _library_kind(x: Any) -> str:
    """Return ``"torch"`` or ``"numpy"`` describing the operand family of ``x``."""
    return "torch" if _is_torch_tensor(x) else "numpy"
