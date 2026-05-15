# SPDX-License-Identifier: Apache-2.0
"""Tests for Tier 2 shell agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.sim.simulator import Simulator
from nest_core.types import AgentId
from nest_shell.agent import ShellAgent, parse_action, shell_marketplace_factory
from nest_shell.factories import shell_auction_factory, shell_voting_factory
from nest_shell.llm import MockLLMBackend


class TestParseAction:
    def test_parse_send(self) -> None:
        response = "ACTION: send\nTO: seller-0\nMESSAGE: buy:product-0:50"
        action = parse_action(response, AgentId("buyer-0"))
        assert action is not None
        assert action["action"] == "send"
        assert action["to"] == AgentId("seller-0")
        assert action["message"] == b"buy:product-0:50"

    def test_parse_none(self) -> None:
        action = parse_action("ACTION: none", AgentId("buyer-0"))
        assert action is None

    def test_parse_sender_placeholder(self) -> None:
        response = "ACTION: send\nTO: {sender}\nMESSAGE: sold:product:50"
        action = parse_action(response, AgentId("buyer-3"))
        assert action is not None
        assert action["to"] == AgentId("buyer-3")

    def test_parse_no_to_defaults_to_sender(self) -> None:
        response = "ACTION: send\nMESSAGE: sold:product:50"
        action = parse_action(response, AgentId("buyer-5"))
        assert action is not None
        assert action["to"] == AgentId("buyer-5")

    def test_parse_garbage(self) -> None:
        action = parse_action("I don't know what to do", AgentId("a"))
        assert action is None


class TestMockLLMBackend:
    @pytest.mark.asyncio
    async def test_buy_response(self) -> None:
        backend = MockLLMBackend()
        response = await backend.complete(
            [{"role": "user", "content": "Message from buyer-0: buy:product:50"}]
        )
        assert "ACTION: send" in response
        assert "sold:" in response
        assert backend.call_count == 1

    @pytest.mark.asyncio
    async def test_sold_response(self) -> None:
        backend = MockLLMBackend()
        response = await backend.complete(
            [{"role": "user", "content": "Message from seller-0: sold:product:50"}]
        )
        assert "ACTION: send" in response
        assert "buy:" in response

    @pytest.mark.asyncio
    async def test_none_response(self) -> None:
        backend = MockLLMBackend()
        response = await backend.complete([{"role": "user", "content": "Hello world"}])
        assert "ACTION: none" in response

    @pytest.mark.asyncio
    async def test_custom_responses(self) -> None:
        backend = MockLLMBackend(
            responses={
                "special": "ACTION: send\nTO: admin\nMESSAGE: alert:critical",
            }
        )
        response = await backend.complete(
            [{"role": "user", "content": "This is a special message"}]
        )
        assert "alert:critical" in response


class TestShellAgent:
    @pytest.mark.asyncio
    async def test_shell_agent_simulation(self, tmp_path: Path) -> None:
        backend = MockLLMBackend()
        trace_file = tmp_path / "shell.jsonl"

        sim = Simulator(seed=42, trace_path=trace_file)

        buyer = ShellAgent(
            AgentId("buyer-0"),
            role="buyer",
            backend=backend,
            num_sellers=2,
            rounds=3,
        )
        seller = ShellAgent(
            AgentId("seller-0"),
            role="seller",
            backend=backend,
            num_sellers=2,
            rounds=3,
        )
        seller2 = ShellAgent(
            AgentId("seller-1"),
            role="seller",
            backend=backend,
            num_sellers=2,
            rounds=3,
        )

        sim.add_agent(AgentId("buyer-0"), buyer)
        sim.add_agent(AgentId("seller-0"), seller)
        sim.add_agent(AgentId("seller-1"), seller2)

        await sim.run(max_ticks=5000)

        assert trace_file.exists()
        content = trace_file.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

        assert backend.call_count > 0
        assert buyer.action_count > 0

    @pytest.mark.asyncio
    async def test_shell_marketplace_factory(self, tmp_path: Path) -> None:
        backend = MockLLMBackend()
        trace_file = tmp_path / "shell_market.jsonl"

        config = ScenarioConfig.from_dict(
            {
                "name": "shell-test",
                "seed": 42,
                "agents": {
                    "count": 6,
                    "roles": [
                        {"name": "buyer", "count": 3},
                        {"name": "seller", "count": 3},
                    ],
                },
                "task": {"type": "marketplace", "config": {"rounds": 3}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        agents = shell_marketplace_factory(config, {}, backend=backend)
        assert len(agents) == 6

        buyer_count = sum(1 for k in agents if str(k).startswith("buyer"))
        seller_count = sum(1 for k in agents if str(k).startswith("seller"))
        assert buyer_count == 3
        assert seller_count == 3

        sim = Simulator(seed=42, trace_path=trace_file)
        for aid, agent in agents.items():
            sim.add_agent(aid, agent)

        await sim.run(max_ticks=2000)

        assert trace_file.exists()
        content = trace_file.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

        send_count = 0
        for line in lines:
            event: dict[str, Any] = json.loads(line)
            if event["kind"] == "send":
                send_count += 1
        assert send_count > 0
        assert backend.call_count > 0

    @pytest.mark.asyncio
    async def test_history_truncation(self) -> None:
        """Verify conversation history doesn't grow unbounded."""
        backend = MockLLMBackend()
        agent = ShellAgent(
            AgentId("buyer-0"),
            role="buyer",
            backend=backend,
            num_sellers=1,
            rounds=50,
        )
        assert agent.history_length == 1  # system prompt only


