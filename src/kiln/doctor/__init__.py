"""Doctor — system health checks.

Quick mode (default): dependency + GPU + RAM checks (Soup-style).
Deep mode (--deep): full validation including engine binaries, model checks (Colibri-style).

Structured JSON output via --json.
Exit code: 0=healthy, 1=issues found.
"""

from __future__ import annotations

import importlib
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field

# Canonical dependency list: (import_name, pkg_name, min_version, required)
_DEPS = [
    ("torch", "torch", "2.0.0", False),
    ("transformers", "transformers", "5.0.0", False),
    ("peft", "peft", "0.10.0", False),
    ("trl", "trl", "0.10.0", False),
    ("datasets", "datasets", "2.14.0", False),
    ("bitsandbytes", "bitsandbytes", "0.41.0", False),
    ("accelerate", "accelerate", "0.25.0", False),
    ("fastapi", "fastapi", "0.104.0", False),
    ("uvicorn", "uvicorn", "0.24.0", False),
    ("pydantic", "pydantic", "2.0.0", True),
    ("typer", "typer", "0.9.0", True),
    ("rich", "rich", "13.0.0", True),
    ("yaml", "pyyaml", "6.0", False),
]


@dataclass
class CheckResult:
    """Result of a single doctor check (id, status, summary)."""
    id: str
    status: str  # pass | fail | warn | skip
    summary: str


@dataclass
class DoctorReport:
    """Aggregated system-health report (status + checks)."""
    schema_version: int = 1
    status: str = "pass"
    checks: list[CheckResult] = field(default_factory=list)
    plan: dict | None = None

    def to_dict(self) -> dict:
        """Serialize this report to a plain dict."""
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "checks": [
                {"id": c.id, "status": c.status, "summary": c.summary}
                for c in self.checks
            ],
            "plan": self.plan,
        }


def _version_ok(installed: str, minimum: str) -> bool:
    def _parse(v: str) -> tuple[int, ...]:
        parts = v.split("+")[0].split(".")
        return tuple(int(p) for p in parts[:3])
    try:
        return _parse(installed) >= _parse(minimum)
    except (ValueError, TypeError):
        return False


def _check_python() -> CheckResult:
    v = sys.version.split()[0]
    if sys.version_info >= (3, 10) and sys.version_info < (3, 14):
        return CheckResult(id="python", status="pass", summary=f"{v}")
    return CheckResult(
        id="python", status="fail",
        summary=f"{v} (need >=3.10,<3.14)",
    )


def _check_platform() -> CheckResult:
    p = platform.system()
    return CheckResult(id="platform", status="pass", summary=f"{p} {platform.machine()}")


def _check_gpu() -> CheckResult:
    gpu_info = _detect_gpu()
    if gpu_info:
        return CheckResult(id="gpu", status="pass", summary=gpu_info)
    return CheckResult(
        id="gpu", status="warn",
        summary="No GPU detected (CPU-only serving available)",
    )


def _detect_gpu() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if lines:
                gpu_name = lines[0].strip()
                mem = gpu_name.split(",")[-1].strip()
                return f"NVIDIA: {gpu_name} ({mem} MiB)"
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _check_memory() -> CheckResult:
    try:
        import psutil
        total = psutil.virtual_memory().total / (1024 ** 3)
        return CheckResult(
            id="memory", status="pass",
            summary=f"{total:.1f} GB",
        )
    except ImportError:
        return CheckResult(id="memory", status="skip", summary="psutil not installed")


def _check_disk() -> CheckResult:
    try:
        usage = os.statvfs("/")
        free = (usage.f_bavail * usage.f_frsize) / (1024 ** 3)
        return CheckResult(
            id="disk", status="pass" if free > 5 else "warn",
            summary=f"{free:.1f} GB free",
        )
    except OSError:
        return CheckResult(id="disk", status="skip", summary="unable to check")


def _check_deps() -> list[CheckResult]:
    results = []
    for import_name, pkg_name, min_ver, required in _DEPS:
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", "?")
            if _version_ok(str(ver), min_ver):
                results.append(CheckResult(
                    id=f"dep:{pkg_name}", status="pass",
                    summary=f"{ver} (>= {min_ver})",
                ))
            else:
                status = "fail" if required else "warn"
                results.append(CheckResult(
                    id=f"dep:{pkg_name}", status=status,
                    summary=f"{ver} (need >= {min_ver})",
                ))
        except ImportError:
            status = "fail" if required else "skip"
            results.append(CheckResult(
                id=f"dep:{pkg_name}", status=status,
                summary=f"not installed (>= {min_ver})",
            ))
    return results


def _check_llama_cpp() -> CheckResult:
    from pathlib import Path
    base = Path.home() / ".kiln" / "llama.cpp"
    if not base.exists():
        return CheckResult(
            id="llama_cpp", status="skip",
            summary="not downloaded (will auto-download on first export)",
        )
    from kiln.export import _llama_quantize_exists
    if _llama_quantize_exists(base):
        return CheckResult(
            id="llama_cpp", status="pass",
            summary=f"{base}",
        )
    return CheckResult(
        id="llama_cpp", status="warn",
        summary=f"cloned at {base} but not built",
    )


def _check_engine_backends() -> list[CheckResult]:
    results = []
    results.append(_check_llama_cpp())

    try:
        import torch
        if torch.cuda.is_available():
            results.append(CheckResult(
                id="backend:cuda", status="pass",
                summary=f"CUDA {torch.version.cuda}",
            ))
        else:
            results.append(CheckResult(
                id="backend:cuda", status="skip",
                summary="torch installed but no CUDA device",
            ))
    except ImportError:
        results.append(CheckResult(
            id="backend:cuda", status="skip",
            summary="torch not installed",
        ))
    return results


def run_doctor(*, deep: bool = False) -> DoctorReport:
    """Run quick/Deep system health checks; return a DoctorReport."""
    report = DoctorReport()

    report.checks.append(_check_python())
    report.checks.append(_check_platform())
    report.checks.append(_check_gpu())
    report.checks.append(_check_memory())
    report.checks.append(_check_disk())
    report.checks.extend(_check_deps())

    if deep:
        report.checks.extend(_check_engine_backends())

    fails = [c for c in report.checks if c.status == "fail"]
    warns = [c for c in report.checks if c.status == "warn"]

    if fails:
        report.status = "fail"
    elif warns:
        report.status = "warn"
    else:
        report.status = "pass"

    return report
