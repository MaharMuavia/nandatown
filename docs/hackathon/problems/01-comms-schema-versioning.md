---
title: Versioned message schemas with forward/backward compatibility
layer: comms
difficulty: easy
---

# Versioned message schemas with forward/backward compatibility

## Motivation

The default comms plugin
[`nest_plugins_reference/comms/nest_native.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/comms/nest_native.py)
is 114 lines of raw JSON-envelope-plus-base64 serialization with **no
schema version field, no unknown-field handling, and no semantic
versioning of message types**. Look at `serialize` (lines 46-62): it
emits `id`, `sender`, `receiver`, `payload`, `correlation_id`,
`timestamp`, `metadata` — that's it. There is no `"v"` field. There is
no way for a v2 agent to safely receive a v1 message; there is no way
for a v1 agent to receive a v2 message that added a new field.

This is the layer that *every* other layer rides on. The moment two
swarms running different NEST versions try to talk — or two
implementations of the same protocol negotiated by competing
contributors try to interop — the wire format silently breaks and the
trace shows mysterious `KeyError` exceptions deep inside agent
behaviour. The validators in
[`nest_core/validators.py`](../../../packages/nest-core/nest_core/validators.py)
will report "messages flowed" but not "messages were
*understood*". Nobody picked this layer in the first hackathon round
(0 of 10 PRs touched comms) — it's a real gap.

Anyone deploying NEST against a long-running swarm benefits: rolling
upgrades become possible. Anyone publishing a third-party plugin
benefits: their wire format can evolve without breaking the world.

## Success criteria

- Ship a new comms plugin (suggested name: `versioned`) registered in
  [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py)
  as `(\"comms\", \"versioned\")`.
- Every serialized envelope carries an explicit `schema_version`
  (semver string) and a `kind` (message type tag).
- `deserialize` accepts messages with **higher minor versions than
  it knows about** (forward compat: unknown fields are preserved in
  `metadata` and re-emitted on re-serialize) and **rejects
  unknown-major-version messages with a typed exception**
  (`UnsupportedSchemaError`) instead of crashing.
- Ship an adversarial validator that scans a trace and fails if any
  agent silently dropped an unknown field or accepted an
  unknown-major version. The validator must FAIL against the default
  `nest_native` plugin when v2 messages are injected and PASS against
  your plugin.
- Ship `scenarios/comms_versioning.yaml` with mixed-version agents
  (half v1, half v2). The validator passes. Trace is deterministic
  under seeds 42, 7, 1337.
- All tests pass in <30 seconds on a single core.

## Suggested approach pointers

- Look at how Protobuf does unknown-field preservation; you can mimic
  the spirit in JSON by stuffing unknowns into a reserved `_unknown`
  dict on deserialize and re-emitting them on serialize.
- Don't try to invent your own version-negotiation handshake — keep
  it in-band on every message.
- Decide *up front* whether your minor-version contract is "MUST
  ignore unknown fields" or "MAY ignore"; document it.
- Property-test round-trip: `deserialize(serialize(m)) == m` for any
  schema-valid `m`, even one with future-version unknowns.
- Look at PR #9's `dpop_jwt` for a clean example of how to introduce
  a parallel plugin without breaking the existing one.

## Anti-patterns

- Don't just add a `"v": 1` field to `nest_native` and call it new.
- Don't make the version handshake out-of-band (over a separate
  channel) — that defeats the point.
- Don't break the existing `nest_native` envelope. Your plugin lives
  alongside it.
- Don't use `pickle`. The format must be inspectable in a JSONL trace.

## Out of scope

- Real schema registries (Confluent-style). This is in-band only.
- Cross-language wire interop (JSON-only is fine).
- The `Message` Pydantic model itself; you're versioning the
  *envelope*, not the typed payload.
