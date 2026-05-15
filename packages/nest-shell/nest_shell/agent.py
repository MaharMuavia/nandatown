# SPDX-License-Identifier: Apache-2.0
"""Tier 2 LLM-backed shell agent.

Replaces hardcoded state-machine logic with LLM-driven decision making.
The agent maintains a conversation history and asks the LLM what to do
on each event.

Example::

    backend = MockLLMBackend()
    agent = ShellAgent(AgentId("buyer-0"), role="buyer", backend=backend)
"""

from __future__ import annotations

import re
from typing import Any

from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId

from nest_shell.llm import LLMBackend

_DEFAULT_SYSTEM_PROMPT = """\
You are an agent in a multi-agent marketplace simulation.
Your role is: {role}

When you receive a message, decide what action to take.
Respond in this exact format:

ACTION: send
TO: <agent-id>
MESSAGE: <message-content>

Or if no action is needed:
ACTION: none

Rules:
- If you are a buyer, send buy requests to sellers.
- If you are a seller, respond to buy requests with "sold:" or "reject:".
- Always include the product and price in messages.
- Format: buy:<product>:<price> or sold:<product>:<price> or reject:<product>:<min_price>
"""


def parse_action(response: str, sender: AgentId) -> dict[str, Any] | None:
    """Parse an LLM response into an action dict.

    Example::

        action = parse_action("ACTION: send\\nTO: seller-0\\nMESSAGE: buy:p:50", sender)
    """
    response = response.strip()

    action_match = re.search(r"ACTION:\s*(\w+)", response)
    if not action_match:
        return None

    action_type = action_match.group(1).lower()
    if action_type == "none":
        return None

    if action_type == "send":
        to_match = re.search(r"TO:\s*(.+)", response)
        msg_match = re.search(r"MESSAGE:\s*(.+)", response)

        if not msg_match:
            return None

        target_str = to_match.group(1).strip() if to_match else str(sender)
        target_str = target_str.replace("{sender}", str(sender))

        message = msg_match.group(1).strip()
        message = message.replace("{sender}", str(sender))

        return {
            "action": "send",
            "to": AgentId(target_str),
            "message": message.encode("utf-8"),
        }

    return None


class ShellAgent(StateMachineAgent):
    """LLM-backed agent that uses a language model to decide actions.

    Example::

        agent = ShellAgent(
            agent_id=AgentId("buyer-0"),
            role="buyer",
            backend=MockLLMBackend(),
        )
    """

    def __init__(
        self,
        agent_id: AgentId,
        role: str,
        backend: LLMBackend,
        system_prompt: str | None = None,
        num_sellers: int = 10,
        rounds: int = 10,
    ) -> None:
        self._id = agent_id
        self._role = role
        self._backend = backend
        self._system_prompt = (system_prompt or _DEFAULT_SYSTEM_PROMPT).format(role=role)
        self._history: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        self._num_sellers = num_sellers
        self._rounds = rounds
        self._round = 0
        self._action_count = 0

    async def on_start(self, ctx: AgentContext) -> None:
        if self._role == "buyer":
            seller_idx = ctx.rng.randint(0, self._num_sellers - 1)
            seller = AgentId(f"seller-{seller_idx}")
            price = ctx.rng.randint(10, 100)

            self._history.append(
                {
                    "role": "user",
                    "content": f"Simulation started. You are {self._id}. "
                    f"Send a buy request to a seller. "
                    f"Suggested target: {seller}, suggested price: {price}.",
                }
            )

            response = await self._backend.complete(self._history)
            self._history.append({"role": "assistant", "content": response})

            action = parse_action(response, seller)
            if action and action["action"] == "send":
                await ctx.send(action["to"], action["message"])
                self._action_count += 1
            else:
                await ctx.send(seller, f"buy:product-0:{price}".encode())
                self._action_count += 1

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        msg = payload.decode("utf-8", errors="replace")
        self._round += 1

        if self._round > self._rounds:
            return

        self._history.append(
            {
                "role": "user",
                "content": f"Message from {sender}: {msg}",
            }
        )

        if len(self._history) > 20:
            self._history = [self._history[0]] + self._history[-18:]

        response = await self._backend.complete(self._history)
        self._history.append({"role": "assistant", "content": response})

        action = parse_action(response, sender)
        if action and action["action"] == "send":
            await ctx.send(action["to"], action["message"])
            self._action_count += 1

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def history_length(self) -> int:
        return len(self._history)


def shell_marketplace_factory(
    config: Any,
    plugins: dict[str, Any],
    backend: LLMBackend | None = None,
) -> dict[AgentId, StateMachineAgent]:
    """Create shell agents for the marketplace scenario.

    Example::

        agents = shell_marketplace_factory(config, plugins, backend=MockLLMBackend())
    """
    from nest_shell.llm import MockLLMBackend

    if backend is None:
        backend = MockLLMBackend()

    task_config = config.task.config
    rounds = task_config.get("rounds", 10)

    agents: dict[AgentId, StateMachineAgent] = {}

    if config.agents.roles:
        buyer_count = 0
        seller_count = 0
        for role in config.agents.roles:
            if role.name == "buyer":
                buyer_count = role.count
            elif role.name == "seller":
                seller_count = role.count
    else:
        buyer_count = config.agents.count // 2
        seller_count = config.agents.count - buyer_count

    for i in range(seller_count):
        aid = AgentId(f"seller-{i}")
        agents[aid] = ShellAgent(
            agent_id=aid,
            role="seller",
            backend=backend,
            num_sellers=seller_count,
            rounds=rounds,
        )

    for i in range(buyer_count):
        aid = AgentId(f"buyer-{i}")
        agents[aid] = ShellAgent(
            agent_id=aid,
            role="buyer",
            backend=backend,
            num_sellers=seller_count,
            rounds=rounds,
        )

    return agents
