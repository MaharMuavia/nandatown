# SPDX-License-Identifier: Apache-2.0
"""Smoke tests: verify that nest-sdk re-exports all interfaces and types."""


def test_nest_sdk_imports() -> None:
    """Importing nest_sdk should succeed and expose a version string."""
    import nest_sdk

    assert nest_sdk.__version__ == "0.1.0"


def test_sdk_exports_all_layers() -> None:
    """All 12 layer interfaces are importable from nest_sdk."""
    from nest_sdk import (
        Auth,
        CommsProtocol,
        Coordination,
        DataFacts,
        Identity,
        Memory,
        Negotiation,
        Payments,
        Privacy,
        Registry,
        Transport,
        Trust,
    )

    layers = [
        Auth,
        CommsProtocol,
        Coordination,
        DataFacts,
        Identity,
        Memory,
        Negotiation,
        Payments,
        Privacy,
        Registry,
        Transport,
        Trust,
    ]
    assert len(layers) == 12


def test_sdk_exports_core_types() -> None:
    """Core types are importable from nest_sdk."""
    from nest_sdk import (
        AgentCard,
        AgentId,
        Message,
        Money,
        PaymentRef,
        Query,
        Quote,
        Receipt,
        Task,
        Token,
    )

    agent = AgentId("test")
    assert agent == "test"
    assert Money(amount=10).currency == "credits"
    # Just verify they're importable; not None
    assert AgentCard is not None
    assert Message is not None
    assert PaymentRef is not None
    assert Query is not None
    assert Quote is not None
    assert Receipt is not None
    assert Task is not None
    assert Token is not None
