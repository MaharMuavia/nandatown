# SPDX-License-Identifier: Apache-2.0
"""Tests for auction and voting scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig


class TestAuctionScenario:
    @pytest.mark.asyncio
    async def test_auction_from_dict(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "auction.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "test-auction",
                "seed": 42,
                "agents": {
                    "count": 6,
                    "roles": [
                        {"name": "auctioneer", "count": 1},
                        {"name": "bidder", "count": 5},
                    ],
                },
                "task": {"type": "auction", "config": {"rounds": 3}},
                "duration": "ticks: 5000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        result = await runner.run()

        assert result.exists()
        content = result.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

        kinds: set[str] = set()
        for line in lines:
            event: dict[str, Any] = json.loads(line)
            kinds.add(event["kind"])

        assert "send" in kinds
        assert "receive" in kinds

    @pytest.mark.asyncio
    async def test_auction_yaml(self, tmp_path: Path) -> None:
        yaml_path = Path(__file__).parent.parent.parent.parent / "scenarios" / "auction.yaml"
        if not yaml_path.exists():
            pytest.skip("auction.yaml not found")

        config = ScenarioConfig.from_yaml(yaml_path)
        config.output.trace = str(tmp_path / "auction.jsonl")
        config.duration = "ticks: 5000"

        runner = ScenarioRunner(config)
        result = await runner.run()
        assert result.exists()

        content = result.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 10


class TestVotingScenario:
    @pytest.mark.asyncio
    async def test_voting_from_dict(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "voting.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "test-voting",
                "seed": 42,
                "agents": {
                    "count": 12,
                    "roles": [
                        {"name": "proposer", "count": 1},
                        {"name": "coordinator", "count": 1},
                        {"name": "voter", "count": 10},
                    ],
                },
                "task": {"type": "voting", "config": {"rounds": 3, "threshold": 0.5}},
                "duration": "ticks: 5000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        result = await runner.run()

        assert result.exists()
        content = result.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

        kinds: set[str] = set()
        for line in lines:
            event: dict[str, Any] = json.loads(line)
            kinds.add(event["kind"])

        assert "send" in kinds
        assert "receive" in kinds

    @pytest.mark.asyncio
    async def test_voting_yaml(self, tmp_path: Path) -> None:
        yaml_path = Path(__file__).parent.parent.parent.parent / "scenarios" / "voting.yaml"
        if not yaml_path.exists():
            pytest.skip("voting.yaml not found")

        config = ScenarioConfig.from_yaml(yaml_path)
        config.output.trace = str(tmp_path / "voting.jsonl")
        config.duration = "ticks: 5000"

        runner = ScenarioRunner(config)
        result = await runner.run()
        assert result.exists()

        content = result.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 10

    @pytest.mark.asyncio
    async def test_voting_deterministic(self, tmp_path: Path) -> None:
        traces: list[str] = []
        for i in range(2):
            trace_file = tmp_path / f"vote_{i}.jsonl"
            config = ScenarioConfig.from_dict(
                {
                    "name": "det-vote",
                    "seed": 77,
                    "agents": {
                        "count": 7,
                        "roles": [
                            {"name": "proposer", "count": 1},
                            {"name": "coordinator", "count": 1},
                            {"name": "voter", "count": 5},
                        ],
                    },
                    "task": {"type": "voting", "config": {"rounds": 2}},
                    "duration": "ticks: 3000",
                    "output": {"trace": str(trace_file)},
                }
            )
            runner = ScenarioRunner(config)
            await runner.run()
            traces.append(trace_file.read_text())

        assert traces[0] == traces[1]
        assert len(traces[0]) > 0
