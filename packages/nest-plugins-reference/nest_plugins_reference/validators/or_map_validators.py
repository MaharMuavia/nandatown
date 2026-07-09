# SPDX-License-Identifier: Apache-2.0
"""Adversarial validators for the OR-Map (observed-remove) memory plugin.

Two properties the default ``blackboard`` and the merged ``lww_register`` plugin
cannot satisfy for a shared *set/map of live entries*:

1. **Add-wins under a concurrent remove.**  When one replica re-advertises an
   entry at the same time another replica retires the copy it had seen, the
   entry must survive -- an add the remover never observed is not deleted.
   ``check_add_wins_survives_concurrent_remove`` builds exactly that race and
   asserts both replicas converge to the *re-added* value.

   * ``blackboard`` has no causal history: a delete is order-dependent ``del``
     on a per-replica dict, so the two replicas diverge -- fails.
   * ``lww_register`` resolves a delete (modelled as a tombstone write) by
     ``(lamport, node)``; the race is arranged so the tombstone sorts *above*
     the concurrent add, so the add is silently overwritten -- fails.
   * ``or_map`` keeps the add via the add-wins rule -- passes.

2. **Convergence under add/remove churn.**  Replicas that apply the same
   multiset of adds and removes in **different delivery orders** must read back
   identical state.  ``check_convergence_under_churn`` permutes the delivery
   order per replica and asserts equality.  ``blackboard`` diverges the moment
   two replicas see operations in different orders; ``or_map`` converges.

Both validators are **capability-aware** pure functions over a replica factory,
so a single call site discriminates all three plugins: they use the CRDT
replication channel (``export_all`` / ``merge_all``) and the ``remove`` verb
when present, and fall back to modelling "observe" as a ``write`` and "delete"
as a tombstone ``write`` when they are not -- which is precisely what exposes
the order-dependent plugins.

Example::

    from nest_plugins_reference.memory.or_map import OrMapMemory
    from nest_plugins_reference.memory.blackboard import Blackboard

    assert check_add_wins_survives_concurrent_remove(OrMapMemory).passed
    assert not check_add_wins_survives_concurrent_remove(Blackboard).passed
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from nest_plugins_reference.validators.gossip_validators import ValidatorReport

ReplicaFactory = Callable[[str], Any]
"""A ``node_id -> memory replica`` constructor (e.g. ``OrMapMemory``)."""

_TOMBSTONE = b"\x00__ormap_tombstone__"
"""Sentinel used to model a delete on plugins that lack a ``remove`` verb."""


class AddWinsViolationError(AssertionError):
    """Raised when a concurrent add is lost to a concurrent remove.

    Example::

        raise AddWinsViolationError("re-added 'cat' was deleted by a stale remove")
    """


def _has_full_channel(replica: Any) -> bool:
    return hasattr(replica, "export_all") and hasattr(replica, "merge_all")


async def _observe(source: Any, target: Any, key: str) -> None:
    """Make ``target`` observe ``source``'s current state for ``key``."""
    if _has_full_channel(source) and _has_full_channel(target):
        await target.merge_all(source.export_all())
        return
    if hasattr(source, "export") and hasattr(target, "merge"):
        state = source.export(key)
        if state is not None:
            await target.merge(key, state)
        return
    # No replication channel (e.g. blackboard): model observation as adopting
    # the source's currently-visible value via the base protocol.
    value = await source.read(key)
    if value is not None:
        await target.write(key, value)


async def _delete(replica: Any, key: str) -> None:
    """Delete ``key`` at ``replica`` using ``remove`` if present, else a tombstone."""
    if hasattr(replica, "remove"):
        await replica.remove(key)
    else:
        await replica.write(key, _TOMBSTONE)


async def _reconcile(a: Any, b: Any, key: str) -> None:
    """Exchange state both ways so ``a`` and ``b`` see each other's operations."""
    if _has_full_channel(a) and _has_full_channel(b):
        state_a = a.export_all()
        state_b = b.export_all()
        await a.merge_all(state_b)
        await b.merge_all(state_a)
        return
    if hasattr(a, "export") and hasattr(b, "export"):
        state_a = a.export(key)
        state_b = b.export(key)
        if state_b is not None:
            await a.merge(key, state_b)
        if state_a is not None:
            await b.merge(key, state_a)
        return
    # Blackboard fallback: each side delivers its current value to the other.
    val_a = await a.read(key)
    val_b = await b.read(key)
    if val_b is not None:
        await a.write(key, val_b)
    if val_a is not None:
        await b.write(key, val_a)


