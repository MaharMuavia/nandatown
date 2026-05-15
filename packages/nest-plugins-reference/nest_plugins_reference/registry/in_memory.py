# SPDX-License-Identifier: Apache-2.0
"""In-memory registry plugin — local dictionary-based agent discovery.

Example::

    registry = InMemoryRegistry()
    await registry.register(card)
    results = await registry.lookup(Query(capabilities=["sell"]))
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from nest_core.types import AgentCard, AgentId, Query


class InMemoryRegistry:
    """Dictionary-backed agent registry.

    Example::

        reg = InMemoryRegistry()
        await reg.register(AgentCard(agent_id=AgentId("a1"), name="Agent1"))
    """

    def __init__(self) -> None:
        self._cards: dict[AgentId, AgentCard] = {}
        self._subscribers: list[asyncio.Queue[AgentCard]] = []

    async def register(self, card: AgentCard) -> None:
        """Register an agent card.

        Example::

            await reg.register(card)
        """
        self._cards[card.agent_id] = card
        for q in self._subscribers:
            await q.put(card)

    async def lookup(self, query: Query) -> list[AgentCard]:
        """Look up agents matching a query.

        Example::

            results = await reg.lookup(Query(capabilities=["sell"]))
        """
        results: list[AgentCard] = []
        for card in self._cards.values():
            if self._matches(card, query):
                results.append(card)
        return results

    async def subscribe(self, query: Query) -> AsyncIterator[AgentCard]:
        """Subscribe to new agent registrations matching a query.

        Example::

            async for card in reg.subscribe(query):
                print(card.name)
        """
        q: asyncio.Queue[AgentCard] = asyncio.Queue()
        self._subscribers.append(q)
        try:
            while True:
                card = await q.get()
                if self._matches(card, query):
                    yield card
        finally:
            self._subscribers.remove(q)

    async def deregister(self, agent: AgentId) -> None:
        """Remove an agent from the registry.

        Example::

            await reg.deregister(AgentId("a1"))
        """
        self._cards.pop(agent, None)

    @staticmethod
    def _matches(card: AgentCard, query: Query) -> bool:
        if query.capabilities and not all(cap in card.capabilities for cap in query.capabilities):
            return False
        return not (query.name_pattern and query.name_pattern not in card.name)
