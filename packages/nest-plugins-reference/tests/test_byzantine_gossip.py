# SPDX-License-Identifier: Apache-2.0
"""Conformance + security tests for the byzantine_gossip registry plugin.

Task 1 only proved the plugin resolves via ``PluginRegistry`` and conforms
to the ``Registry`` Protocol. Task 2 adds the actual byzantine-resistance
primitive this plugin exists for: every card is signed at registration and
re-verified before being merged into a peer's view during gossip
propagation. That is a strictly stronger guarantee than a registration-only
signing scheme (prior art: ``#67``) -- ``#67``'s check runs once, at the
publisher's own registration call, so a compromised or malicious gossip
relay can still forge or impersonate cards while *propagating* them and no
downstream verifier ever re-checks them. This plugin re-verifies on every
hop, which is what Tasks 3-4 build byzantine-quarantine and eclipse
resistance on top of.
"""

from __future__ import annotations

import asyncio
import json

from nest_core.layers.registry import Registry
from nest_core.plugins import PluginRegistry
from nest_core.types import AgentCard, AgentId, Query, Signature
from nest_plugins_reference.identity.did_key import DidKeyIdentity
from nest_plugins_reference.registry.byzantine_gossip import (
    ByzantineGossipRegistry,
    canonical_card_bytes,
    canonical_write_bytes,
)
from nest_plugins_reference.registry.gossip import (
    GOSSIP_PREFIX,
    OP_PUSH,
    GossipNetwork,
    _WriteTag,  # pyright: ignore[reportPrivateUsage]
)


def test_resolves_and_conforms() -> None:
    cls = PluginRegistry().resolve("registry", "byzantine_gossip")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
    reg = cls(AgentId("a"), net, DidKeyIdentity(AgentId("a"), seed=b"s"))
    assert isinstance(reg, Registry)


class _StubContext:
    """Minimal ``AgentContext`` stand-in.

    The ``OP_PUSH`` branch of ``handle_gossip`` never calls back into the
    context (unlike ``OP_DIGEST``, which replies via ``ctx.send``), so a
    stub that fails loudly if that ever changes is enough for these tests.
    """

    async def send(self, to: AgentId, payload: bytes) -> None:  # pragma: no cover
        msg = "OP_PUSH handling must not need ctx.send"
        raise AssertionError(msg)


def _peered_identities(*agent_ids: str) -> dict[str, DidKeyIdentity]:
    """Build one ``DidKeyIdentity`` per agent id, each knowing every peer's public key."""
    idents = {aid: DidKeyIdentity(AgentId(aid), seed=f"seed-{aid}".encode()) for aid in agent_ids}
    for aid, ident in idents.items():
        for peer_id, peer_ident in idents.items():
            if peer_id != aid:
                ident.register_peer(AgentId(peer_id), peer_ident.public_key)
    return idents


def _push_payload(entries: list[tuple[AgentCard, _WriteTag, bool]]) -> bytes:
    """Hand-encode an ``OP_PUSH`` wire payload -- mirrors ``gossip.py``'s ``_encode_push``."""
    obj = [
        {
            "card": card.model_dump(mode="json"),
            "version": tag.version,
            "publisher": str(tag.publisher_id),
            "tombstone": tombstone,
        }
        for card, tag, tombstone in entries
    ]
    body = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return GOSSIP_PREFIX + OP_PUSH + body


# ---------------------------------------------------------------------------
# The core moat: forged/impersonated cards are rejected during propagation
# ---------------------------------------------------------------------------


def test_forged_card_rejected_but_honest_accepted() -> None:
    """Build an honest signed card from A; hand-forge a card claiming A's id.

    Feed both to ``reg_b.handle_gossip`` via one ``OP_PUSH`` payload: the
    honest card must land in ``reg_b``'s view, the forged one must not, and
    the rejection must be recorded as ``("a", "bad_signature")``.
    """
    idents = _peered_identities("a", "b", "m")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b"), AgentId("m")])
    reg_a = ByzantineGossipRegistry(AgentId("a"), net, idents["a"])
    reg_b = ByzantineGossipRegistry(AgentId("b"), net, idents["b"])

    asyncio.run(reg_a.register(AgentCard(agent_id=AgentId("a"), name="A", capabilities=["sell"])))
    [honest_card] = asyncio.run(reg_a.lookup(Query()))
    honest_tag = _WriteTag(version=1, publisher_id=AgentId("a"))

    # M forges a card claiming to be "a", signed with M's own key but the
    # signature metadata still *claims* signer "a" -- a bad/mutated
    # signature, not just a mismatched claim.
    forged_content = AgentCard(agent_id=AgentId("a"), name="EVIL")
    bogus_sig = idents["m"].sign(canonical_card_bytes(forged_content))
    forged_card = AgentCard(
        agent_id=AgentId("a"),
        name="EVIL",
        metadata={
            "sig": {
                "signer": "a",
                "value": bogus_sig.value.hex(),
                "algorithm": bogus_sig.algorithm,
            }
        },
    )
    forged_tag = _WriteTag(version=1, publisher_id=AgentId("a"))

    payload = _push_payload(
        [
            (honest_card, honest_tag, False),
            (forged_card, forged_tag, False),
        ]
    )

    result = asyncio.run(reg_b.handle_gossip(AgentId("a"), payload, _StubContext()))  # type: ignore[arg-type]

    assert result is True
    snap = reg_b.view_snapshot()
    assert AgentId("a") in snap
    [seen_card] = asyncio.run(reg_b.lookup(Query()))
    assert seen_card.name == "A"  # the forged "EVIL" card never landed
    assert reg_b.rejections == [(AgentId("a"), "bad_signature")]


