# Trust layer

**What it does.** Maintain per-agent reputation, accept attestations
and abuse reports, optionally support stake.

## Interface

```python
class Trust(Protocol):
    async def score(self, agent: AgentId) -> ReputationScore: ...
    async def attest(self, agent: AgentId, claim: Claim) -> Attestation: ...
    async def report(self, agent: AgentId, evidence: Evidence) -> None: ...
    async def stake(self, agent: AgentId, amount: int) -> None: ...
```

Full definition: [`nest_core/layers/trust.py`](../../packages/nest-core/nest_core/layers/trust.py).

## Default plugin

`score_average` — running mean of feedback scores. No Sybil resistance,
no decay, no stake economics.

Source: [`nest_plugins_reference/trust/score_average.py`](../../packages/nest-plugins-reference/nest_plugins_reference/trust/score_average.py).

The `reputation` scenario exercises this layer — 16 honest + 4
malicious + 1 observer that samples cheat reports probabilistically.

## `agent_receipts` — receipt-corroborated, collusion-resistant reputation

Derives reputation from **cross-signed receipts** of real interactions
instead of self-asserted feedback. A receipt builds reputation only if
its Ed25519 issuer signature verifies, a *distinct* counterparty
co-signed the same interaction, and the receipt does not sit inside an
isolated collusion component (Tarjan SCC severance over the
corroboration graph) — so a wash-trading ring collapses to score ~0
while honest agents keep their corroborated score.

Source: [`nest_plugins_reference/trust/agent_receipts.py`](../../packages/nest-plugins-reference/nest_plugins_reference/trust/agent_receipts.py).
Scenario: `receipt_reputation` (honest anchor + isolated 4-agent ring +
byzantine co-signers).

## `parc` — portable reputation credentials

Reputation elsewhere in this layer dies with the run. `parc` extends
`agent_receipts` with **portability**: it exports an agent's receipt
ledger as a W3C-Verifiable-Credential-shaped document (a
`behavioral_merkle_root` committing to the carried receipts plus
`nanda-rep/0.2` scores recomputable from them), signed **through the
identity layer** (`ed25519_rotating`), and admits presented credentials
at the border of a new trust domain by *recomputing rather than
trusting*:

- the Merkle root and scores are re-derived from the carried receipts —
  an issuer-inflated-then-re-signed score passes proof verification and
  is still rejected (**a valid signature is not admission**);
- the proof is checked against the issuer's key-rotation window *as-of*
  the credential's `validFrom` tick, so a credential signed with a
  rotated-out key is rejected;
- the presenter must *be* the credential subject (stolen credentials
  are rejected);
- an inline single-subject ledger is a star graph and cannot show an
  N-party ring, so the gate also re-runs whole-graph collusion
  severance over the originating domain's **published ledger**.

**Selective disclosure.** A holder need not show a verifier the whole
ledger: `build_presentation` packages chosen receipts, each with a
Merkle inclusion proof against the credential's signed
`behavioral_merkle_root`, and `verify_presentation` confirms every
disclosed receipt is committed under that root — and that each proof's
`leaf_count` equals the signed `receipt_count`, the bound on the
undisclosed remainder — without needing the rest of the ledger. Scores
are **not** recomputed from a disclosed subset: the reputation
aggregate is a whole-graph property (collusion severance needs every
edge), so the signed score stands — re-deriving it from a hand-picked
subset is exactly the cherry-picking this split forbids. Full-ledger
recomputation remains `admit`'s job.

Source: [`nest_plugins_reference/trust/parc.py`](../../packages/nest-plugins-reference/nest_plugins_reference/trust/parc.py).
Scenario: `parc_migration` (two trust domains in one run; forged,
replayed, stale-key, inflated, and wash-ring credentials each denied
with a typed reason).

## Writing your own

See [`writing-a-plugin.md`](../writing-a-plugin.md). Register under
entry point group `nest.plugins.trust`.

Good fits to test here: EigenTrust-style transitive reputation,
proof-of-stake reputation, decaying scores, attestation graphs,
credential revocation registries.
