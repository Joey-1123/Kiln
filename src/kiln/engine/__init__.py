"""Engine package — Gateway+Engine fused in ONE process (A1).

Two async halves communicate over typed-dataclass messages on an
asyncio.Queue behind a transport seam.  Message codec is numpy-only /
torch-free (A2).
"""

from __future__ import annotations
