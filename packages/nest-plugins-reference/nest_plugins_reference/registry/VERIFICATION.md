# VERIFICATION: `byzantine_gossip` registry plugin

Persona: trust/honesty auditor. This document records what was actually
tested, the FAIL/PASS evidence behind every claim made about this plugin,
and every honest limitation surfaced while building it -- nothing here was
loosened or hidden to make a test pass. If a limitation is real, it is
written down here, not papered over in a test.

Referenced from `byzantine_gossip.py`'s module docstring and
`_sample_eclipse_resistant`'s docstring ("see `VERIFICATION.md` for that
caveat") -- this file lives in the same directory
(`nest_plugins_reference/registry/VERIFICATION.md`), so those references
resolve here directly.

## What this plugin claims -- and does not

**Claim:** `byzantine_gossip` is **byzantine-resistant and
attack-detecting** for three specific, named threats (forged/impersonated
cards in gossip propagation, signed-equivocation, eclipse isolation), up to
a bounded byzantine fraction and under the topologies exercised below.

**Not claimed:** this is **not BFT** (no consensus, no quorum, no
`f < n/3` proof) and **not unconditionally secure**. It is a set of
targeted moats against three attacks a partition-honest gossip registry
(`gossip`, prior art `#24`) is silently vulnerable to, verified by property
tests, unit tests, and end-to-end scenario runs -- not a formal proof of
byzantine fault tolerance for the registry layer as a whole.

## What was tested

- **Unit tests** -- `test_byzantine_gossip.py`: signature verification,
  forgery/impersonation rejection, replay-under-forged-version, tombstone
  flip, equivocation detection + quarantine, no-false-positive guards
  (honest multi-write history, idempotent retransmission), eclipse-resistant
  sampling (adversarial seed + determinism).
- **Validator unit tests** -- `test_registry_byzantine_validators.py`: each
  of the three validators against hand-built "reference-style" evidence
  (proving it FAILs) and hand-built "`byzantine_gossip`-style" evidence
  (proving it PASSes), including the unverifiable-is-a-FAIL guard.
- **Property tests** (Hypothesis) -- `test_byzantine_gossip_properties.py`,
  30 tests: forged cards never accepted (7-kind attack enum), honest
  sub-network convergence, equivocation always caught with no false
  positives, same-seed determinism (byte-identical canonical-JSON hash), an
  adversarial-fraction sweep (`f/N` up to `floor((N-1)/2)/N` at `N=9`,
  seeds 42/7/1337/`0xDEADBEEF`), and 6 explicit edge cases.
- **End-to-end scenario gate** -- `test_byzantine_gossip_scenario.py`, 30
  tests: each of the three scenario YAMLs run under both `registry: gossip`
  and `registry: byzantine_gossip` (same YAML, same seed, only the plugin
  differs), across seeds 42/7/1337, asserting the FAIL/PASS matrix below
  plus two attack-specific "did the phantom card actually land/not land"
  companion tests and 6 same-seed-identical-trace determinism checks.

## FAIL/PASS matrix

Rows = the 3 mandated validators. Columns = `{in_memory, gossip,
byzantine_gossip}` x `{forgery, signed_equivocation, eclipse}` scenarios.
Captured from an actual run at seed 42 (`ScenarioRunner` + the three
validators, called exactly as the gate test calls them) and cross-checked
against all 30 assertions in `test_byzantine_gossip_scenario.py`, which pass
identically at seeds 7 and 1337.

| Validator                          | in_memory (all 3) | gossip / forgery | gossip / equivocation | gossip / eclipse | byzantine_gossip / forgery | byzantine_gossip / equivocation | byzantine_gossip / eclipse |
|-------------------------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `check_no_forged_card_in_view`      | N/A | **FAIL** | **FAIL**\* | **FAIL**\* | PASS | PASS | PASS |
| `check_no_equivocation_accepted`    | N/A | PASS | **FAIL** | PASS | PASS | PASS | PASS |
| `check_no_eclipse`                  | N/A | PASS | PASS | **FAIL** | PASS | PASS | PASS |

\* `gossip`'s FAIL on `check_no_forged_card_in_view` in the
`signed_equivocation`/`eclipse` scenarios is **structural, not
attack-specific**: `gossip` never signs *anything*, including its own
honest agents' registrations, so every view entry is "unsigned" regardless
of whether a forgery was even attempted in that scenario. The
attack-specific proof for the forgery scenario is the pair of companion
tests below, not this validator's verdict alone.

### `in_memory`: N/A, not PASS -- and why that matters

`in_memory` cannot be substituted into any of these three scenario YAMLs at
all. Attempting `layers.registry: in_memory` against any of them raises,
before a single tick runs:

