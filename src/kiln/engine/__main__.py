"""Engine subprocess entry point — `python -m kiln.engine`."""

from __future__ import annotations

import argparse
import asyncio
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kiln engine subprocess")
    p.add_argument("--host", default="127.0.0.1", help="Gateway host to connect to")
    p.add_argument("--port-a", type=int, default=5600, help="Gateway→engine port")
    p.add_argument("--port-b", type=int, default=5601, help="Engine→gateway port")
    return p.parse_args(argv)


async def _run(host: str, port_a: int, port_b: int) -> None:
    from kiln.engine.backends.cuda_native import register as register_cuda
    from kiln.engine.backends.llama_cpp import register as register_cpu
    from kiln.engine.engine import Engine
    from kiln.engine.transport_zmq import ZmqLink

    register_cuda()
    register_cpu()
    link = ZmqLink.connect_to(host, port_a=port_a, port_b=port_b)
    engine = Engine(
        gateway_transport=link.engine_from_gateway,
        engine_transport=link.engine_to_gateway,
    )
    sys.stdout.buffer.write(b"READY\n")
    sys.stdout.buffer.flush()

    async def _drain_stdin() -> None:
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        try:
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except Exception:
            return
        while True:
            chunk = await reader.read(1024)
            if not chunk:
                break

    drain_task = asyncio.create_task(_drain_stdin())
    try:
        await engine.run()
    finally:
        drain_task.cancel()
        try:
            await drain_task
        except asyncio.CancelledError:
            pass
        engine.stop()
        await link.aclose()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(_run(args.host, args.port_a, args.port_b))


if __name__ == "__main__":
    main()