async def _run_add_wins(make_replica: ReplicaFactory, key: str) -> ValidatorReport:
    # Replica ids chosen so a modelled tombstone from the remover ("z") sorts
    # ABOVE the concurrent add from the adder ("a") under an LWW register's
    # (counter, node) order -- making the LWW failure deterministic rather than
    # interleaving-dependent.
    adder = make_replica("a")
    remover = make_replica("z")

    old = b"v-old"
    new = b"v-new"

    await adder.write(key, old)
    await _observe(adder, remover, key)  # remover now knows the old add

    # Concurrent operations: the adder re-advertises; the remover retires the
    # copy it observed. Neither has seen the other's operation yet.
    await adder.write(key, new)
    await _delete(remover, key)

    await _reconcile(adder, remover, key)

    read_adder = await adder.read(key)
    read_remover = await remover.read(key)

    if read_adder != read_remover:
        return ValidatorReport(
            passed=False,
            detail=(
                f"replicas diverged after concurrent add/remove: "
                f"adder={read_adder!r} remover={read_remover!r}"
            ),
            evidence={"adder": repr(read_adder), "remover": repr(read_remover)},
        )
    if read_adder != new:
        return ValidatorReport(
            passed=False,
            detail=(
                f"add-wins violated: concurrent re-add {new!r} was lost, "
                f"replicas hold {read_adder!r}"
            ),
            evidence={"expected": repr(new), "actual": repr(read_adder)},
        )
    return ValidatorReport(
        passed=True,
        detail=f"add-wins holds: concurrent re-add {new!r} survived the remove",
        evidence={"value": repr(read_adder)},
    )


def check_add_wins_survives_concurrent_remove(
    make_replica: ReplicaFactory,
    *,
    key: str = "cat",
) -> ValidatorReport:
    """Assert a concurrent re-add survives a stale remove (the add-wins rule).

    Drives the canonical race -- replica ``a`` re-adds ``key`` while replica
    ``z`` removes the copy it had observed -- and returns ``passed=True`` iff
    both replicas converge to the re-added value. Fails for ``blackboard``
    (divergence) and ``lww_register`` (the tombstone overwrites the add).

    Example::

        report = check_add_wins_survives_concurrent_remove(OrMapMemory)
        assert report.passed, report.detail
    """
    return asyncio.run(_run_add_wins(make_replica, key))


async def _run_churn(
    make_replica: ReplicaFactory,
    ops: Sequence[tuple[str, str, bytes | None]],
    delivery_orders: Sequence[Sequence[int]],
    key: str,
) -> ValidatorReport:
    replica_count = len(delivery_orders)
    replicas = [make_replica(f"node-{i}") for i in range(replica_count)]

    # Phase 1: apply each op at its origin replica and snapshot the full state.
    snapshots: list[bytes | None] = []
    for origin_idx, verb, payload in ops:
        origin = replicas[int(origin_idx.split("-")[-1])] if "-" in origin_idx else replicas[0]
        if verb == "add" and payload is not None:
            await origin.write(key, payload)
        elif verb == "remove":
            await _delete(origin, key)
        if _has_full_channel(origin):
            snapshots.append(origin.export_all())
        else:
            snapshots.append(None)

    # Phase 2: deliver every op's resulting snapshot to each replica in its own
    # order. Plugins without a replication channel replay the raw value/verb.
    for r_idx, order in enumerate(delivery_orders):
        for op_idx in order:
            snap = snapshots[op_idx]
            origin_idx, verb, payload = ops[op_idx]
            if snap is not None and _has_full_channel(replicas[r_idx]):
                await replicas[r_idx].merge_all(snap)
            elif verb == "add" and payload is not None:
                await replicas[r_idx].write(key, payload)
            elif verb == "remove":
                await _delete(replicas[r_idx], key)

    finals = [await r.read(key) for r in replicas]
    distinct = {repr(v) for v in finals}
    if len(distinct) == 1:
        return ValidatorReport(
            passed=True,
            detail=f"{replica_count} replicas converged to {finals[0]!r} under churn",
            evidence={"value": repr(finals[0])},
        )
    return ValidatorReport(
        passed=False,
        detail=f"replicas diverged under churn into {len(distinct)} states: {sorted(distinct)}",
        evidence={"states": sorted(distinct)},
    )


def check_convergence_under_churn(
    make_replica: ReplicaFactory,
    *,
    key: str = "cat",
) -> ValidatorReport:
    """Assert replicas converge under add/remove operations delivered out of order.

    Applies a fixed multiset of adds and removes, then delivers them to three
    replicas in three different orders, and returns ``passed=True`` iff all
    replicas read back the same value. Fails for ``blackboard`` (order
    dependent); passes for ``or_map``.

    Example::

        report = check_convergence_under_churn(OrMapMemory)
        assert report.passed, report.detail
    """
    ops: list[tuple[str, str, bytes | None]] = [
        ("node-0", "add", b"a0"),
        ("node-1", "add", b"a1"),
        ("node-2", "add", b"a2"),
        ("node-0", "remove", None),
        ("node-1", "add", b"a1-again"),
    ]
    delivery_orders = [[0, 1, 2, 3, 4], [4, 3, 2, 1, 0], [2, 0, 4, 1, 3]]
    return asyncio.run(_run_churn(make_replica, ops, delivery_orders, key))
