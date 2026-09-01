"""V2 ZMQ transport (plan A1) — a `Transport` over ZeroMQ PAIR sockets.

The gateway and engine talk through the :class:`~kiln.engine.messages.Transport`
Protocol. V1 uses :class:`~kiln.engine.messages.QueueTransport` (in-process
asyncio.Queue). This module adds a ZeroMQ-backed transport so the two halves
can live in separate processes with real GIL/crash isolation — the deferred
third process of the plan's topology, delivered now behind the same seam.

Messages are serialised with the numpy/torch-free codec in
``kiln.engine.messages`` (JSON over the wire), so the on-wire format stays
identical regardless of transport. pyzmq is imported lazily so the torch-free
control plane never pays for it until a ZMQ transport is actually built.
"""

from __future__ import annotations

from typing import Any

from kiln.engine.messages import EngineMessage, deserialize, serialize

_DEFAULT_HOST = "127.0.0.1"


class ZmqTransport:
    """A :class:`Transport` backed by a single ZeroMQ ``PAIR`` socket.

    A PAIR socket is bidirectional, so one ``ZmqTransport`` can both ``put``
    and ``get``. Two such links form the full gateway↔engine connection: one
    for gateway→engine traffic, one for engine→gateway traffic.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        bind: bool = False,
        ctx: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._bind = bind
        self._ctx = ctx
        self._owns_ctx = ctx is None
        self._socket: Any | None = None
        self._zmq: Any | None = None

    def _ensure(self) -> None:
        if self._socket is not None:
            return
        import zmq  # lazy: keep the torch-free zone import-free
        import zmq.asyncio

        self._zmq = zmq
        ctx = self._ctx or zmq.asyncio.Context()
        self._ctx = ctx
        sock = ctx.socket(zmq.PAIR)
        # PAIR has exactly one peer; linger 0 so aclose/term never blocks.
        sock.setsockopt(zmq.LINGER, 0)
        if self._bind:
            sock.bind(self._endpoint)
        else:
            sock.connect(self._endpoint)
        self._socket = sock

    async def put(self, msg: EngineMessage) -> None:
        """Serialise and send a message over the socket."""
        self._ensure()
        await self._socket.send_json(serialize(msg))  # type: ignore[union-attr]

    async def get(self) -> EngineMessage:
        """Receive and deserialise the next message (blocks)."""
        self._ensure()
        data = await self._socket.recv_json()  # type: ignore[union-attr]
        return deserialize(data)

    async def aclose(self) -> None:
        """Close the socket; terminate an owned context."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._owns_ctx and self._ctx is not None:
            self._ctx.term()
            self._ctx = None

    async def __aenter__(self) -> "ZmqTransport":
        self._ensure()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


class ZmqLink:
    """A pair of ``ZmqTransport`` links forming the gateway↔engine channel.

    The gateway binds both endpoints and the engine connects to them, so the
    same object works inside one process (two asyncio tasks) or across two
    processes (gateway binds, engine subprocess connects).

    Usage (gateway side)::

        link = ZmqLink()
        app = create_gateway(transport=link.gateway_to_engine,
                             response_transport=link.gateway_from_engine)
        engine = Engine(gateway_transport=link.engine_from_gateway,
                        engine_transport=link.engine_to_gateway)

    Usage (engine subprocess side) — connect to the gateway's endpoints::

        link = ZmqLink.connect_to(gateway_host, port_a, port_b)
        engine = Engine(gateway_transport=link.engine_from_gateway,
                        engine_transport=link.engine_to_gateway)
    """

    def __init__(
        self,
        host: str = _DEFAULT_HOST,
        port_a: int = 5600,
        port_b: int = 5601,
        ctx: Any | None = None,
    ) -> None:
        a = f"tcp://{host}:{port_a}"
        b = f"tcp://{host}:{port_b}"
        self._ctx = ctx or _new_ctx()
        self.gateway_to_engine: ZmqTransport = ZmqTransport(a, bind=True, ctx=self._ctx)
        self.engine_from_gateway: ZmqTransport = ZmqTransport(a, bind=False, ctx=self._ctx)
        self.gateway_from_engine: ZmqTransport = ZmqTransport(b, bind=True, ctx=self._ctx)
        self.engine_to_gateway: ZmqTransport = ZmqTransport(b, bind=False, ctx=self._ctx)

    @classmethod
    def connect_to(
        cls, host: str, port_a: int = 5600, port_b: int = 5601
    ) -> "ZmqLink":
        """Build a link for the engine side: connect (not bind) to gateway."""
        link = cls.__new__(cls)
        a = f"tcp://{host}:{port_a}"
        b = f"tcp://{host}:{port_b}"
        link._ctx = _new_ctx()
        link.gateway_to_engine = ZmqTransport(a, bind=False, ctx=link._ctx)
        link.engine_from_gateway = ZmqTransport(a, bind=False, ctx=link._ctx)
        link.engine_to_gateway = ZmqTransport(b, bind=False, ctx=link._ctx)
        link.gateway_from_engine = ZmqTransport(b, bind=False, ctx=link._ctx)
        return link

    def endpoints(self) -> tuple[str, str]:
        """Return the (gateway→engine, engine→gateway) endpoints."""
        return (
            f"tcp://{_DEFAULT_HOST}:{self._port_a()}",
            f"tcp://{_DEFAULT_HOST}:{self._port_b()}",
        )

    def _port_a(self) -> int:
        return int(self.gateway_to_engine._endpoint.rsplit(":", 1)[1])  # noqa: SLF001

    def _port_b(self) -> int:
        return int(self.engine_to_gateway._endpoint.rsplit(":", 1)[1])  # noqa: SLF001

    async def aclose(self) -> None:
        for t in (
            self.gateway_to_engine,
            self.engine_from_gateway,
            self.engine_to_gateway,
            self.gateway_from_engine,
        ):
            await t.aclose()


def _new_ctx() -> Any:
    import zmq.asyncio

    return zmq.asyncio.Context()