def test_missing_signature_rejected() -> None:
    idents = _peered_identities("a", "b")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
    reg_b = ByzantineGossipRegistry(AgentId("b"), net, idents["b"])

    unsigned_card = AgentCard(agent_id=AgentId("a"), name="A")
    tag = _WriteTag(version=1, publisher_id=AgentId("a"))
    payload = _push_payload([(unsigned_card, tag, False)])

    asyncio.run(reg_b.handle_gossip(AgentId("a"), payload, _StubContext()))  # type: ignore[arg-type]

    assert AgentId("a") not in reg_b.view_snapshot()
    assert reg_b.rejections == [(AgentId("a"), "missing_signature")]


def test_signer_mismatch_rejected() -> None:
    """M signs honestly with its own key but attaches the card to A's identity."""
    idents = _peered_identities("a", "b", "m")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b"), AgentId("m")])
    reg_b = ByzantineGossipRegistry(AgentId("b"), net, idents["b"])

    content = AgentCard(agent_id=AgentId("a"), name="A")
    m_sig = idents["m"].sign(canonical_card_bytes(content))
    impersonating_card = AgentCard(
        agent_id=AgentId("a"),
        name="A",
        metadata={"sig": {"signer": "m", "value": m_sig.value.hex(), "algorithm": m_sig.algorithm}},
    )
    tag = _WriteTag(version=1, publisher_id=AgentId("a"))
    payload = _push_payload([(impersonating_card, tag, False)])

    asyncio.run(reg_b.handle_gossip(AgentId("a"), payload, _StubContext()))  # type: ignore[arg-type]

    assert AgentId("a") not in reg_b.view_snapshot()
    assert reg_b.rejections == [(AgentId("a"), "signer_mismatch")]


# ---------------------------------------------------------------------------
# The write-binding moat: content-only signing is not enough (replay/un-delete)
# ---------------------------------------------------------------------------


def test_replay_with_inflated_version_rejected() -> None:
    """A relay with NO private key replays a genuinely-signed card under a forged higher version.

    Content-only signing (sign ``agent_id``/``name``/``capabilities``/
    ``endpoint`` alone) would let this through: the card's content
    signature still checks out, and the wire-supplied ``_WriteTag`` is
    merged verbatim by last-writer-wins, letting a relay with no signing
    key inflate a publisher's version and block/override their real future
    writes. Binding the signature to ``(content, version, tombstone)``
    closes it.
    """
    idents = _peered_identities("a", "b")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
    reg_a = ByzantineGossipRegistry(AgentId("a"), net, idents["a"])
    reg_b = ByzantineGossipRegistry(AgentId("b"), net, idents["b"])

    asyncio.run(reg_a.register(AgentCard(agent_id=AgentId("a"), name="A", capabilities=["sell"])))
    [honest_card] = asyncio.run(reg_a.lookup(Query()))

    # M (no private key) replays A's honestly-signed card, forging a much
    # higher version so it wins last-writer-wins against A's real writes.
    forged_tag = _WriteTag(version=999, publisher_id=AgentId("a"))
    payload = _push_payload([(honest_card, forged_tag, False)])

    result = asyncio.run(reg_b.handle_gossip(AgentId("a"), payload, _StubContext()))  # type: ignore[arg-type]

    assert result is True
    assert AgentId("a") not in reg_b.view_snapshot()
    assert reg_b.rejections == [(AgentId("a"), "bad_signature")]


