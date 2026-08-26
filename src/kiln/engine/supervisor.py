"""Torch-free supervisor — separate process from day 1.

The supervisor monitors the engine process and can restart it on crash.
Communication is via a simple ready-ack protocol over a pipe.

Design principle: an engine segfault must not kill the supervisor.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

_READY = b"READY\n"
_ACK = b"ACK\n"


@dataclass
class SupervisorConfig:
    """Configuration for the supervisor."""

    engine_cmd: list[str]  # Command to start the engine process
    ready_timeout: float = 30.0  # Seconds to wait for READY
    ack_interval: float = 15.0  # Seconds between ack checks
    max_restarts: int = 5  # Max restarts before giving up
    restart_delay: float = 2.0  # Seconds between restart attempts


class Supervisor:
    """Torch-free supervisor that monitors the engine process.

    Runs as a separate process.  The engine process sends READY on
    startup and responds to ACK pings.
    """

    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._running = False
        self._restart_count = 0

    @property
    def is_running(self) -> bool:
        """Whether the supervisor is actively monitoring the engine."""
        return self._running

    @property
    def engine_pid(self) -> int | None:
        """PID of the managed engine process, or None."""
        return self._process.pid if self._process else None

    async def start(self) -> bool:
        """Start the engine process and wait for READY.

        Returns True if the engine is ready, False on failure.
        """
        log.info("Starting engine: %s", self.config.engine_cmd)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.config.engine_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            log.error("Failed to start engine: %s", exc)
            return False

        # Wait for READY
        try:
            assert self._process.stdin is not None
            assert self._process.stdout is not None
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self.config.ready_timeout,
            )
            if line.strip() == b"READY":
                log.info("Engine ready (pid=%d)", self._process.pid)
                return True
            log.error("Engine sent unexpected ready signal: %r", line)
            return False
        except asyncio.TimeoutError:
            log.error("Engine did not send READY within %ss", self.config.ready_timeout)
            await self._kill_process()
            return False

    async def run(self) -> None:
        """Run the supervisor loop — monitors and restarts the engine."""
        self._running = True
        log.info("Supervisor started")

        while self._running and self._restart_count < self.config.max_restarts:
            if self._process is None or self._process.returncode is not None:
                if self._restart_count > 0:
                    log.info(
                        "Restarting engine (attempt %d/%d)",
                        self._restart_count,
                        self.config.max_restarts,
                    )
                    await asyncio.sleep(self.config.restart_delay)

                if not await self.start():
                    self._restart_count += 1
                    continue

            # Monitor loop — send ack pings
            try:
                await self._monitor_loop()
            except asyncio.CancelledError:
                break

            # Process ended — check if restartable
            if self._process and self._process.returncode is not None:
                rc = self._process.returncode
                log.warning("Engine exited with code %d", rc)
                self._restart_count += 1

        if self._restart_count >= self.config.max_restarts:
            log.error("Max restarts (%d) reached", self.config.max_restarts)

        self._running = False
        log.info("Supervisor stopped")

    def stop(self) -> None:
        """Stop the supervisor and engine."""
        self._running = False
        if self._process and self._process.returncode is None:
            self._process.terminate()

    async def _monitor_loop(self) -> None:
        """Monitor the engine, sending ack pings."""
        while self._running and self._process and self._process.returncode is None:
            await asyncio.sleep(self.config.ack_interval)
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(_ACK)
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                log.warning("Engine pipe broken — engine may have crashed")
                break

    async def _kill_process(self) -> None:
        """Kill the engine process."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()


# ---------------------------------------------------------------------------
# CLI entry point for the supervisor (torch-free)
# ---------------------------------------------------------------------------


def run_supervisor(engine_cmd: list[str], **kwargs: Any) -> None:
    """Run the supervisor from the CLI.

    This function is completely torch-free — it only spawns a subprocess.
    """
    config = SupervisorConfig(engine_cmd=engine_cmd, **kwargs)
    supervisor = Supervisor(config)

    def _signal_handler(sig: int, frame: Any) -> None:
        log.info("Received signal %d, stopping", sig)
        supervisor.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    asyncio.run(supervisor.run())
