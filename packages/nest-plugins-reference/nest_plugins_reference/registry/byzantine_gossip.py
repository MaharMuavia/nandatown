# SPDX-License-Identifier: Apache-2.0
"""Byzantine-resistant gossip registry plugin — scaffold (Task 1 of the series).

``nest_plugins_reference.registry.gossip.GossipRegistry`` gives us
eventually-consistent discovery under honest-but-partitioned failures: every
agent gossips its local view over the transport, and the simulator's
partition logic naturally blocks cross-partition propagation.  It assumes,
however, that every participant plays by the rules — same publisher never
signs two conflicting write tags at the same version, no agent forges
another agent's cards, and no agent tries to starve a victim's view by only
ever gossiping with a captured subset of peers.

This plugin is the byzantine-hardened counterpart.  Task 1 scaffolded the
class and proved it satisfies ``nest_core.layers.registry.Registry`` — the
view/merge/wire-format machinery is a deliberate copy of
``GossipRegistry``'s structure, while the network-wide primitives
(``GossipNetwork``, ``GOSSIP_PREFIX``, ``OP_DIGEST``, ``OP_PUSH``,
``_WriteTag``) are imported and reused as-is so both plugins share one
notion of "peer set" and "write ordering."

Task 2 (this task) adds the core moat: **every card is signed at
registration and re-verified on every gossip hop, not just once at
registration time.**  Prior art for signed cards exists (``#67``:
registration-only signing — a publisher signs its card when it first
registers).  That is necessary but not sufficient: ``#67``'s check runs
exactly once, at the source, and nothing downstream re-checks a card as it
hops through the gossip mesh.  A compromised or malicious relay agent can
forge a card claiming another agent's identity (impersonation) or mutate a
previously-honest card's bytes in transit (forgery) and any peer that only
trusts "it must be fine, gossip is honest-but-partitioned" will merge it
straight into its view.  This plugin closes that gap: ``handle_gossip``'s
``OP_PUSH`` branch verifies ``identity.verify(canonical_write_bytes(card,
tag.version, tombstone), sig, card.agent_id)`` for every incoming card and
drops (never ``_apply``s) anything that is unsigned, claims a signer other
than its own ``agent_id`` (impersonation), or fails cryptographic
verification (forgery/mutation) — recording ``(agent_id, reason)`` in
``self.rejections`` for judge/validator legibility with reason codes
``missing_signature``, ``signer_mismatch``, and ``bad_signature``, mirroring
``#67``'s taxonomy.

Critically, the signature binds not just the card's *content* but also its
**write tag (version) and tombstone bit**.  Content-only signing (sign
``agent_id``/``name``/``capabilities``/``endpoint``, nothing else) leaves a
gap of its own: the wire-supplied ``_WriteTag`` and ``tombstone`` in an
``OP_PUSH`` entry are merged verbatim once the *card* checks out, so a relay
with **no private key at all** can replay a genuinely-signed card under a
forged, inflated ``version`` (winning last-writer-wins against the
publisher's real future writes, i.e. blocking updates) or with a flipped
``tombstone`` bit (resurrecting a deregistered agent — an "un-delete" — or
silently deleting a live one).  Binding the signature to
``(content, version, tombstone)`` closes that: a replayed card with a
tampered tag or tombstone now fails verification and is dropped as
``bad_signature``, exactly like a forged/mutated card.

Note what this still does **not** defend against: a publisher who signs two
*different*, both validly-signed cards at the same version (equivocation).
Signature verification alone cannot detect that — both cards check out.
Task 3 adds the witness/quarantine mechanism for that. Task 4 adds
eclipse-resistant peer sampling + adversarial scenarios and validators.

Example::

    from nest_plugins_reference.identity.did_key import DidKeyIdentity
    from nest_plugins_reference.registry.gossip import GossipNetwork

    net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
    identity = DidKeyIdentity(AgentId("a"), seed=b"s")
    reg = ByzantineGossipRegistry(AgentId("a"), net, identity)
    await reg.register(AgentCard(agent_id=AgentId("a"), name="A"))
"""

from __future__ import annotations

import json
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nest_core.types import AgentCard, AgentId, Query, Signature