```
TypeError: InMemoryRegistry.__init__() takes 1 positional argument but 3 were given
```

This is not a missing feature flag -- `InMemoryRegistry` is a **single
globally-shared dictionary** (see `nest_plugins_reference/registry/in_memory.py`
and `gossip_registry.py`'s own docstring: "`in_memory`-style shared-dict
behaviour is impossible by construction" for a per-agent-view design). It
has no `gossip_round`, no `handle_gossip`, no `view_snapshot`, no per-agent
view, no peer sampling, and no equivocation ledger. The three validators in
this module are written against the **distributed-view model** `gossip` and
`byzantine_gossip` share: there is no per-agent "view" to forge a card into,
no peer-to-peer content divergence to equivocate, and no peer sampling to
eclipse -- `in_memory` is a different design point (centralized, no
partition tolerance, no distribution surface at all) with no per-agent
adversarial surface to demonstrate a validator against, not a plugin that
happens to score PASS here. Marking these cells "N/A" rather than "FAIL" is
the honest call: `in_memory` isn't secure against these attacks, it just
isn't *comparable* against them via these validators.

What `test_registry_byzantine_validators.py` *does* establish about
`in_memory` generically (validator-unit level, not a full scenario run): it
never signs anything, so a hand-built "reference-style" unsigned card fails
`check_no_forged_card_in_view` exactly like `gossip`'s does -- see
`test_forged_card_validator_fails_against_reference_style_unsigned_card`.

### Reproducing the matrix

```bash
# The authoritative, committed gate -- 30 tests, all 9 gossip/byzantine_gossip
# matrix cells above, across seeds 42, 7, 1337, plus determinism checks:
uv run pytest packages/nest-plugins-reference/tests/test_byzantine_gossip_scenario.py -v

# The in_memory unit-level evidence (validator-only, no scenario run):
uv run pytest packages/nest-plugins-reference/tests/test_registry_byzantine_validators.py -v
```

To print the literal verdict dict for one scenario/plugin pair directly
(what produced the table above):

```bash
uv run python - <<'PY'
import asyncio, sys
from pathlib import Path
sys.path.insert(0, "packages/nest-plugins-reference/tests")
from test_byzantine_gossip_scenario import (
    _config, _collect_cards, _equivocation_views, _equivocation_ledgers,
)
from nest_core.runner import ScenarioRunner
from nest_plugins_reference.validators.registry_byzantine_validators import (
    check_no_eclipse, check_no_equivocation_accepted, check_no_forged_card_in_view,
)

async def run(yaml_name: str, plugin: str, seed: int = 42) -> None:
    trace = Path(f"/tmp/{yaml_name}.{plugin}.jsonl")
    runner = ScenarioRunner(_config(yaml_name, plugin, trace, seed))
    await runner.run()
    p = runner.resolved_plugins
    regs, ids = p["_byzantine_registries"], p["_byzantine_identities"]
    honest, byz = p["_honest_ids"], p["_byzantine_ids"]
    views = {a: regs[a].view_snapshot() for a in honest}
    cards = await _collect_cards(regs, honest)
    forged = check_no_forged_card_in_view(views, ids, cards).passed
    eqv = check_no_equivocation_accepted(
        _equivocation_ledgers(regs), await _equivocation_views(regs, honest)
    ).passed
    ecl = check_no_eclipse(views, honest, byz).passed
    print(yaml_name, plugin, {"forged": forged, "equivocation": eqv, "eclipse": ecl})

async def main() -> None:
    for y in ("gossip_byzantine_forgery.yaml", "gossip_signed_equivocation.yaml", "gossip_eclipse.yaml"):
        for pl in ("gossip", "byzantine_gossip"):
            await run(y, pl)

asyncio.run(main())
PY
```

Actual output of the snippet above (seed 42, this run):

```
gossip_byzantine_forgery.yaml   gossip            {'forged': False, 'equivocation': True, 'eclipse': True}
gossip_byzantine_forgery.yaml   byzantine_gossip  {'forged': True, 'equivocation': True, 'eclipse': True}
gossip_signed_equivocation.yaml gossip            {'forged': False, 'equivocation': False, 'eclipse': True}
gossip_signed_equivocation.yaml byzantine_gossip  {'forged': True, 'equivocation': True, 'eclipse': True}
gossip_eclipse.yaml             gossip            {'forged': False, 'equivocation': True, 'eclipse': False}
gossip_eclipse.yaml             byzantine_gossip  {'forged': True, 'equivocation': True, 'eclipse': True}
```

## Honest limitations (every one gathered across the build)

Nothing below was hidden to keep a test green; where a limitation was found,
the test was written to *document* it (e.g.
`test_edge_quarantine_then_honest_recovery`), not to route around it.

1. **Eclipse resistance is heuristic (anchor set), not a proof.** The
   anchor half of `_sample_eclipse_resistant` is *positional* --
   "lexicographically-first `ceil(fanout/2)` `AgentId`s among this agent's
   current peers" -- not identity-vetted. Two concrete consequences:
   - **Pathological topology defeat.** An adversary that controls (or
     Sybils) every one of the lexicographically-first `ceil(fanout/2)`
     `AgentId`s among a specific victim's peers defeats the anchor
     guarantee for that victim entirely -- it degenerates to whatever the
     random half draws. A reputation-/identity-vetted anchor would need a
     trust signal (e.g. `score_average` trust, elsewhere in this repo) that
     is not wired into gossip peer selection.
   - **No cross-round rotation / liveness check.** The anchor set is
     recomputed identically every round from the current peer list (the
     point -- a *stable* contact) -- but if an anchor slot is byzantine, it
     stays byzantine forever. There is no mechanism here that detects an
     anchor peer behaving as a silent black hole and rotates around it.
2. **The eclipse *scenario's* gossip-FAIL is empirically tuned to seeds
   42/7/1337, not a derived bound.** `scenarios/gossip_eclipse.yaml`'s
   parameters (`n_byz=24`, `fanout=2`, `duration: 100 ticks`) were found by
   directly simulating the three mandated seeds and checking the outcome --
   not from a closed-form probability bound. `gossip`'s pure-uniform
   sampling *can* eventually connect the two honest agents given enough
   rounds or a larger fanout; a seed outside `{42, 7, 1337}` is not
   guaranteed to reproduce the FAIL cell in the matrix above.
3. **`InertByzantineDriverAgent` models Sybil dilution (silence), not an
   active-lying adversary.** The eclipse scenario's byzantine agents never
   register, gossip, or answer -- pure absence. A byzantine agent that
   actively lies (claims an empty digest when it has data, replays a stale
   digest, selectively relays to some peers and not others) is a different,
   stronger attack than anything exercised by these three scenarios or by
   the property-test sweep (which also spreads byzantine ids evenly rather
   than adversarially placing them against the anchor heuristic -- see
   limitation 1).
4. **Quarantine is PERMANENT -- a once-equivocating publisher's later
   honest write is still rejected.** This is deliberate, not an oversight:
   `_quarantined` has no expiry or appeal mechanism, and every subsequent
   card from a quarantined `agent_id` is refused (`REASON_QUARANTINED`) on
   sight, without even attempting signature verification -- including a
   perfectly-honest, freshly-and-genuinely-signed card at a later version.
   `test_edge_quarantine_then_honest_recovery` pins this down explicitly.
   The rationale: a publisher proven to have signed conflicting writes once
   cannot be trusted to have stopped, and re-trusting a proven-byzantine
   identity needs a governance decision this plugin does not make on its
   own. A real deployment wanting rehabilitation would need an external,
   explicit un-quarantine action -- there is none here.
   - **Quarantine does not propagate as network state.** A publisher
     quarantined by agent `v` simply stops appearing in `v`'s digest/view;
     downstream peers who only ever pull from `v` never learn *why* that
     publisher disappeared, they just never see it. This is sufficient for
     "never (re)enters an honest view downstream of the witness," but it
     means an agent that never itself directly receives both conflicting
     cards (via any path) will never get its own `equivocations` ledger
     entry for that publisher -- only the direct witness(es) do. The
     validator's bar (`check_no_equivocation_accepted`) is deliberately
     "*some* honest agent's ledger recorded it," not "every honest agent's
     ledger recorded it," for exactly this reason.
5. **`check_no_forged_card_in_view`'s gossip-FAIL is partly structural.**
   `gossip` never signs *anything*, including its own honest agents' own
   registrations -- so this validator FAILs under `gossip` in every
   scenario regardless of whether an actual forgery attempt is present (see
   the matrix footnote above). This is a real property of the validator
   (documented on its own docstring since Task 5), not a bug introduced
   later, but it means the validator's FAIL cell alone conflates "gossip
   never signs" with "the injected phantom cards were specifically
   accepted." The forgery gate test now asserts the attack-specific fact
   directly and separately (`test_reference_gossip_accepts_phantom_cards` /
   `test_byzantine_gossip_rejects_phantom_cards`): the forger's exact
   phantom ids land in every honest view under `gossip` and are absent
   from, and recorded in `rejections` for, every honest view under
   `byzantine_gossip` -- a causally clean discriminator that does not
   depend on the validator's structural blind spot.
6. **A quarantine reason-code precision nit (harmless).** In
   `ByzantineGossipRegistry.handle_gossip`, the quarantine check
   (`if card.agent_id in self._quarantined`) runs *before* signature
   verification for every `OP_PUSH` entry. So a forged/badly-signed card
   arriving under an `agent_id` that is *already* quarantined for an
   unrelated prior equivocation gets logged as `REASON_QUARANTINED`, not
   `REASON_BAD_SIGNATURE` -- even though the card would also have failed
   signature verification on its own merits. The card is rejected either
   way (never applied), so this has no effect on any validator's PASS/FAIL
   verdict or on what lands in a view; it only means `rejections`' reason
   code for that specific card undercounts `bad_signature` in favor of
   `quarantined` once a publisher is already quarantined. Not fixed here
   because fixing it (checking signature first, quarantine second) would
   mean doing full cryptographic verification work for a publisher already
   known-byzantine on every subsequent card it ever sends, for a
   cosmetic-only benefit.
7. **`check_no_equivocation_accepted` cannot work from bare
   `ViewSnapshot` data alone.** Two conflicting cards signed by the same
   publisher at the same version produce byte-identical `(version,
   publisher_id, tombstone)` tuples by construction -- that is what
   equivocation *is*. The validator requires the richer `EquivocationView`
   shape (adds a `content_hash` per entry); a caller wiring it from
   `view_snapshot()` alone gets a validator that can never detect anything.
   - **Tombstone gap:** `content_hash` sourced via `reg.lookup()` (as the
     scenario gate does) is only available for live entries, since
     `lookup()` filters tombstones out. `byzantine_gossip`'s own witness
     map still catches a live-card-vs-tombstone equivocation internally (it
     hashes the full write, tombstone included) -- but a caller building
     `EquivocationView` purely from `lookup()` output would miss supplying
     a hash for the tombstoned side and could show a false negative in that
     specific sub-case. Not exercised by the three demo scenarios.
8. **`check_no_forged_card_in_view`'s `cards` parameter assumes one
   physical card instance circulates per agent id.** If an adversary
   crafted *different* forged cards for different specific viewers (rather
   than one forged card broadcast identically to everyone), a flat
   `cards: dict[AgentId, AgentCard]` cannot represent that -- it would need
   to be keyed by `(viewer, agent_id)`. The flatter shape matches the
   realistic gossip threat model actually exercised here (the same wire
   bytes propagate peer-to-peer, and `lookup()` naturally gives you this
   shape), but it is an assumption, not a proof that per-viewer forgery is
   impossible to construct against this validator.
9. **`test_adversarial_fraction_sweep`'s convergence bound
   (`_SWEEP_ROUNDS=24`) is empirical, not derived.** The round count needed
   for the honest sub-network to converge at the worst tested byzantine
   fraction was reasoned through informally (anchor/random split for the
   fixed `agentNN` naming scheme) then confirmed by direct simulation, not
   from a closed-form bound. Changing `_SWEEP_N` or the byzantine-index
   spread formula may require re-tuning this constant; it is not adaptive.
10. **Validators are trace/snapshot-evidence-bounded, like every NANDA Town
    validator.** All three validators here are pure functions over
    per-agent evidence (view snapshots, cards, ledgers) supplied by the
    caller -- they judge what appears in that evidence, not the ground
    truth of a run. `check_no_forged_card_in_view` makes this explicit by
    treating "cannot be checked" (`unverifiable`) as a FAIL rather than a
    silent pass (limitation 8's `cards`/`identities` under-population is
    exactly the failure mode this guards against), but the general
    principle holds for all three: absence of evidence is not evidence of
    safety, and evidence outside what was captured (a trace, a snapshot, a
    ledger) is simply not seen.

## Relation to prior art

- **Extends `#24`** (merged gossip registry: partition-honesty, eventual
  convergence under network partitions). `byzantine_gossip` reuses `#24`'s
  wire format, `GossipNetwork`, write-tag ordering, and merge logic
  wholesale -- it adds signing/verification, equivocation witnessing, and
  eclipse-resistant sampling on top, it does not replace `#24`'s honest-path
  behavior.
- **Complementary to `#67`** (registration-only card signing). `#67`
  signs a card once, at registration, at the source. That is necessary but
  not sufficient for gossip: nothing downstream re-checks a card as it
  hops through the mesh (a compromised relay can still forge/mutate it),
  and even a card that *is* validly signed by its real publisher provides
  no defense if that publisher itself signs two different cards at the same
  version -- `#67`'s check runs once, against the card in isolation, and
  would accept either equivocating card without complaint. The novel
  invariant this plugin adds is exactly that gap: **a validly-signed
  equivocator still poisons the network**, which registration-signing
  cannot prevent by construction, only re-verification-on-every-hop plus
  cross-write witnessing can.
