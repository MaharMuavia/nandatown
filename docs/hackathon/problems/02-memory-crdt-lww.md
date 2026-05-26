---
title: Conflict-free shared memory under concurrent writers
layer: memory
difficulty: easy
---

# Conflict-free shared memory under concurrent writers

## Motivation

The default memory plugin
[`nest_plugins_reference/memory/blackboard.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/memory/blackboard.py)
is 80 lines of "shared dict + optimistic CAS." `write` is
**last-writer-wins by wall-arrival order, with no notion of causal
history**; `cas` returns `False` on conflict and leaves the caller to
retry. That's fine for a single coordinator scribbling to a known key.
It is the *wrong* shape the moment two agents try to update the same
slot at once, which is exactly what happens in
[`scenarios/marketplace.yaml`](../../../scenarios/marketplace.yaml)
when fifty sellers race to claim shared catalogue entries, or in the
reputation scenario when the observer and an honest reporter both
update the same agent's score.

PR #4 (semantic memory) added recall + TTL + LRU but did **not**
change conflict resolution — it still inherits LWW semantics from the
underlying `OrderedDict`. So the gap remains: there is no
CRDT-shaped memory plugin, and the
[`docs/layers/memory.md`](../../../docs/layers/memory.md) "Good fits"
list explicitly calls out CRDTs as wanted.

Anyone building a coordination protocol that needs eventual
consistency under concurrent writes (vote-tally aggregation, shared
catalogue, distributed counter, presence) benefits. The blackboard
silently corrupts state; a real CRDT proves convergence.

## Success criteria

- Ship a memory plugin (suggested name: `lww_crdt` or `or_set`) that
  implements at least *one* well-known CRDT correctly: LWW-Register
  with logical clocks, OR-Set, G-Counter, or PN-Counter. Register it
  in [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py)
  under `(\"memory\", \"<your_name>\")`.
- The plugin still satisfies the `Memory` protocol from
  [`nest_core/layers/memory.py`](../../../packages/nest-core/nest_core/layers/memory.py)
  (i.e., `isinstance(plugin, Memory)` is True). `read`/`write`/`cas`/
  `subscribe` all work — `cas` should be implementable in terms of
  the CRDT's natural merge semantics.
- Ship an adversarial validator that drives N concurrent writers
  against the same key with deterministic-but-interleaved writes and
  asserts **convergence**: every replica observes the same final
  state regardless of message-delivery order. The validator must FAIL
  against `blackboard` and PASS against your plugin.
- Ship `scenarios/memory_concurrent_writers.yaml` with at least 8
  agents writing to the same logical key under
  `failures.message_drop: 0.1` and arbitrary in-flight reordering.
- Determinism: same seed → byte-identical merged state across runs.

## Suggested approach pointers

- Pick the simplest CRDT that solves *one* of the four built-in
  scenarios' concrete pain. LWW-Register with Lamport clocks is the
  smallest unit of useful work here.
- Use the simulator's per-agent RNG (see `_failure_rng` in
  [`nest_core/sim/simulator.py`](../../../packages/nest-core/nest_core/sim/simulator.py))
  to seed your logical clocks deterministically.
- For OR-Set, the unique-tag-on-add trick is the whole game.
- Encode the CRDT state inside the existing `bytes` value type — JSON
  inside is fine. Keep traces grep-able.
- Look at how PR #4 layered new behaviour on top of an existing plugin
  without breaking the base interface.

## Anti-patterns

- Don't ship a CRDT that requires every node to see every other node
  before merging (that's just a centralized log, not a CRDT).
- Don't claim convergence and then implement it with global locks.
- Don't reimplement `blackboard` and call it `blackboard_v2`.
- Don't hand-wave determinism by relying on `time.time()` or
  `random.random()` with an unseeded global RNG.

## Out of scope

- Distributed-systems-grade gossip transport. Use NEST's in-memory
  delivery; you're testing the *merge logic*, not the wire.
- CRDTs over the wire (CmRDTs with operation-based replication). Pick
  state-based (CvRDT) for this problem.
- Persistence to disk.