from nest_plugins_reference.registry.gossip import (
    GOSSIP_PREFIX,
    OP_DIGEST,
    OP_PUSH,
    GossipNetwork,
    _WriteTag,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from nest_core.layers.identity import Identity
    from nest_core.sim.agent import AgentContext


REASON_MISSING_SIGNATURE = "missing_signature"
"""Rejection reason: card carries no ``metadata["sig"]`` at all.

Example::

    reg.rejections.append((AgentId("a"), REASON_MISSING_SIGNATURE))
"""

REASON_SIGNER_MISMATCH = "signer_mismatch"
"""Rejection reason: ``sig.signer`` names a different agent than ``card.agent_id``
(impersonation — the card claims someone else's identity).

Example::

    reg.rejections.append((AgentId("a"), REASON_SIGNER_MISMATCH))
"""

REASON_BAD_SIGNATURE = "bad_signature"
"""Rejection reason: signature is present and claims the right signer, but
fails cryptographic verification (forgery, or a mutated-in-transit card).

Example::

    reg.rejections.append((AgentId("a"), REASON_BAD_SIGNATURE))
"""


@dataclass
class _Versioned:
    """A stored card plus its write tag and a tombstone bit.

    Local copy of ``GossipRegistry``'s ``_Versioned`` structure — kept
    separate (not imported) so later tasks can extend it with a signature
    field without touching the plain gossip plugin.

    Example::

        v = _Versioned(card=card, tag=_WriteTag(1, AgentId("a")), tombstone=False)
    """

    card: AgentCard
    tag: _WriteTag
    tombstone: bool = False


class ByzantineGossipRegistry:
    """Per-agent gossip registry with signed, re-verified-on-every-hop cards.

    Satisfies ``nest_core.layers.registry.Registry``: ``register``,
    ``lookup``, ``subscribe``, ``deregister``.  Delegates to the same
    local-view / last-writer-wins merge logic as
    ``nest_plugins_reference.registry.gossip.GossipRegistry``, but
    ``register``/``deregister`` sign every write via the injected
    ``Identity`` — content plus version plus tombstone — and
    ``handle_gossip`` verifies that signature (fresh, against
    ``card.agent_id`` and the wire-supplied version/tombstone) before
    merging an inbound card — see the module docstring for why
    registration-only, content-only signing (``#67``) is not enough.
    Equivocation detection and eclipse resistance land in Tasks 3-4.

    Driver agents call ``gossip_round(ctx)`` on a schedule and forward
    inbound ``GOSSIP_PREFIX``-marked payloads to
    ``handle_gossip(sender, payload, ctx)``, exactly as with
    ``GossipRegistry``.

    Example::

        net = GossipNetwork(agent_ids=[AgentId("a"), AgentId("b")])
        identity = DidKeyIdentity(AgentId("a"), seed=b"s")
        reg = ByzantineGossipRegistry(AgentId("a"), net, identity)
        await reg.register(AgentCard(agent_id=AgentId("a"), name="A"))
        cards = await reg.lookup(Query())  # returns local view only
    """

    def __init__(self, agent_id: AgentId, network: GossipNetwork, identity: Identity) -> None:
        self._agent_id = agent_id
        self._network = network
        self._identity = identity
        self._view: dict[AgentId, _Versioned] = {}
        self.rejections: list[tuple[AgentId, str]] = []
        """Ledger of cards dropped during gossip merge: ``(agent_id, reason)``
        pairs, in the order they were rejected.  ``reason`` is one of
        ``REASON_MISSING_SIGNATURE``, ``REASON_SIGNER_MISMATCH``,
        ``REASON_BAD_SIGNATURE``.  Exposed for validators/tests, not part of
        the ``Registry`` Protocol.

        Example::

            assert reg.rejections == [(AgentId("a"), "bad_signature")]
        """

    # ------------------------------------------------------------------
    # Registry protocol
    # ------------------------------------------------------------------

    async def register(self, card: AgentCard) -> None:
        """Register ``card`` locally, signed; gossip propagates it on the next round.

        Allocates this write's version first, then signs
        ``canonical_write_bytes(card, version, tombstone=False)`` with this
        agent's ``Identity`` and stores the signature in
        ``card.metadata["sig"]`` (a fresh ``AgentCard`` — the caller's
        instance is not mutated) so every peer that later receives this
        card via gossip can verify it came from ``card.agent_id``, was not
        altered in transit, and carries the version/tombstone the publisher
        actually wrote — not one a relay forged on the wire.

        Example::

            await reg.register(AgentCard(agent_id=AgentId("a"), name="A"))
        """
        tag = _WriteTag(
            version=self._network.next_version(card.agent_id),
            publisher_id=card.agent_id,
        )
        signed_card = _sign_card(card, tag.version, tombstone=False, identity=self._identity)
        self._apply(signed_card, tag, tombstone=False)

    async def lookup(self, query: Query) -> list[AgentCard]:
        """Return cards matching ``query`` from the **local** view.

        Example::

            cards = await reg.lookup(Query(capabilities=["sell"]))
        """
        return [v.card for v in self._view.values() if not v.tombstone and _matches(v.card, query)]

    async def subscribe(self, query: Query) -> AsyncIterator[AgentCard]:
        """Yield cards matching ``query`` from the local view, then end.

        Example::

            async for card in reg.subscribe(query):
                print(card.name)
        """
        for card in await self.lookup(query):
            yield card

    async def deregister(self, agent: AgentId) -> None:
        """Tombstone ``agent`` locally; gossip propagates the tombstone.

        Allocates the new (tombstoning) version and re-signs
        ``canonical_write_bytes(existing_card, version, tombstone=True)`` so
        the deletion itself is authenticated — a relay cannot flip
        ``tombstone`` back to ``False`` on the wire and "un-delete" the
        agent, since that would no longer match the signed write.

        Example::

            await reg.deregister(AgentId("a"))
        """
        existing = self._view.get(agent)
        if existing is None:
            return
        tag = _WriteTag(
            version=self._network.next_version(agent),
            publisher_id=agent,
        )
        signed_card = _sign_card(
            existing.card, tag.version, tombstone=True, identity=self._identity
        )
        self._apply(signed_card, tag, tombstone=True)

    # ------------------------------------------------------------------
    # Gossip mechanics
    # ------------------------------------------------------------------

    async def gossip_round(self, ctx: AgentContext) -> None:
        """Run one round of push-pull anti-entropy.

        Same peer-sampling strategy as ``GossipRegistry.gossip_round`` for
        now; Task 4 replaces the uniform sample with an eclipse-resistant
        one.

        Example::

            await reg.gossip_round(ctx)
        """
        peers = self._network.peers_of(self._agent_id)
        if not peers:
            return
        fanout = min(self._network.fanout, len(peers))
        chosen = _sample_without_replacement(ctx.rng, peers, fanout)
        digest = self._digest()
        payload = GOSSIP_PREFIX + OP_DIGEST + _encode(digest)
        for peer in chosen:
            await ctx.send(peer, payload)

    async def handle_gossip(self, sender: AgentId, payload: bytes, ctx: AgentContext) -> bool:
        """Process a gossip message from ``sender``.

        Returns ``True`` if the payload was a gossip message (and was
        consumed), ``False`` otherwise.  ``OP_PUSH`` entries are verified
        before merge against ``canonical_write_bytes(card, tag.version,
        tombstone)`` — binding the signature to the wire-supplied version
        and tombstone bit, not just the card content — so unsigned,
        impersonating, forged/mutated, replayed-with-a-forged-version, or
        tombstone-flipped entries are all dropped and recorded in
        ``self.rejections`` instead of being applied.  Equivocation
        detection (two differently-signed cards from the same publisher at
        the same version — both individually valid) is not caught here; see
        Task 3.

        Example::

            handled = await reg.handle_gossip(sender, payload, ctx)
        """
        if not payload.startswith(GOSSIP_PREFIX):
            return False
        body = payload[len(GOSSIP_PREFIX) :]
        if not body:
            return True
        op, rest = body[:1], body[1:]
        if op == OP_DIGEST:
            sender_digest = _decode_digest(rest)
            missing = self._compute_missing(sender_digest)
            if missing:
                push_payload = GOSSIP_PREFIX + OP_PUSH + _encode_push(missing)
                await ctx.send(sender, push_payload)
            return True
        if op == OP_PUSH:
            for card, tag, tombstone in _decode_push(rest):
                reason = _verify_card(card, tag.version, tombstone, self._identity)
                if reason is not None:
                    self.rejections.append((card.agent_id, reason))
                    continue
                self._apply(card, tag, tombstone=tombstone)
            return True
        return True  # Unknown op: consume silently so junk doesn't escape.

    # ------------------------------------------------------------------
    # Inspection (used by validators + tests)
    # ------------------------------------------------------------------

    def view_snapshot(self) -> dict[AgentId, tuple[int, AgentId, bool]]:
        """Return a deterministic snapshot of the local view.

        Same shape as ``GossipRegistry.view_snapshot`` so
        ``check_converged`` composes across both plugins.

        Example::

            snap = reg.view_snapshot()
        """
        return {
            aid: (v.tag.version, v.tag.publisher_id, v.tombstone)
            for aid, v in sorted(self._view.items())
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply(self, card: AgentCard, tag: _WriteTag, *, tombstone: bool) -> None:
        existing = self._view.get(card.agent_id)
        if existing is not None and existing.tag >= tag:
            return
        self._view[card.agent_id] = _Versioned(card=card, tag=tag, tombstone=tombstone)

    def _digest(self) -> dict[AgentId, _WriteTag]:
        return {aid: v.tag for aid, v in self._view.items()}

    def _compute_missing(
        self, sender_digest: dict[AgentId, _WriteTag]
    ) -> list[tuple[AgentCard, _WriteTag, bool]]:
        out: list[tuple[AgentCard, _WriteTag, bool]] = []
        for aid, versioned in self._view.items():
            sender_tag = sender_digest.get(aid)
            if sender_tag is None or sender_tag < versioned.tag:
                out.append((versioned.card, versioned.tag, versioned.tombstone))
        return out


# ---------------------------------------------------------------------------
# Signing + verification
# ---------------------------------------------------------------------------


def canonical_card_bytes(card: AgentCard) -> bytes:
    """Canonical content-only bytes of ``card`` for content comparisons.

    Covers ``agent_id``, ``name``, ``capabilities`` (sorted so declaration
    order is not semantically meaningful), and ``endpoint``. Deliberately
    **excludes** ``metadata`` — that is where the signature itself lives
    (``metadata["sig"]``), so including it would make the signed payload
    depend on the signature, which is circular. Any other data a publisher
    wants integrity-protected belongs in one of the covered fields, not in
    ``metadata``. Structural analogue of ``cid_facts.content_hash``, which
    canonicalizes a ``DatasetMetadata``'s content fields the same way.

    **Not** what gets signed — signing binds the full write, including
    ``version``/``tombstone``; see ``canonical_write_bytes``. This helper
    remains for content-only comparisons (e.g. detecting whether two cards
    have identical content regardless of write metadata).

    Example::

        same_content = canonical_card_bytes(card1) == canonical_card_bytes(card2)
    """
    content: dict[str, object] = {
        "agent_id": str(card.agent_id),
        "name": card.name,
        "capabilities": sorted(card.capabilities),
        "endpoint": card.endpoint,
    }
    return json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_write_bytes(card: AgentCard, version: int, tombstone: bool) -> bytes:
    """Canonical bytes of a **write** — ``card`` content plus ``version`` and ``tombstone``.

    This is what gets signed and verified, not ``canonical_card_bytes``
    alone. Binding the signature to the write tag and tombstone bit (in
    addition to content) closes a replay hole: without it, a relay holding
    no private key can take a genuinely-signed card and re-broadcast it
    under a forged, inflated ``version`` (winning last-writer-wins against
    the publisher's real future writes) or with a flipped ``tombstone`` bit
    (resurrecting a deregistered agent, or deleting a live one) — the card's
    *content* signature still checks out because content-only signing never
    covered the tag or tombstone in the first place. Still excludes
    ``metadata`` for the same circularity reason as ``canonical_card_bytes``.

    Example::

        sig = identity.sign(canonical_write_bytes(card, version=3, tombstone=False))
    """
    content: dict[str, object] = {
        "agent_id": str(card.agent_id),
        "name": card.name,
        "capabilities": sorted(card.capabilities),
        "endpoint": card.endpoint,
        "version": version,
        "tombstone": tombstone,
    }
    return json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_card(card: AgentCard, version: int, tombstone: bool, *, identity: Identity) -> AgentCard:
    """Return a copy of ``card`` with a fresh ``metadata["sig"]`` from ``identity``.

    Signs ``canonical_write_bytes(card, version, tombstone)`` — the whole
    write, not just the content — so a relay cannot replay this card under a
    different version or tombstone state and still pass verification.

    The signature ``value`` is stored hex-encoded (not raw ``bytes``):
    ``AgentCard.metadata`` is a plain ``dict[str, Any]``, and round-tripping
    raw ``bytes`` through ``AgentCard.model_dump(mode="json")`` /
    ``model_validate`` inside an ``Any``-typed field is lossy (pydantic has
    no field-type hint telling it to treat that value as bytes on the way
    back in). Hex keeps the wire payload plain JSON end to end.
    """
    sig = identity.sign(canonical_write_bytes(card, version, tombstone))
    metadata = dict(card.metadata)
    metadata["sig"] = {
        "signer": str(sig.signer),
        "value": sig.value.hex(),
        "algorithm": sig.algorithm,
    }
    return card.model_copy(update={"metadata": metadata})


def _verify_card(card: AgentCard, version: int, tombstone: bool, identity: Identity) -> str | None:
    """Verify ``card``'s embedded signature against ``(version, tombstone)``.

    Returns a rejection reason, or ``None`` if the signature is valid.

    Reason codes mirror ``#67``'s taxonomy: ``REASON_MISSING_SIGNATURE`` (no
    ``metadata["sig"]``), ``REASON_SIGNER_MISMATCH`` (``sig.signer`` names a
    different agent than ``card.agent_id`` — impersonation), or
    ``REASON_BAD_SIGNATURE`` (present, correctly-claimed signer, but fails
    cryptographic verification — forgery, in-transit mutation, or a replay
    under a forged ``version``/``tombstone`` that the publisher never
    actually signed).
    """
    raw_sig_meta = card.metadata.get("sig")
    if not isinstance(raw_sig_meta, dict):
        return REASON_MISSING_SIGNATURE
    sig_meta = cast("dict[str, object]", raw_sig_meta)
    signer_raw = sig_meta.get("signer")
    value_raw = sig_meta.get("value")
    if signer_raw is None or value_raw is None:
        return REASON_MISSING_SIGNATURE
    signer = AgentId(str(signer_raw))
    if signer != card.agent_id:
        return REASON_SIGNER_MISMATCH
    try:
        value = bytes.fromhex(str(value_raw))
    except ValueError:
        return REASON_BAD_SIGNATURE
    algorithm = str(sig_meta.get("algorithm", "ed25519"))
    sig = Signature(signer=signer, value=value, algorithm=algorithm)
    if not identity.verify(canonical_write_bytes(card, version, tombstone), sig, card.agent_id):
        return REASON_BAD_SIGNATURE
    return None


# ---------------------------------------------------------------------------
# Helpers (module-private; structural copy of gossip.py's wire codec)
# ---------------------------------------------------------------------------


def _matches(card: AgentCard, query: Query) -> bool:
    if query.capabilities and not all(cap in card.capabilities for cap in query.capabilities):
        return False
    return not (query.name_pattern and query.name_pattern not in card.name)


def _sample_without_replacement(rng: random.Random, peers: list[AgentId], k: int) -> list[AgentId]:
    """Deterministic sample of ``k`` peers from ``peers`` using ``rng``.

    Structural copy of ``gossip.py``'s Fisher-Yates sampler.  Task 4
    replaces this with the eclipse-resistant sampler.
    """
    pool = list(peers)
    out: list[AgentId] = []
    for _ in range(k):
        j = rng.randint(0, len(pool) - 1)
        out.append(pool[j])
        pool[j] = pool[-1]
        pool.pop()
    return out


def _encode(digest: dict[AgentId, _WriteTag]) -> bytes:
    obj = {str(aid): [t.version, str(t.publisher_id)] for aid, t in digest.items()}
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _decode_digest(raw: bytes) -> dict[AgentId, _WriteTag]:
    obj = json.loads(raw.decode())
    return {
        AgentId(aid): _WriteTag(version=int(v), publisher_id=AgentId(pid))
        for aid, (v, pid) in obj.items()
    }


def _encode_push(items: list[tuple[AgentCard, _WriteTag, bool]]) -> bytes:
    obj = [
        {
            "card": card.model_dump(mode="json"),
            "version": tag.version,
            "publisher": str(tag.publisher_id),
            "tombstone": tombstone,
        }
        for card, tag, tombstone in items
    ]
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _decode_push(raw: bytes) -> list[tuple[AgentCard, _WriteTag, bool]]:
    obj: list[dict[str, object]] = json.loads(raw.decode())
    out: list[tuple[AgentCard, _WriteTag, bool]] = []
    for entry in obj:
        card = AgentCard.model_validate(entry["card"])
        tag = _WriteTag(
            version=int(entry["version"]),  # type: ignore[arg-type]
            publisher_id=AgentId(str(entry["publisher"])),
        )
        out.append((card, tag, bool(entry["tombstone"])))
    return out
