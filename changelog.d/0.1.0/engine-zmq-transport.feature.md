V2 (A1) — ZeroMQ transport seam (`src/kiln/engine/transport_zmq.py`). The gateway
and engine now talk over `ZmqTransport` (PAIR sockets, JSON wire codec identical
to the in-process path) behind the same `Transport` Protocol, so the two halves
can be split into separate processes with real GIL/crash isolation. `kiln serve
--transport zmq` exercises the 3-process wire path in one process; a later
supervisor step spawns the engine as its own process against the same endpoints.
