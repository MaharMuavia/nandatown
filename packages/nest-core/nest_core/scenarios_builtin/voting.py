# SPDX-License-Identifier: Apache-2.0
"""Voting/consensus scenario — agents vote on proposals and reach agreement.

A proposer broadcasts proposals, voters cast votes,
and a coordinator tallies results.

Example::

    agents = voting_factory(config, plugins)
"""

from __future__ import annotations

from typing import Any

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId


class ProposerAgent(StateMachineAgent):
    """Broadcasts proposals to all voters."""

    def __init__(self, agent_id: AgentId, num_voters: int, rounds: int = 3) -> None:
        self._id = agent_id
        self._num_voters = num_voters
        self._rounds = rounds
        self._round = 0

    async def on_start(self, ctx: AgentContext) -> None:
        self._round = 1
        for i in range(self._num_voters):
            voter = AgentId(f"voter-{i}")
            await ctx.send(voter, f"propose:{self._round}:increase-budget".encode())

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        msg = payload.decode("utf-8", errors="replace")

        if msg.startswith("result:"):
            self._round += 1
            if self._round <= self._rounds:
                topic = ctx.rng.choice(["increase-budget", "new-policy", "elect-leader"])
                for i in range(self._num_voters):
                    voter = AgentId(f"voter-{i}")
                    await ctx.send(voter, f"propose:{self._round}:{topic}".encode())


class VoterAgent(StateMachineAgent):
    """Votes on proposals based on random preference."""

    def __init__(self, agent_id: AgentId, coordinator: AgentId) -> None:
        self._id = agent_id
        self._coordinator = coordinator

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        msg = payload.decode("utf-8", errors="replace")

        if msg.startswith("propose:"):
            parts = msg.split(":")
            if len(parts) >= 3:
                round_num = parts[1]
                vote = "yes" if ctx.rng.random() > 0.3 else "no"
                await ctx.send(
                    self._coordinator,
                    f"vote:{round_num}:{vote}:{self._id}".encode(),
                )


class CoordinatorAgent(StateMachineAgent):
    """Tallies votes and announces results."""

    def __init__(
        self,
        agent_id: AgentId,
        proposer: AgentId,
        num_voters: int,
        threshold: float = 0.5,
    ) -> None:
        self._id = agent_id
        self._proposer = proposer
        self._num_voters = num_voters
        self._threshold = threshold
        self._votes: dict[str, list[str]] = {}
        self._decided: set[str] = set()

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        msg = payload.decode("utf-8", errors="replace")

        if msg.startswith("vote:"):
            parts = msg.split(":")
            if len(parts) >= 4:
                round_num = parts[1]
                vote = parts[2]

                if round_num not in self._votes:
                    self._votes[round_num] = []
                self._votes[round_num].append(vote)

                all_voted = len(self._votes[round_num]) >= self._num_voters
                if all_voted and round_num not in self._decided:
                    self._decided.add(round_num)
                    yes_count = sum(1 for v in self._votes[round_num] if v == "yes")
                    total = len(self._votes[round_num])
                    passed = yes_count / total >= self._threshold

                    result = "passed" if passed else "rejected"
                    await ctx.send(
                        self._proposer,
                        f"result:{round_num}:{result}:{yes_count}/{total}".encode(),
                    )


def voting_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create proposer, voter, and coordinator agents.

    Example::

        agents = voting_factory(config, plugins)
    """
    task_config = config.task.config
    rounds = task_config.get("rounds", 3)
    threshold = task_config.get("threshold", 0.5)

    agents: dict[AgentId, StateMachineAgent] = {}

    if config.agents.roles:
        voter_count = 0
        for role in config.agents.roles:
            if role.name == "voter":
                voter_count = role.count
        if voter_count == 0:
            voter_count = max(1, config.agents.count - 2)
    else:
        voter_count = max(1, config.agents.count - 2)

    proposer_id = AgentId("proposer-0")
    coordinator_id = AgentId("coordinator-0")

    agents[proposer_id] = ProposerAgent(proposer_id, num_voters=voter_count, rounds=rounds)
    agents[coordinator_id] = CoordinatorAgent(
        coordinator_id,
        proposer=proposer_id,
        num_voters=voter_count,
        threshold=threshold,
    )

    for i in range(voter_count):
        aid = AgentId(f"voter-{i}")
        agents[aid] = VoterAgent(aid, coordinator=coordinator_id)

    return agents
