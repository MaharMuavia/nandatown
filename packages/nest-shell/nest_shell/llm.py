# SPDX-License-Identifier: Apache-2.0
"""LLM backend abstraction for shell agents.

Example::

    backend = LiteLLMBackend(model="gpt-4o-mini")
    response = await backend.complete(messages)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol for LLM completion backends.

    Example::

        class MyBackend:
            async def complete(self, messages):
                return "I'll buy that for 50 credits."
    """

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Send messages to the LLM and return the assistant response text.

        Example::

            response = await backend.complete([{"role": "user", "content": "hello"}])
        """
        ...


class LiteLLMBackend:
    """LLM backend using litellm for multi-provider support.

    Example::

        backend = LiteLLMBackend(model="gpt-4o-mini", temperature=0.7)
        response = await backend.complete(messages)
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def complete(self, messages: list[dict[str, str]]) -> str:
        import litellm  # pyright: ignore[reportUnknownVariableType]

        response = await litellm.acompletion(  # pyright: ignore[reportUnknownMemberType]
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        choices: list[object] = getattr(response, "choices", [])
        if choices:
            msg: object = getattr(choices[0], "message", None)
            content: str = str(getattr(msg, "content", "") or "") if msg else ""
            return content
        return ""


class MockLLMBackend:
    """Deterministic mock backend for testing without API keys.

    Returns canned responses based on simple keyword matching.

    Example::

        backend = MockLLMBackend()
        response = await backend.complete([{"role": "user", "content": "buy request"}])
    """

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = responses or {}
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self._call_count += 1
        last_msg = messages[-1]["content"] if messages else ""

        for keyword, response in self._responses.items():
            if keyword in last_msg:
                return response

        if "buy:" in last_msg or "purchase" in last_msg.lower():
            return "ACTION: send\nTO: {sender}\nMESSAGE: sold:product:50"
        if "sold:" in last_msg:
            return "ACTION: send\nTO: {sender}\nMESSAGE: buy:product-next:60"
        if "reject:" in last_msg:
            return "ACTION: send\nTO: {sender}\nMESSAGE: buy:product-retry:70"

        return "ACTION: none"
