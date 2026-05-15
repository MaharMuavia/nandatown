# SPDX-License-Identifier: Apache-2.0
"""Shell agent factories for auction and voting scenarios.

These factories create LLM-backed :class:`ShellAgent` instances with
scenario-appropriate system prompts so users can set ``brain: llm``
in their YAML files.

Example::

    agents = shell_auction_factory(config, plugins, backend=MockLLMBackend())
"""

from __future__ import annotations

from typing import Any

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import StateMachineAgent
from nest_core.types import AgentId

from nest_shell.agent import ShellAgent
from nest_shell.llm import LLMBackend

_AUCTION_AUCTIONEER_PROMPT = """\
You are an auctioneer in a multi-agent auction simulation.
Your role is: auctioneer

When the simulation starts, announce an item for auction to all bidders.
When you receive bids, track them and pick the highest bidder.

Respond in this exact format:

ACTION: send
TO: <agent-id>
MESSAGE: <message-content>

Or if no action is needed:
ACTION: none

Rules:
- Announce items with format: auction:<item>:<base_price>
- When all bids arrive, notify the winner with: won:<item>:<price>
- Notify losers with: lost:<item>:<winning_price>
- Start new rounds after announcing results.
"""

_AUCTION_BIDDER_PROMPT = """\
You are a bidder in a multi-agent auction simulation.
Your role is: bidder

When you receive an auction announcement, decide how much to bid.

Respond in this exact format:

ACTION: send
TO: <agent-id>
MESSAGE: <message-content>

Or if no action is needed:
ACTION: none

Rules:
- When you see auction:<item>:<base_price>, respond with bid:<item>:<your_bid>
- Your bid should be at or above the base price but within your budget.
- If you win, you receive won:<item>:<price>. If you lose, you receive lost:<item>:<price>.
"""

_VOTING_PROPOSER_PROMPT = """\
You are a proposer in a multi-agent voting simulation.
Your role is: proposer

You propose topics for voters to vote on.

Respond in this exact format:

ACTION: send
TO: <agent-id>
MESSAGE: <message-content>

Or if no action is needed:
ACTION: none

Rules:
- Propose topics with format: propose:<round>:<topic>
- When you receive result:<round>:<outcome>:<tally>, start a new round.
- Topics can be: increase-budget, new-policy, elect-leader.
"""

_VOTING_VOTER_PROMPT = """\
You are a voter in a multi-agent voting simulation.
Your role is: voter

When you receive a proposal, cast your vote.

Respond in this exact format:

ACTION: send
TO: <agent-id>
MESSAGE: <message-content>

Or if no action is needed:
ACTION: none

Rules:
- When you see propose:<round>:<topic>, respond with vote:<round>:<yes_or_no>:<your_id>
- Send your vote to the coordinator (coordinator-0).
- Vote yes or no based on the topic.
"""

_VOTING_COORDINATOR_PROMPT = """\
You are a coordinator in a multi-agent voting simulation.
Your role is: coordinator

You tally votes and announce results.

Respond in this exact format:

ACTION: send
TO: <agent-id>
MESSAGE: <message-content>

Or if no action is needed:
ACTION: none

Rules:
- Collect vote:<round>:<yes_or_no>:<voter_id> messages from voters.
- When all votes arrive, announce result:<round>:<passed_or_rejected>:<tally> to the proposer.
"""


def shell_auction_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
    backend: LLMBackend | None = None,
) -> dict[AgentId, StateMachineAgent]:
    """Create shell agents for the auction scenario.

    Example::

        agents = shell_auction_factory(config, plugins, backend=MockLLMBackend())
    """
    from nest_shell.llm import MockLLMBackend

    if backend is None:
        backend = MockLLMBackend()

    task_config = config.task.config
    rounds = task_config.get("rounds", 5)

    agents: dict[AgentId, StateMachineAgent] = {}

    if config.agents.roles:
        bidder_count = 0
        for role in config.agents.roles:
            if role.name == "bidder":
                bidder_count = role.count
        if bidder_count == 0:
            bidder_count = config.agents.count - 1
    else:
        bidder_count = config.agents.count - 1

    auctioneer_id = AgentId("auctioneer-0")
    agents[auctioneer_id] = ShellAgent(
        agent_id=auctioneer_id,
        role="auctioneer",
        backend=backend,
        system_prompt=_AUCTION_AUCTIONEER_PROMPT,
        num_sellers=bidder_count,
        rounds=rounds,
    )

    for i in range(bidder_count):
        aid = AgentId(f"bidder-{i}")
        agents[aid] = ShellAgent(
            agent_id=aid,
            role="bidder",
            backend=backend,
            system_prompt=_AUCTION_BIDDER_PROMPT,
            num_sellers=bidder_count,
            rounds=rounds,
        )

    return agents


def shell_voting_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
    backend: LLMBackend | None = None,
) -> dict[AgentId, StateMachineAgent]:
    """Create shell agents for the voting scenario.

    Example::

        agents = shell_voting_factory(config, plugins, backend=MockLLMBackend())
    """
    from nest_shell.llm import MockLLMBackend

    if backend is None:
        backend = MockLLMBackend()

    task_config = config.task.config
    rounds = task_config.get("rounds", 3)

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

    agents[proposer_id] = ShellAgent(
        agent_id=proposer_id,
        role="proposer",
        backend=backend,
        system_prompt=_VOTING_PROPOSER_PROMPT,
        num_sellers=voter_count,
        rounds=rounds,
    )
    agents[coordinator_id] = ShellAgent(
        agent_id=coordinator_id,
        role="coordinator",
        backend=backend,
        system_prompt=_VOTING_COORDINATOR_PROMPT,
        num_sellers=voter_count,
        rounds=rounds,
    )

    for i in range(voter_count):
        aid = AgentId(f"voter-{i}")
        agents[aid] = ShellAgent(
            agent_id=aid,
            role="voter",
            backend=backend,
            system_prompt=_VOTING_VOTER_PROMPT,
            num_sellers=voter_count,
            rounds=rounds,
        )

    return agents
