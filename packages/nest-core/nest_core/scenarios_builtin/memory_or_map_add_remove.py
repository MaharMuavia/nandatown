# SPDX-License-Identifier: Apache-2.0
"""OR-Map add/remove churn scenario -- prove add-wins convergence end-to-end.

Every agent owns its **own replica** of the memory plugin (a per-agent plugin
override) and, at start-up, writes a distinct value to the *same* shared key.
A designated subset of agents then issues an observed-remove of that key one
round later -- retiring only the adds they have gossiped so far, while other
agents' concurrent adds are still in flight. Agents run a fixed number of
full-state anti-entropy rounds (broadcasting ``export_all`` snapshots; peers
``merge_all`` whatever they receive), so under a lossy network the redundant
rounds still drive every replica to the same **add-wins** result: the key
stays present, holding the deterministic winning add, because a remove can only
erase adds it had already observed.

On stop each agent broadcasts a ``final:<json>`` record carrying the *winning
value* it reads for the key, so the ``memory_or_map_add_remove`` trace
validator (:func:`nest_core.validators.validate_or_map_convergence`) can
confirm the swarm converged to one value regardless of delivery order or loss.

Example::

    agents = memory_or_map_add_remove_factory(config, plugins)
"""

from __future__ import annotations

import base64
import json
from typing import Any

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId

_TICK = b"tick"
_REMOVE_TICK = b"remove-tick"
_SYNC_PREFIX = "sync:"
_FINAL_PREFIX = "final:"


class OrMapChurnAgent(StateMachineAgent):
    """Writes one value to a shared key, optionally removes it, then gossips.

    The agent reads its private replica from ``ctx.plugins["memory"]`` (a
    per-agent override), so every agent merges independently and the scenario
    exercises real conflict resolution rather than a single shared dict. A
    ``remover`` schedules an observed-remove one round after its initial write,
    modelling the add-wins race at swarm scale.

    Example::

        agent = OrMapChurnAgent(AgentId("w0"), key="shared", value=b"v0",
                                rounds=20, remover=False)
    """

    def __init__(
        self,
        agent_id: AgentId,
        key: str,
        value: bytes,
        rounds: int,
        remover: bool,
    ) -> None:
        self._id = agent_id
        self._key = key
        self._value = value
        self._rounds = rounds
        self._remover = remover

    async def on_start(self, ctx: AgentContext) -> None:
        """Write this agent's value, schedule a remove (if remover) and all rounds.

        Scheduling every gossip round up front (rather than chaining tick to
        tick) means a dropped tick cannot halt the loop -- the remaining ticks
        still fire, which is what makes convergence robust to loss.

        Example::

            await agent.on_start(ctx)
        """
        mem = ctx.plugins["memory"]
        await mem.write(self._key, self._value)
        if self._remover:
            await ctx.schedule(1.0, _REMOVE_TICK)
        for round_idx in range(self._rounds):
            await ctx.schedule(float(round_idx + 2), _TICK)

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """Handle a gossip tick, a remove tick, or an incoming full-state sync.

        Example::

            await agent.on_message(ctx, AgentId("w1"), b"tick")
        """
        mem = ctx.plugins["memory"]
        if payload == _REMOVE_TICK:
            await mem.remove(self._key)
            return
        if payload == _TICK:
            state = mem.export_all()
            await ctx.broadcast(_SYNC_PREFIX.encode() + state)
            return
        text = payload.decode("utf-8", errors="replace")
        if text.startswith(_SYNC_PREFIX):
            state = text[len(_SYNC_PREFIX) :].encode("utf-8")
            try:
                await mem.merge_all(state)
            except ValueError:
                # Malformed / garbled state (e.g. byzantine corruption): ignore.
                return

    async def on_stop(self, ctx: AgentContext) -> None:
        """Broadcast the winning value for the key for the convergence validator.

        Example::

            await agent.on_stop(ctx)
        """
        mem = ctx.plugins["memory"]
        winner = await mem.read(self._key)
        encoded = None if winner is None else base64.b64encode(winner).decode("ascii")
        record = json.dumps({"key": self._key, "value": encoded}, sort_keys=True)
        await ctx.broadcast(_FINAL_PREFIX.encode() + record.encode("utf-8"))


def memory_or_map_add_remove_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create N churn agents, each with its own memory replica.

    Every ``removers``-th agent (default every third) issues an observed-remove
    after its initial write. Values are derived deterministically from the
    agent index, and remover selection is index-based, so the scenario replays
    byte-identically under a fixed seed.

    Example::

        agents = memory_or_map_add_remove_factory(config, plugins)
    """
    task_config = config.task.config
    rounds = int(task_config.get("rounds", 20))
    key = str(task_config.get("key", "shared"))
    remover_stride = max(int(task_config.get("remover_stride", 3)), 2)
    count = max(config.agents.count, 8)

    memory_cls = plugins["memory"]
    agent_ids = [AgentId(f"writer-{i}") for i in range(count)]

    agents: dict[AgentId, StateMachineAgent] = {}
    overrides: dict[AgentId, dict[str, Any]] = {}
    for idx, aid in enumerate(agent_ids):
        agents[aid] = OrMapChurnAgent(
            aid,
            key=key,
            value=f"value-from-{aid}".encode(),
            rounds=rounds,
            remover=(idx % remover_stride == 0),
        )
        overrides[aid] = {"memory": memory_cls(str(aid))}

    plugins["_agent_plugins"] = overrides
    return agents
