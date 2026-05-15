# SPDX-License-Identifier: Apache-2.0
"""Tests for NEST CLI commands."""

from __future__ import annotations

from pathlib import Path

from nest_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


class TestVersion:
    def test_version_output(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestDoctor:
    def test_doctor_passes(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "checks passed" in result.output
        assert "[FAIL]" not in result.output


class TestRun:
    def test_run_marketplace(self, tmp_path: Path) -> None:
        yaml_path = Path(__file__).parent.parent.parent.parent / "scenarios" / "marketplace.yaml"
        if not yaml_path.exists():
            import pytest

            pytest.skip("marketplace.yaml not found")

        trace_out = tmp_path / "trace.jsonl"
        result = runner.invoke(
            app,
            [
                "run",
                str(yaml_path),
                "--ticks",
                "2000",
                "-o",
                str(trace_out),
            ],
        )
        assert result.exit_code == 0
        assert "Running scenario" in result.output
        assert "Trace written to" in result.output
        assert trace_out.exists()

    def test_run_missing_file(self) -> None:
        result = runner.invoke(app, ["run", "nonexistent.yaml"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_run_seed_override(self, tmp_path: Path) -> None:
        yaml_path = Path(__file__).parent.parent.parent.parent / "scenarios" / "marketplace.yaml"
        if not yaml_path.exists():
            import pytest

            pytest.skip("marketplace.yaml not found")

        trace_out = tmp_path / "trace.jsonl"
        result = runner.invoke(
            app,
            [
                "run",
                str(yaml_path),
                "--seed",
                "999",
                "--ticks",
                "1000",
                "-o",
                str(trace_out),
            ],
        )
        assert result.exit_code == 0
        assert "seed: 999" in result.output


class TestInit:
    def test_init_creates_file(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "test-scenario", "-d", str(tmp_path)])
        assert result.exit_code == 0
        assert "Created scenario" in result.output

        created = tmp_path / "test-scenario.yaml"
        assert created.exists()
        content = created.read_text()
        assert "name: test-scenario" in content
        assert "transport: in_memory" in content

    def test_init_no_overwrite(self, tmp_path: Path) -> None:
        (tmp_path / "existing.yaml").write_text("name: existing\n")
        result = runner.invoke(app, ["init", "existing", "-d", str(tmp_path)])
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestInspect:
    def test_inspect_trace(self, tmp_path: Path) -> None:
        import json

        trace = tmp_path / "test.jsonl"
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 10, "corr": "c-1"},
            {"ts": 1.0, "agent": "a2", "kind": "receive", "from": "a1", "size": 10, "corr": "c-1"},
            {"ts": 2.0, "agent": "a1", "kind": "stop"},
        ]
        trace.write_text("\n".join(json.dumps(e) for e in events))

        result = runner.invoke(app, ["inspect", str(trace)])
        assert result.exit_code == 0
        assert "NEST Trace Summary" in result.output
        assert "Total events:" in result.output

    def test_inspect_missing_file(self) -> None:
        result = runner.invoke(app, ["inspect", "nonexistent.jsonl"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestReport:
    def test_report_metrics(self, tmp_path: Path) -> None:
        import json

        trace = tmp_path / "test.jsonl"
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 10, "corr": "c-1"},
            {"ts": 1.0, "agent": "a2", "kind": "receive", "from": "a1", "size": 10, "corr": "c-1"},
            {"ts": 2.0, "agent": "a1", "kind": "stop"},
        ]
        trace.write_text("\n".join(json.dumps(e) for e in events))

        result = runner.invoke(app, ["report", str(trace)])
        assert result.exit_code == 0
        assert "Metrics:" in result.output
        assert "success_rate" in result.output

    def test_report_with_html(self, tmp_path: Path) -> None:
        import json

        trace = tmp_path / "test.jsonl"
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 10, "corr": "c-1"},
            {"ts": 1.0, "agent": "a2", "kind": "receive", "from": "a1", "size": 10, "corr": "c-1"},
        ]
        trace.write_text("\n".join(json.dumps(e) for e in events))

        report_path = tmp_path / "report.html"
        result = runner.invoke(app, ["report", str(trace), "-o", str(report_path)])
        assert result.exit_code == 0
        assert "Report written to" in result.output
        assert report_path.exists()
        assert "NEST Trace Report" in report_path.read_text()

    def test_report_missing_file(self) -> None:
        result = runner.invoke(app, ["report", "nonexistent.jsonl"])
        assert result.exit_code == 1


class TestPluginsList:
    def test_list_all(self) -> None:
        result = runner.invoke(app, ["plugins", "list"])
        assert result.exit_code == 0
        assert "transport" in result.output
        assert "in_memory" in result.output
        assert "payments" in result.output

    def test_list_filtered(self) -> None:
        result = runner.invoke(app, ["plugins", "list", "payments"])
        assert result.exit_code == 0
        assert "prepaid_credits" in result.output
