"""Tests for kiln.doctor (system health checks)."""

from __future__ import annotations

from kiln.doctor import (
    CheckResult,
    DoctorReport,
    _check_deps,
    _check_platform,
    _check_python,
    run_doctor,
)


class TestCheckResult:
    def test_dataclass(self):
        c = CheckResult(id="test", status="pass", summary="ok")
        assert c.id == "test"
        assert c.status == "pass"


class TestDoctorReport:
    def test_to_dict(self):
        report = DoctorReport(
            schema_version=1,
            status="pass",
            checks=[CheckResult(id="python", status="pass", summary="3.12.0")],
        )
        d = report.to_dict()
        assert d["schema_version"] == 1
        assert d["status"] == "pass"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["id"] == "python"

    def test_empty_report(self):
        report = DoctorReport()
        d = report.to_dict()
        assert d["schema_version"] == 1
        assert d["status"] == "pass"
        assert d["checks"] == []


class TestCheckPython:
    def test_pass(self):
        result = _check_python()
        assert result.status == "pass"
        assert result.id == "python"
        assert "3." in result.summary


class TestCheckPlatform:
    def test_pass(self):
        result = _check_platform()
        assert result.status == "pass"
        assert result.id == "platform"


class TestCheckDeps:
    def test_returns_list(self):
        results = _check_deps()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_pydantic_required(self):
        results = _check_deps()
        pydantic = [r for r in results if r.id == "dep:pydantic"]
        assert len(pydantic) == 1
        assert pydantic[0].status == "pass"


class TestRunDoctor:
    def test_quick_mode(self):
        report = run_doctor(deep=False)
        assert report.schema_version == 1
        assert report.status in ("pass", "warn", "fail")
        assert len(report.checks) > 0

        check_ids = [c.id for c in report.checks]
        assert "python" in check_ids
        assert "platform" in check_ids

    def test_deep_mode(self):
        report = run_doctor(deep=True)
        check_ids = [c.id for c in report.checks]
        assert "llama_cpp" in check_ids

    def test_status_is_consistent(self):
        report = run_doctor()
        statuses = [c.status for c in report.checks]
        if "fail" in statuses:
            assert report.status == "fail"
        elif "warn" in statuses:
            assert report.status == "warn"
        else:
            assert report.status == "pass"
