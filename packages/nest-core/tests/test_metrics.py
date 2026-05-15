# SPDX-License-Identifier: Apache-2.0
"""Tests for metrics computation and HTML report generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nest_core.metrics import (
    ALL_METRICS,
    compute_metrics,
    generate_html_report,
)
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig


class TestComputeMetrics:
    def _write_trace(self, path: Path) -> None:
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 0.0, "agent": "a2", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 10, "corr": "c-1"},
            {"ts": 1.0, "agent": "a2", "kind": "receive", "from": "a1", "size": 10, "corr": "c-1"},
            {"ts": 2.0, "agent": "a2", "kind": "send", "to": "a1", "size": 8, "corr": "c-2"},
            {"ts": 2.0, "agent": "a1", "kind": "receive", "from": "a2", "size": 8, "corr": "c-2"},
            {"ts": 3.0, "agent": "a1", "kind": "send", "to": "a2", "size": 5, "corr": "c-3"},
            {"ts": 3.0, "agent": "a2", "kind": "dropped", "from": "a1", "size": 5, "corr": "c-3"},
            {"ts": 5.0, "agent": "a1", "kind": "stop"},
            {"ts": 5.0, "agent": "a2", "kind": "stop"},
        ]
        path.write_text("\n".join(json.dumps(e) for e in events))

    def test_success_rate(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["success_rate"])
        assert abs(results["success_rate"] - 2.0 / 3.0) < 0.01

    def test_message_count(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["message_count"])
        assert results["message_count"] == 5.0

    def test_mean_latency(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["mean_latency"])
        assert results["mean_latency"] == 0.0

    def test_dropped_count(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["dropped_count"])
        assert results["dropped_count"] == 1.0

    def test_agent_count(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["agent_count"])
        assert results["agent_count"] == 2.0

    def test_duration(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["duration"])
        assert results["duration"] == 5.0

    def test_all_metrics(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ALL_METRICS)
        assert len(results) == len(ALL_METRICS)

    def test_unknown_metric_ignored(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        self._write_trace(trace)
        results = compute_metrics(trace, ["nonexistent", "message_count"])
        assert "message_count" in results
        assert "nonexistent" not in results


class TestHtmlReport:
    def test_generates_html(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 10, "corr": "c-1"},
            {"ts": 1.0, "agent": "a2", "kind": "receive", "from": "a1", "size": 10, "corr": "c-1"},
            {"ts": 2.0, "agent": "a1", "kind": "stop"},
        ]
        trace.write_text("\n".join(json.dumps(e) for e in events))

        metrics = {"success_rate": 1.0, "message_count": 2.0}
        report_path = tmp_path / "report.html"
        result = generate_html_report(trace, metrics, report_path)

        assert result.exists()
        content = result.read_text()
        assert "NEST Trace Report" in content
        assert "success_rate" in content
        assert "message_count" in content
        assert "<table>" in content


class TestRunnerMetrics:
    @pytest.mark.asyncio
    async def test_runner_computes_metrics(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "m.jsonl"
        report_file = tmp_path / "report.html"
        config = ScenarioConfig.from_dict(
            {
                "name": "metrics-test",
                "seed": 42,
                "agents": {
                    "count": 10,
                    "roles": [
                        {"name": "buyer", "count": 5},
                        {"name": "seller", "count": 5},
                    ],
                },
                "task": {"type": "marketplace", "config": {"rounds": 3}},
                "duration": "ticks: 2000",
                "metrics": ["success_rate", "message_count", "agent_count"],
                "output": {"trace": str(trace_file), "report": str(report_file)},
            }
        )

        runner = ScenarioRunner(config)
        await runner.run()

        assert runner.metrics["success_rate"] > 0
        assert runner.metrics["message_count"] > 0
        assert runner.metrics["agent_count"] == 10.0
        assert report_file.exists()
        assert "NEST Trace Report" in report_file.read_text()
