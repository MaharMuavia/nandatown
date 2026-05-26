---
title: Gossip-based registry with eventual consistency under partition
layer: registry
difficulty: medium
---

# Gossip-based registry with eventual consistency under partition

## Motivation

The default registry plugin
[`nest_plugins_reference/registry/in_memory.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/registry/in_memory.py)
is 88 lines of "single shared Python dict + asyncio queues for
subscribers." `register`, `lookup`, and `subscribe` all touch
`self._cards: dict[AgentId, AgentCard]` (line 29). There is exactly
one instance per simulation. Every agent in
[`scenarios/marketplace.yaml`](../../../scenarios/marketplace.yaml)
shares it. That is fine for testing message flow, but it is
**operationally a lie**: in any real deployment the registry is
distributed, possibly partitioned, and definitely subject to
eventual-consistency races.

What happens today when you run with `failures.network_partition`
(line 158 of
[`nest_core/runner.py`](../../../packages/nest-core/nest_core/runner.py))?
The partition affects *transport*, but registry lookups still go to
the shared dict — partitioned agents can still discover each other.
That isn't physically possible in the real world. Zero PRs touched
registry; the
[`docs/layers/registry.md`](../../../docs/layers/registry.md) wishlist
calls out "DHT-backed registries, gossip-based discovery, filtering /
capability queries, registry consensus protocols" — nobody picked any
of them.

Anyone running NEST as a believable swarm simulator (rather than a
single-process toy) benefits. Anyone testing service-discovery
protocols benefits directly.

## Success criteria

- Ship a registry plugin (suggested name: `gossip`) where **each agent
  holds its own local view** and views converge via periodic gossip
  messages over the transport layer. Register as
  `(\"registry\", \"gossip\")` in
  [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py).
- `lookup(query)` returns the agent's *local* view at call time —
  potentially stale. `register(card)` is local-write-then-gossip.
- The plugin respects network partitions: agents in different
  partition groups (see `partition_map` at
  [`nest_core/sim/simulator.py`](../../../packages/nest-core/nest_core/sim/simulator.py)
  line 246) cannot directly exchange gossip; convergence requires a
  bridge.
- Ship an adversarial validator that catches **two specific failure
  modes**:
  1. *Stale-lookup honesty*: when partition is active, a lookup must
     not return cards from the other partition. The validator inspects
     the trace and fails if any lookup leaked across an active
     partition.
  2. *Convergence*: after partition heals, all agents' views
     **must converge** within K gossip rounds (you pick K and
     justify it). The validator fails if convergence doesn't happen.
- Validator FAILS against `in_memory` registry (it silently leaks
  across partition by sharing a dict) and PASSES against your plugin.
- Ship `scenarios/gossip_registry.yaml` with 20 agents, a partition
  splitting them 50/50 for the first half of the scenario, then a
  heal. Trace deterministic under seeds 42, 7, 1337.

## Suggested approach pointers

- The minimal viable gossip is push-pull with bounded fanout. Don't
  reach for SWIM or Hyparview unless you have time.
- Use the transport plugin for gossip messages; that way partition
  injection from the simulator naturally affects gossip too. Look at
  how `NestNativeComms.send` in
  [`nest_plugins_reference/comms/nest_native.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/comms/nest_native.py)
  routes through transport.
- Vector clocks on cards make convergence detection clean. Hybrid
  Logical Clocks are an alternative.
- For `subscribe`, deliver a card to the subscriber once it appears
  in the *local* view, not the moment it's globally registered.
- Don't make every agent gossip every round — implement at least
  one form of anti-entropy throttle.

## Anti-patterns

- Don't keep a hidden shared dict "as a cache." If two partitioned
  agents can see each other through it, your plugin is the same as
  `in_memory`.
- Don't broadcast the entire local view on every gossip — pick a
  delta strategy.
- Don't claim convergence and then implement it with a
  centralized leader.
- Don't pretend agents in the same partition group are in the same
  process. Each agent has its own local view.

## Out of scope

- DHT semantics (Kademlia, Chord). Flat gossip is sufficient.
- Registry consensus (Raft-on-registry) — that's a coordination
  problem, not a registry one.
- Cross-language interop.