def test_tombstone_flip_rejected() -> None:
    """A relay flips an honest deregister's tombstone bit back to False -- an "un-delete".

    A honestly issued this deregister; its ``metadata["sig"]`` was computed
    over ``canonical_write_bytes(card, version, tombstone=True)``. A relay
    (no private key) forwards the same card+version but flips ``tombstone``
    to ``False`` on the wire, trying to resurrect A in B's view. That must
    fail verification and be dropped, not silently un-delete A.
    """
    idents = _peered_identities("a", "b")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
    reg_a = ByzantineGossipRegistry(AgentId("a"), net, idents["a"])
    reg_b = ByzantineGossipRegistry(AgentId("b"), net, idents["b"])

    asyncio.run(reg_a.register(AgentCard(agent_id=AgentId("a"), name="A", capabilities=["sell"])))
    asyncio.run(reg_a.deregister(AgentId("a")))
    tombstoned = reg_a._view[AgentId("a")]  # pyright: ignore[reportPrivateUsage]
    assert tombstoned.tombstone is True

    payload = _push_payload([(tombstoned.card, tombstoned.tag, False)])

    result = asyncio.run(reg_b.handle_gossip(AgentId("a"), payload, _StubContext()))  # type: ignore[arg-type]

    assert result is True
    assert AgentId("a") not in reg_b.view_snapshot()  # un-delete did NOT land
    assert reg_b.rejections == [(AgentId("a"), "bad_signature")]


def test_honest_card_mutated_in_transit_rejected() -> None:
    """A relay mutates a capability on an honestly-signed card after signing.

    Covers the module docstring's "mutated in transit" claim, which had no
    dedicated test previously -- ``test_forged_card_rejected_but_honest_accepted``
    only exercises a hand-forged card with a bad signature, not a mutation
    of an otherwise-genuine signed card.
    """
    idents = _peered_identities("a", "b")
    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
    reg_a = ByzantineGossipRegistry(AgentId("a"), net, idents["a"])
    reg_b = ByzantineGossipRegistry(AgentId("b"), net, idents["b"])

    asyncio.run(reg_a.register(AgentCard(agent_id=AgentId("a"), name="A", capabilities=["sell"])))
    [honest_card] = asyncio.run(reg_a.lookup(Query()))
    honest_tag = _WriteTag(version=1, publisher_id=AgentId("a"))

    mutated_card = honest_card.model_copy(update={"capabilities": ["buy"]})
    payload = _push_payload([(mutated_card, honest_tag, False)])

    asyncio.run(reg_b.handle_gossip(AgentId("a"), payload, _StubContext()))  # type: ignore[arg-type]

    assert AgentId("a") not in reg_b.view_snapshot()
    assert reg_b.rejections == [(AgentId("a"), "bad_signature")]


# ---------------------------------------------------------------------------
# canonical_card_bytes + register signing
# ---------------------------------------------------------------------------


def test_canonical_card_bytes_excludes_metadata_and_sorts_capabilities() -> None:
    card1 = AgentCard(agent_id=AgentId("a"), name="A", capabilities=["y", "x"], metadata={"n": 1})
    card2 = AgentCard(agent_id=AgentId("a"), name="A", capabilities=["x", "y"], metadata={"n": 2})
    assert canonical_card_bytes(card1) == canonical_card_bytes(card2)


def test_canonical_card_bytes_differs_on_content_change() -> None:
    card1 = AgentCard(agent_id=AgentId("a"), name="A")
    card2 = AgentCard(agent_id=AgentId("a"), name="B")
    assert canonical_card_bytes(card1) != canonical_card_bytes(card2)


def test_register_signs_card_with_verifiable_signature() -> None:
    idents = _peered_identities("a")
    net = GossipNetwork(agent_ids=[AgentId("a")])
    reg = ByzantineGossipRegistry(AgentId("a"), net, idents["a"])

    asyncio.run(reg.register(AgentCard(agent_id=AgentId("a"), name="A")))
    [card] = asyncio.run(reg.lookup(Query()))
    snap = reg.view_snapshot()
    version, _publisher, tombstone = snap[AgentId("a")]

    sig_meta = card.metadata["sig"]
    assert sig_meta["signer"] == "a"
    sig = Signature(
        signer=AgentId(sig_meta["signer"]),
        value=bytes.fromhex(sig_meta["value"]),
        algorithm=sig_meta["algorithm"],
    )
    # The signature binds the whole write (content + version + tombstone),
    # not just canonical_card_bytes -- see test_replay_with_inflated_version_rejected
    # and test_tombstone_flip_rejected for why that matters.
    assert idents["a"].verify(canonical_write_bytes(card, version, tombstone), sig, AgentId("a"))
