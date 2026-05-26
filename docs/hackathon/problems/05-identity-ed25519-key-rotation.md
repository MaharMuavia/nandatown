---
title: Real Ed25519 identity with key rotation and historical signature verification
layer: identity
difficulty: medium
---

# Real Ed25519 identity with key rotation and historical signature verification

## Motivation

The default identity plugin
[`nest_plugins_reference/identity/did_key.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/identity/did_key.py)
is 199 lines of deterministic *simulation* cryptography
(textbook RSA with `pow(sig_int, e, n)` at line 98 and Miller-Rabin
primality at line 146-174). The module docstring at line 6 calls it
out: "It is not production cryptography." The README footnote at line
229 hammers it home: "deterministic public-key signatures for
simulation; not Ed25519."

No real identity layer ships — and crucially **no plugin supports
key rotation**. A long-running agent that wants to rotate its signing
key (because a key has been compromised, or because of policy)
currently cannot, because `register_peer` (line 40) accepts exactly
one public key per agent ID and overwriting it would invalidate every
prior signature that agent made. There is no concept of "this
signature was valid *at the time it was made*." Zero hackathon PRs
touched identity — clean ground.

[`docs/layers/identity.md`](../../../docs/layers/identity.md)
explicitly wants "real Ed25519/secp256k1 signing, DID method
implementations, key rotation, multi-key agents." Any deployment that
intends to survive a key-compromise event — every real one —
benefits.

## Success criteria

- Ship an identity plugin (suggested name: `ed25519_rotating`)
  registered as `(\"identity\", \"<your_name>\")` in
  [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py).
- Real Ed25519 signing — the stdlib has none, so use
  `cryptography` or a pure-Python implementation. If you bring a new
  dependency, declare it in the `[plugins]` extra in
  [`pyproject.toml`](../../../pyproject.toml).
- API for rotation: `rotate_key(new_seed) -> KeyId`. After rotation,
  signatures made with the **old** key still verify if and only if
  the verifier requests verification *as-of* the old key's validity
  window. After-the-fact forgery using the old (rotated-out) key
  must fail.
- Each `Signature` carries the `key_id` that signed it (extend the
  `Signature` Pydantic model in
  [`nest_core/types.py`](../../../packages/nest-core/nest_core/types.py)
  or add a metadata field — document your choice).
- Ship an adversarial validator that catches **two attacks**:
  1. *Post-rotation forgery*: an attacker who compromised the old
     key tries to forge a fresh signature after rotation. Must fail
     verification.
  2. *Backdating*: an attacker tries to backdate a signature made
     with the *new* key into the old key's validity window. Must
     fail verification.
- Validator must FAIL against `did_key` and PASS against your plugin.
- Ship `scenarios/identity_rotation.yaml` exercising at least one
  rotation per agent over the scenario's lifetime, with 10% byzantine
  agents trying both attacks.

## Suggested approach pointers

- `cryptography.hazmat.primitives.asymmetric.ed25519` is the standard
  library here; deterministic seeding via `Ed25519PrivateKey.
  from_private_bytes(seed)` keeps Tier 1 reproducibility.
- A key's validity window is `[issued_at_tick, rotated_out_tick)`.
  Store it; signatures carry the window they were made in.
- Borrow `_known_keys` shape from `did_key.py` but make it map
  `AgentId -> list[KeyRecord]` instead of `AgentId -> tuple`.
- Treat key rotation as a *publishing* operation — the new key must
  be signed by the old key (or by an out-of-band root) to prove
  continuity. This is the whole point of rotation: continuity of
  identity across keys.
- Tier 2 (LLM agent) interop: don't break `register_peer`'s existing
  callers.

## Anti-patterns

- Don't reimplement RSA-from-`pow` in `did_key.py` and call it
  Ed25519. Use a real implementation.
- Don't make rotation a no-op (silently keeping the same key).
- Don't make every verification require the *current* key — the
  whole feature is "verify against the key that was valid then."
- Don't store private keys in clear text in the trace.

## Out of scope

- Real DID methods (did:web, did:peer). DID-shaped *records* are
  fine; you're not implementing W3C DIDs end-to-end.
- HSM/TPM integration.
- Quantum-resistant signatures.
