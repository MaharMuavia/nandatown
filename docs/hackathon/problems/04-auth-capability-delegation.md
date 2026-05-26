---
title: Delegatable capability tokens with cascading revocation
layer: auth
difficulty: easy
---

# Delegatable capability tokens with cascading revocation

## Motivation

The default auth plugin
[`nest_plugins_reference/auth/jwt_auth.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/auth/jwt_auth.py)
is 106 lines of HMAC-signed token issuance. PR #9 added a DPoP-style
sender-constrained JWT — a meaningful upgrade for replay resistance.
Neither plugin lets an agent **delegate** a subset of its capabilities
to another agent without going back to the issuer, and neither
supports **cascading revocation** (revoke a parent → all descendants
become invalid).

`JwtAuth._revoked: set[str]` (line 33) tracks revocation by exact
token string, with no parent-child relationship at all. That makes the
auth layer unable to model the most common real-world pattern:
"agent A holds a long-lived root token; agent A mints a 10-minute
sub-token for agent B; revoking A's token should invalidate B's at
the next verify, automatically." Macaroons (Google, 2014), biscuits
(CleverCloud, 2020), and SPIFFE delegation all do this.
[`docs/layers/auth.md`](../../../docs/layers/auth.md) explicitly lists
"capability delegation" and "revocation propagation" as wanted.

Anyone building a multi-agent workflow where the orchestrator hands
out narrowly-scoped, time-bounded sub-capabilities benefits. Without
this you cannot model an LLM-agent sub-renting access to a tool — and
withdrawing it cleanly.

## Success criteria

- Ship an auth plugin (suggested name: `delegatable` or `macaroons`)
  registered as `(\"auth\", \"<your_name>\")` in
  [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py).
- New API on top of the existing `Auth` protocol:
  `delegate(parent_token, audience, scopes_subset, ttl) -> Token`. The
  child token's scopes must be a strict subset of the parent's.
  Issuing a child with a scope the parent doesn't hold must raise.
- `verify(child_token)` must check the parent's revocation state
  transitively. If any ancestor in the chain is revoked, the child
  fails to verify with a typed exception (`RevokedAncestorError` or
  similar).
- Ship an adversarial validator that catches **three attacks**:
  1. *Scope escalation*: child requests broader scopes than parent.
  2. *Stale parent*: parent token expired or revoked but child still
     verifies.
  3. *Audience confusion*: child token presented by an agent other
     than its declared audience.
- The validator must FAIL against the default `jwt` plugin and PASS
  against your plugin.
- Ship `scenarios/delegated_auth.yaml` with a coordinator, 3
  intermediaries, and 12 leaf agents in a delegation tree.

## Suggested approach pointers

- Read the macaroon paper (Birgisson et al., 2014) — caveats are the
  cleanest model here.
- Borrow the HMAC chain pattern from `jwt_auth.py` but anchor each
  child's signature to its parent's hash. Revoking a parent's hash
  invalidates every descendant by construction — no separate
  revocation list per child.
- The DPoP plugin from PR #9 is a good reference for how to extend
  the auth surface without breaking the base `Auth` contract.
- Decide: is your delegation tree a *strict* tree (single parent per
  token) or a DAG (multiple parents)? Strict tree is enough.
- Time bounds: child TTL must be ≤ parent TTL. Enforce this.

## Anti-patterns

- Don't ship "delegation" that's actually just re-issuance by the
  central authority. The whole point is the parent agent can mint
  child tokens *without* the issuer's help.
- Don't add a `\"delegated_from\"` field to JWT claims and call it
  delegation — without HMAC chaining there's no transitive
  revocation.
- Don't conflate scopes with audiences. Both matter.
- Don't rebuild PR #9's DPoP. This is a *different* problem.

## Out of scope

- Hardware-backed key attestation (TPM/HSM).
- OAuth2 server endpoints. Pure in-process is fine.
- Token introspection over the network.
