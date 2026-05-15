# SPDX-License-Identifier: Apache-2.0
"""Tests for trace inspection and correlation IDs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nest_core.inspect import analyze_trace, format_summary
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig


class TestAnalyzeTrace:
    def test_basic_stats(self, tmp_path: Path) -> None:
        trace = tmp_path / "test.jsonl"
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 0.0, "agent": "a2", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 10, "corr": "corr-1"},
            {
                "ts": 1.0,
                "agent": "a2",
                "kind": "receive",
                "from": "a1",
                "size": 10,
                "corr": "corr-1",
            },
            {"ts": 5.0, "agent": "a1", "kind": "stop"},
            {"ts": 5.0, "agent": "a2", "kind": "stop"},
        ]
        trace.write_text("\n".join(json.dumps(e) for e in events))

        summary = analyze_trace(trace)
        assert summary.total_events == 6
        assert summary.agent_count == 2
        assert summary.message_count == 2
        assert summary.unique_correlations == 1
        assert summary.duration == 5.0
        assert summary.event_kinds["start"] == 2
        assert summary.event_kinds["send"] == 1

    def test_format_summary(self, tmp_path: Path) -> None:
        trace = tmp_path / "test.jsonl"
        events = [
            {"ts": 0.0, "agent": "a1", "kind": "start"},
            {"ts": 1.0, "agent": "a1", "kind": "send", "to": "a2", "size": 5, "corr": "corr-1"},
            {"ts": 2.0, "agent": "a1", "kind": "stop"},
        ]
        trace.write_text("\n".join(json.dumps(e) for e in events))

        summary = analyze_trace(trace)
        text = format_summary(summary)
        assert "NEST Trace Summary" in text
        assert "Total events:" in text
        assert "3" in text


class TestCorrelationIds:
    @pytest.mark.asyncio
    async def test_trace_has_correlation_ids(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "corr.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "corr-test",
                "seed": 42,
                "agents": {
                    "count": 4,
                    "roles": [
                        {"name": "buyer", "count": 2},
                        {"name": "seller", "count": 2},
                    ],
                },
                "task": {"type": "marketplace", "config": {"rounds": 2}},
                "duration": "ticks: 1000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        await runner.run()

        content = trace_file.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]

        send_events: list[dict[str, Any]] = []
        recv_events: list[dict[str, Any]] = []
        for line in lines:
            event: dict[str, Any] = json.loads(line)
            if event["kind"] == "send":
                send_events.append(event)
            elif event["kind"] == "receive":
                recv_events.append(event)

        assert len(send_events) > 0
        for ev in send_events:
            assert "corr" in ev, f"send event missing corr: {ev}"

        assert len(recv_events) > 0
        for ev in recv_events:
            assert "corr" in ev, f"receive event missing corr: {ev}"

        send_corrs: set[str] = {ev["corr"] for ev in send_events}
        recv_corrs: set[str] = {ev["corr"] for ev in recv_events}
        assert send_corrs & recv_corrs, "send/receive should share correlation IDs"
