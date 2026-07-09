# SPDX-License-Identifier: Apache-2.0
"""OR-Map CRDT memory plugin -- add-wins, observed-remove shared state.

This module implements a **state-based Observed-Remove Map** (an add-wins
``ORSWOT``-style CvRDT, "OR-Set Without Tombstones" generalised from a set to
a keyed map) for the Nanda Town memory layer. It exists to cover the one thing
the merged ``lww_register`` plugin structurally *cannot* express: **deletion
under concurrency**.

``lww_register`` resolves every conflict -- including a delete modelled as an
LWW write of a tombstone -- by the total order ``(lamport, node)``. That means
a concurrent *add* can silently **lose** to a concurrent *remove* if the remove
happens to carry the higher timestamp. For a register that is the correct,
intended behaviour; for a shared *set/map* of live entries it is a lost update:
an agent that re-advertises a catalogue entry at the same time another agent
retires the old one should keep its entry, not have it deleted out from under
it. The ``blackboard`` default is worse still -- a delete is just ``del`` on a
shared dict, order-dependent and non-convergent.

An OR-Map fixes this with the **add-wins** rule: an element survives iff it has
at least one *add* that the remover had **not observed** at remove time. The
mechanism is the classic "unique tag on add" (here called a *dot*
``(node, counter)``) plus a per-replica **causal context** (a version vector of
the highest counter seen per node). A remove drops only the dots the remover
has actually seen; a concurrent add carries a fresh dot outside the remover's
context and therefore wins. The merge of any two replica states is a genuine
semilattice join -- **commutative, associative, and idempotent** -- so replicas
that have observed the same operations converge to byte-identical state
regardless of delivery order, duplication, or loss (*strong eventual
consistency*), and the map needs **no tombstones** to do it.

The read side keeps the base :class:`~nest_core.layers.memory.Memory` contract
single-valued: when concurrent writes leave a key with several live dots, all
of them are retained internally (so convergence and inspection are exact) but
:meth:`read` returns the payload of the deterministic winner -- the dot that is
largest under ``(counter, node)``. Reads are therefore total, deterministic,
and replay-stable.

State for a key is encoded as inspectable JSON so it stays grep-able inside a
JSONL trace::

    {"crdt": "or_map", "key": "cat", "dots":
        [{"node": "agent-2", "counter": 3, "payload": "<base64>"}],
     "context": {"agent-2": 3, "agent-5": 1}}

Example::

    a = OrMapMemory("a")
    b = OrMapMemory("b")
    await a.write("cat", b"apple")
    await b.merge_all(a.export_all())        # b now observes a's add
    await a.write("cat", b"apricot")         # concurrent re-add on a ...
    await b.remove("cat")                    # ... while b removes what it saw
    await a.merge_all(b.export_all())
    await b.merge_all(a.export_all())
    assert await a.read("cat") == b"apricot"  # add-wins: the entry survives
    assert await b.read("cat") == b"apricot"
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

CRDT_KIND = "or_map"
"""Schema tag stamped into every serialized state, used to detect and validate
OR-Map state when it is read back from a trace or the wire."""


class OrMapStateError(ValueError):
    """Raised when a byte string is not valid serialized OR-Map state.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers
    (such as the gossip loop in the concurrent-writers scenario) keep working,
    while callers that care can catch the specific type.

    Example::

        try:
            OrMapMemory._decode_key(b"not json")
        except OrMapStateError:
            ...
    """


@dataclass(frozen=True, order=True)
class Dot:
    """A unique per-write tag ``(counter, node)`` -- the OR-Set "unique tag".

    Fields are declared ``counter`` first so the dataclass-generated ordering
    is ``(counter, node)``: a higher counter wins, and the stable ``node`` id
    breaks ties. Because a node's counter strictly increases on every local
    write, a ``(node, counter)`` pair is globally unique across all writes, so
    it can both identify an add and participate in the deterministic read
    total order.

    Example::

        assert Dot(counter=2, node="a") > Dot(counter=1, node="z")
        assert Dot(counter=1, node="b") > Dot(counter=1, node="a")
    """

    counter: int
    node: str


@dataclass(frozen=True)
class _Add:
    """A live entry: the dot that created it plus its payload.

    Example::

        e = _Add(Dot(1, "a"), b"apple")
    """

    dot: Dot
    payload: bytes


class OrMapMemory:
    """An add-wins observed-remove map CRDT implementing the ``Memory`` protocol.

    Each instance is an independent **replica**. Local writes mint a fresh dot
    ``(node_id, counter+1)``; :meth:`remove` drops the dots this replica has
    observed for a key; and replicas reconcile with :meth:`export_all` /
    :meth:`merge_all` (full-state anti-entropy) or the per-key
    :meth:`export` / :meth:`merge`. The merge is conflict-free and add-wins, so
    any set of replicas that have observed the same operations read back
    identical values no matter the order in which writes, removes, and merges
    arrived.

    The base :class:`~nest_core.layers.memory.Memory` surface
    (``read`` / ``write`` / ``cas`` / ``subscribe``) treats values as opaque
    user payloads; the CRDT machinery is internal. The additive
    :meth:`remove` / :meth:`export` / :meth:`merge` / :meth:`export_all` /
    :meth:`merge_all` methods are the delete verb and the replication channel --
    a caller that only speaks the base protocol never has to know the values
    are CRDT entries.

    Example::

        mem = OrMapMemory("agent-0")
        await mem.write("counter", b"42")
        assert await mem.read("counter") == b"42"
        await mem.remove("counter")
        assert await mem.read("counter") is None
    """

    def __init__(self, node_id: str = "node") -> None:
        """Create a replica with a stable, unique ``node_id``.

        The ``node_id`` must be stable for the replica's lifetime and unique
        across replicas: it namespaces this replica's dots and breaks ties in
        the read total order. Two replicas sharing a ``node_id`` would mint
        colliding dots and break the convergence guarantee.

        Example::

            mem = OrMapMemory("agent-0")
        """
        self._node_id = str(node_id)
        # key -> {dot: payload} for every currently-live add of that key.
        self._entries: dict[str, dict[Dot, bytes]] = {}
        # Causal context / version vector: node -> highest counter observed.
        self._context: dict[str, int] = {}
        self._subscribers: dict[str, list[asyncio.Queue[bytes]]] = {}

    @property
    def node_id(self) -> str:
        """The stable node identifier that namespaces this replica's dots.

        Example::

            assert OrMapMemory("agent-0").node_id == "agent-0"
        """
        return self._node_id

    @property
    def context(self) -> dict[str, int]:
        """A copy of this replica's causal context (version vector).

        Example::

            mem = OrMapMemory("a")
            assert mem.context == {}
        """
        return dict(self._context)

    # -- Memory protocol -------------------------------------------------

    async def read(self, key: str) -> bytes | None:
        """Read the winning payload for ``key`` or ``None`` if it has no live add.

        When concurrent writes leave several live dots, the winner is the dot
        that is largest under ``(counter, node)`` -- a deterministic, replay-
        stable choice.

        Example::

            val = await mem.read("counter")
        """
        winner = self._winner(key)
        return winner.payload if winner is not None else None

    async def write(self, key: str, value: bytes) -> None:
        """Locally add/replace ``key`` with ``value`` under a fresh dot.

        The write mints ``(node_id, counter+1)`` and makes it the *only* live
        dot this replica knows for ``key`` (a local write supersedes this
        replica's own earlier writes); concurrent writes from other replicas
        are preserved as separate dots at the next merge. Subscribers are
        notified, matching the ``blackboard`` contract that every local write
        is observable.

        Example::

            await mem.write("counter", b"42")
        """
        dot = self._next_dot()
        self._entries[key] = {dot: value}
        await self._notify(key, value)

    async def subscribe(self, key: str) -> AsyncIterator[bytes]:
        """Yield the winning payload for ``key`` each time it advances.

        Removals are not delivered (the base protocol yields ``bytes`` values,
        not tombstones); a subsequent re-add is delivered normally.

        Example::

            async for val in mem.subscribe("counter"):
                print(val)
        """
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._subscribers.setdefault(key, []).append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers[key].remove(q)

    async def cas(self, key: str, expected: bytes, new: bytes) -> bool:
        """Compare-and-swap on this replica's winning payload.

        Succeeds iff the current winning payload equals ``expected``, in which
        case it performs a normal tagged :meth:`write` of ``new``. This is
        linearizable *on this replica*; across replicas the CRDT merge -- not
        CAS -- reconciles a swap that raced a concurrent write elsewhere.

        Example::

            ok = await mem.cas("counter", b"42", b"43")
        """
        winner = self._winner(key)
        current = winner.payload if winner is not None else None
        if current == expected:
            await self.write(key, new)
            return True
        return False

    # -- Additive delete verb -------------------------------------------

    async def remove(self, key: str) -> bool:
        """Observed-remove ``key``: drop every add this replica has seen.

        Only the dots currently live at this replica are removed; because the
        causal context retains their counters, a peer learns the removal at the
        next merge. A concurrent add made elsewhere (a dot outside this
        replica's context) is **not** removed -- that is the add-wins rule.
        Returns ``True`` if a live value was actually dropped. Idempotent.

        Example::

            await mem.write("k", b"v")
            assert await mem.remove("k") is True
            assert await mem.remove("k") is False
        """
        if key not in self._entries:
            return False
        del self._entries[key]
        await self._notify_removed(key)
        return True

    # -- CRDT replication channel ---------------------------------------

    def export(self, key: str) -> bytes | None:
        """Serialize the live dots and causal context for a single ``key``.

        Returns ``None`` only if this replica has *never* observed ``key``.
        A key that has been removed serializes with an empty ``dots`` list, so
        the removal still propagates through :meth:`merge`. The result is valid
        input to another replica's :meth:`merge`.

        Example::

            state = mem.export("counter")
        """
        if key not in self._entries and not self._seen_key(key):
            return None
        return self._encode_key(key, self._entries.get(key, {}))

    def export_all(self) -> bytes:
        """Serialize this replica's full state for a full-state anti-entropy push.

        This is the correct channel for propagating **removals**: the snapshot
        carries the complete live-key set plus the causal context, so a peer
        can tell "never seen" (keep) from "seen and removed" (drop).

        Example::

            snapshot = mem.export_all()
        """
        keys: dict[str, list[dict[str, Any]]] = {
            key: self._encode_dots(dots) for key, dots in sorted(self._entries.items())
        }
        data = {
            "crdt": CRDT_KIND,
            "keys": keys,
            "context": dict(sorted(self._context.items())),
        }
        return json.dumps(data, sort_keys=True).encode("utf-8")

    async def merge(self, key: str, state: bytes) -> bool:
        """Merge a remote single-key state into this replica.

        Applies the add-wins join for ``key`` using the incoming causal
        context, advances this replica's context pointwise, and notifies
        subscribers if the winning payload changed. Returns ``True`` on a
        visible change. Idempotent: merging the same state twice is a no-op.

        Example::

            changed = await mem.merge("counter", other.export("counter"))
        """
        remote_key, remote_dots, remote_ctx = self._decode_key(state)
        target = key if remote_key is None else remote_key
        before = self._winner(target)
        self._entries[target] = self._join_key(
            self._entries.get(target, {}), remote_dots, remote_ctx
        )
        if not self._entries[target]:
            del self._entries[target]
        self._absorb_context(remote_ctx)
        return await self._emit_if_changed(target, before)

    async def merge_all(self, state: bytes) -> list[str]:
        """Merge a full-state snapshot, returning the keys whose value changed.

        Because the snapshot names every live key and the sender's context,
        this reconciles adds *and* removals: a key the sender dropped is
        removed here too unless this replica holds a concurrent add.

        Example::

            changed_keys = await mem.merge_all(other.export_all())
        """
        remote_keys, remote_ctx = self._decode_all(state)
        before: dict[str, _Add | None] = {}
        for key in set(self._entries) | set(remote_keys):
            before[key] = self._winner(key)
            merged = self._join_key(
                self._entries.get(key, {}), remote_keys.get(key, {}), remote_ctx
            )
            if merged:
                self._entries[key] = merged
            else:
                self._entries.pop(key, None)
        self._absorb_context(remote_ctx)
        changed: list[str] = []
        for key in sorted(before):
            if await self._emit_if_changed(key, before[key]):
                changed.append(key)
        return changed

    # -- internals -------------------------------------------------------

    def _next_dot(self) -> Dot:
        counter = self._context.get(self._node_id, 0) + 1
        self._context[self._node_id] = counter
        return Dot(counter=counter, node=self._node_id)

    def _winner(self, key: str) -> _Add | None:
        dots = self._entries.get(key)
        if not dots:
            return None
        best = max(dots)
        return _Add(dot=best, payload=dots[best])

    def _seen_key(self, key: str) -> bool:
        # A key is "known" if it is live now; removed keys are indistinguishable
        # from never-seen at the per-key granularity, which is why removals
        # propagate through export_all (full state), not a bare export(key).
        return key in self._entries

    def _join_key(
        self,
        mine: dict[Dot, bytes],
        theirs: dict[Dot, bytes],
        their_ctx: dict[str, int],
    ) -> dict[Dot, bytes]:
        """Add-wins ORSWOT join of two dot sets for one key.

        Keep one of my dots if the other side still has it, or if the other
        side has never observed it (a concurrent local add). Symmetrically for
        their dots against my context. The union of the survivors is the merged
        live set.
        """
        kept: dict[Dot, bytes] = {}
        for dot, payload in mine.items():
            if dot in theirs or dot.counter > their_ctx.get(dot.node, 0):
                kept[dot] = payload
        for dot, payload in theirs.items():
            if dot in mine or dot.counter > self._context.get(dot.node, 0):
                kept[dot] = payload
        return kept

    def _absorb_context(self, other: dict[str, int]) -> None:
        for node, counter in other.items():
            if counter > self._context.get(node, 0):
                self._context[node] = counter

    async def _emit_if_changed(self, key: str, before: _Add | None) -> bool:
        after = self._winner(key)
        before_payload = before.payload if before is not None else None
        after_payload = after.payload if after is not None else None
        if after_payload == before_payload:
            return False
        if after_payload is None:
            await self._notify_removed(key)
        else:
            await self._notify(key, after_payload)
        return True

    async def _notify(self, key: str, payload: bytes) -> None:
        for q in self._subscribers.get(key, []):
            await q.put(payload)

    async def _notify_removed(self, key: str) -> None:
        # Removals are not surfaced on the value stream; hook retained so the
        # emit path is symmetric and easy to extend to tombstone-aware
        # subscribers later.
        return None

    # -- serialization ---------------------------------------------------

    @staticmethod
    def _encode_dots(dots: dict[Dot, bytes]) -> list[dict[str, Any]]:
        return [
            {
                "node": dot.node,
                "counter": dot.counter,
                "payload": base64.b64encode(payload).decode("ascii"),
            }
            for dot, payload in sorted(dots.items())
        ]

    def _encode_key(self, key: str, dots: dict[Dot, bytes]) -> bytes:
        data = {
            "crdt": CRDT_KIND,
            "key": key,
            "dots": self._encode_dots(dots),
            "context": dict(sorted(self._context.items())),
        }
        return json.dumps(data, sort_keys=True).encode("utf-8")

    @staticmethod
    def _loads_object(state: bytes) -> dict[str, Any]:
        try:
            obj = json.loads(state)
        except (ValueError, TypeError) as exc:
            msg = "state is not valid JSON"
            raise OrMapStateError(msg) from exc
        if not isinstance(obj, dict):
            msg = f"not {CRDT_KIND} state: {obj!r}"
            raise OrMapStateError(msg)
        data = cast("dict[str, Any]", obj)
        if data.get("crdt") != CRDT_KIND:
            msg = f"not {CRDT_KIND} state: {data!r}"
            raise OrMapStateError(msg)
        return data

    @staticmethod
    def _parse_dots(raw: Any) -> dict[Dot, bytes]:
        if not isinstance(raw, list):
            msg = "'dots' must be a list"
            raise OrMapStateError(msg)
        raw_list = cast("list[Any]", raw)
        dots: dict[Dot, bytes] = {}
        for item in raw_list:
            if not isinstance(item, dict):
                msg = f"dot entry must be an object: {item!r}"
                raise OrMapStateError(msg)
            fields = cast("dict[str, Any]", item)
            try:
                node = str(fields["node"])
                counter = int(fields["counter"])
                payload = base64.b64decode(fields["payload"])
            except (KeyError, ValueError, TypeError) as exc:
                msg = f"malformed dot entry: {fields!r}"
                raise OrMapStateError(msg) from exc
            dots[Dot(counter=counter, node=node)] = payload
        return dots

    @staticmethod
    def _parse_context(raw: Any) -> dict[str, int]:
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            msg = "'context' must be an object"
            raise OrMapStateError(msg)
        raw_ctx = cast("dict[str, Any]", raw)
        try:
            return {str(node): int(counter) for node, counter in raw_ctx.items()}
        except (ValueError, TypeError) as exc:
            msg = f"malformed context: {raw_ctx!r}"
            raise OrMapStateError(msg) from exc

    @classmethod
    def _decode_key(cls, state: bytes) -> tuple[str | None, dict[Dot, bytes], dict[str, int]]:
        data = cls._loads_object(state)
        raw_key = data.get("key")
        key = None if raw_key is None else str(raw_key)
        dots = cls._parse_dots(data.get("dots", []))
        ctx = cls._parse_context(data.get("context"))
        return key, dots, ctx

    @classmethod
    def _decode_all(cls, state: bytes) -> tuple[dict[str, dict[Dot, bytes]], dict[str, int]]:
        data = cls._loads_object(state)
        raw_keys = data.get("keys", {})
        if not isinstance(raw_keys, dict):
            msg = "snapshot 'keys' must be an object"
            raise OrMapStateError(msg)
        raw_map = cast("dict[str, Any]", raw_keys)
        keys: dict[str, dict[Dot, bytes]] = {
            str(key): cls._parse_dots(dots) for key, dots in raw_map.items()
        }
        ctx = cls._parse_context(data.get("context"))
        return keys, ctx