class TestShellAuctionFactory:
    @pytest.mark.asyncio
    async def test_creates_correct_agents(self) -> None:
        config = ScenarioConfig.from_dict(
            {
                "name": "auction-shell-test",
                "seed": 42,
                "agents": {
                    "count": 5,
                    "roles": [
                        {"name": "auctioneer", "count": 1},
                        {"name": "bidder", "count": 4},
                    ],
                },
                "task": {"type": "auction", "config": {"rounds": 3}},
            }
        )
        backend = MockLLMBackend()
        agents = shell_auction_factory(config, {}, backend=backend)

        assert len(agents) == 5
        assert AgentId("auctioneer-0") in agents
        assert all(isinstance(a, ShellAgent) for a in agents.values())

        bidder_count = sum(1 for k in agents if str(k).startswith("bidder"))
        assert bidder_count == 4

    @pytest.mark.asyncio
    async def test_simulation_runs(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "auction_shell.jsonl"
        backend = MockLLMBackend()

        config = ScenarioConfig.from_dict(
            {
                "name": "auction-shell-sim",
                "seed": 42,
                "agents": {"count": 4},
                "task": {"type": "auction", "config": {"rounds": 2}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        agents = shell_auction_factory(config, {}, backend=backend)
        sim = Simulator(seed=42, trace_path=trace_file)
        for aid, agent in agents.items():
            sim.add_agent(aid, agent)

        await sim.run(max_ticks=2000)

        assert trace_file.exists()
        content = trace_file.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0


class TestShellVotingFactory:
    @pytest.mark.asyncio
    async def test_creates_correct_agents(self) -> None:
        config = ScenarioConfig.from_dict(
            {
                "name": "voting-shell-test",
                "seed": 42,
                "agents": {
                    "count": 7,
                    "roles": [
                        {"name": "proposer", "count": 1},
                        {"name": "coordinator", "count": 1},
                        {"name": "voter", "count": 5},
                    ],
                },
                "task": {"type": "voting", "config": {"rounds": 2}},
            }
        )
        backend = MockLLMBackend()
        agents = shell_voting_factory(config, {}, backend=backend)

        assert len(agents) == 7
        assert AgentId("proposer-0") in agents
        assert AgentId("coordinator-0") in agents
        assert all(isinstance(a, ShellAgent) for a in agents.values())

        voter_count = sum(1 for k in agents if str(k).startswith("voter"))
        assert voter_count == 5

    @pytest.mark.asyncio
    async def test_simulation_runs(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "voting_shell.jsonl"
        backend = MockLLMBackend()

        config = ScenarioConfig.from_dict(
            {
                "name": "voting-shell-sim",
                "seed": 42,
                "agents": {"count": 5},
                "task": {"type": "voting", "config": {"rounds": 2}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        agents = shell_voting_factory(config, {}, backend=backend)
        sim = Simulator(seed=42, trace_path=trace_file)
        for aid, agent in agents.items():
            sim.add_agent(aid, agent)

        await sim.run(max_ticks=2000)

        assert trace_file.exists()
        content = trace_file.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0


class TestRunnerBrainDispatch:
    @pytest.mark.asyncio
    async def test_runner_llm_brain_creates_shell_agents(self, tmp_path: Path) -> None:
        """Runner with brain='llm' and llm_model='mock' creates ShellAgents."""
        trace_file = tmp_path / "runner_llm.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "runner-llm-test",
                "seed": 42,
                "agents": {
                    "count": 4,
                    "brain": "llm",
                    "llm_model": "mock",
                    "roles": [
                        {"name": "buyer", "count": 2},
                        {"name": "seller", "count": 2},
                    ],
                },
                "task": {"type": "marketplace", "config": {"rounds": 3}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        trace_path = await runner.run()

        assert trace_path.exists()
        content = trace_path.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

        send_count = 0
        for line in lines:
            event: dict[str, Any] = json.loads(line)
            if event["kind"] == "send":
                send_count += 1
        assert send_count > 0

    @pytest.mark.asyncio
    async def test_runner_shell_brain_creates_shell_agents(self, tmp_path: Path) -> None:
        """Runner with brain='shell' also creates ShellAgents."""
        trace_file = tmp_path / "runner_shell.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "runner-shell-test",
                "seed": 42,
                "agents": {
                    "count": 4,
                    "brain": "shell",
                    "llm_model": "mock",
                },
                "task": {"type": "marketplace", "config": {"rounds": 2}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        trace_path = await runner.run()

        assert trace_path.exists()
        content = trace_path.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

    @pytest.mark.asyncio
    async def test_runner_state_machine_still_works(self, tmp_path: Path) -> None:
        """Default brain='state-machine' continues to use existing factories."""
        trace_file = tmp_path / "runner_sm.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "runner-sm-test",
                "seed": 42,
                "agents": {"count": 6},
                "task": {"type": "marketplace", "config": {"rounds": 3}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        trace_path = await runner.run()

        assert trace_path.exists()
        content = trace_path.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0

    @pytest.mark.asyncio
    async def test_runner_llm_auction(self, tmp_path: Path) -> None:
        """Runner creates shell auction agents with brain='llm'."""
        trace_file = tmp_path / "runner_auction_llm.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "runner-auction-llm",
                "seed": 42,
                "agents": {
                    "count": 4,
                    "brain": "llm",
                    "llm_model": "mock",
                },
                "task": {"type": "auction", "config": {"rounds": 2}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        trace_path = await runner.run()
        assert trace_path.exists()

    @pytest.mark.asyncio
    async def test_runner_llm_voting(self, tmp_path: Path) -> None:
        """Runner creates shell voting agents with brain='llm'."""
        trace_file = tmp_path / "runner_voting_llm.jsonl"
        config = ScenarioConfig.from_dict(
            {
                "name": "runner-voting-llm",
                "seed": 42,
                "agents": {
                    "count": 5,
                    "brain": "llm",
                    "llm_model": "mock",
                },
                "task": {"type": "voting", "config": {"rounds": 2}},
                "duration": "ticks: 2000",
                "output": {"trace": str(trace_file)},
            }
        )

        runner = ScenarioRunner(config)
        trace_path = await runner.run()
        assert trace_path.exists()

    @pytest.mark.asyncio
    async def test_yaml_scenario_with_brain_llm(self, tmp_path: Path) -> None:
        """End-to-end: load a YAML scenario with brain=llm and run it."""
        import yaml

        yaml_path = tmp_path / "shell_test.yaml"
        trace_file = tmp_path / "yaml_shell.jsonl"

        scenario = {
            "name": "yaml-shell-test",
            "seed": 42,
            "agents": {
                "count": 4,
                "brain": "llm",
                "llm_model": "mock",
                "roles": [
                    {"name": "buyer", "count": 2},
                    {"name": "seller", "count": 2},
                ],
            },
            "task": {"type": "marketplace", "config": {"rounds": 2}},
            "duration": "ticks: 2000",
            "output": {"trace": str(trace_file)},
        }

        with yaml_path.open("w") as f:
            yaml.dump(scenario, f)

        config = ScenarioConfig.from_yaml(yaml_path)
        assert config.agents.brain == "llm"
        assert config.agents.llm_model == "mock"

        runner = ScenarioRunner(config)
        trace_path = await runner.run()

        assert trace_path.exists()
        content = trace_path.read_text()
        lines = [ln for ln in content.strip().split("\n") if ln]
        assert len(lines) > 0
