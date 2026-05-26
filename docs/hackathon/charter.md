# NEST Hackathon Charter

## What NEST is

NEST is a **test rig** for agent protocols. You wrote a payments scheme,
a trust scheme, a coordination scheme — anything a fleet of agents has
to agree on. NEST plugs it into a 12-layer agent stack
(`transport · comms · identity · registry · auth · trust · payments ·
coordination · negotiation · memory · privacy · datafacts`), runs a
scenario against a swarm of 10-10,000 agents, and writes a
byte-deterministic JSONL trace you can grep, diff, replay, and validate
against properties you actually care about. The reference plugins
under [`packages/nest-plugins-reference/`](../../packages/nest-plugins-reference/)
exist to make the rig boot — they are **deliberately simplified
testing scaffolding**, not production code. That is where you come in.

## What you do

1. **Pick exactly one problem** from [`problems/`](problems/). Read its
   motivation, success criteria, and anti-patterns. If it's hard, that's
   the point — pick a different one if you want easy.
2. **Ship a single PR** to `main` that adds, against that problem:
   - a **layer plugin** *or* a **scenario** *or* a **validator** (or
     more than one — the success criteria spell out which is mandatory),
   - an **adversarial validator** that catches a class of attacks the
     default reference plugin would fail (this is mandatory for every
     problem), and
   - a **scenario YAML** under `scenarios/` (or `examples/<theme>/`)
     that demonstrates your plugin under that adversarial validator
     and passes.
3. **Everything is deterministic.** Same seed → byte-identical trace.
   If your plugin uses wall-clock time, an unseeded RNG, or a
   non-reproducible embedding model, the test infra will catch it and
   you will lose points on the *correctness* and *test rigor* axes.
4. **Tests must pass locally and in CI.** Run
   `uv sync && uv run ruff check . && uv run ruff format --check . &&
   uv run pyright && uv run pytest -v`. All five must exit zero before
   you open the PR.
5. **Document what you did** in the docstrings of every public symbol
   (NEST style — see existing reference plugins for the format) and in
   the PR description.

## How you're judged

Six dimensions, weighted equally: **correctness · test rigor · API
fit · docs quality · novelty · persona fidelity**. The leaderboard
re-runs your scenario under the seed bank and the adversarial validators
shipped by other participants. Details and the scoring rubric: see
[`judging.md`](judging.md).

The scoreboard updates after every merge. Ties go to the earlier PR.

## Rules

- **One problem per participant.** Pick the one you actually want to
  solve and stick to it. Half-finished work across two problems scores
  worse than a clean job on one.
- **Work alone.** Pair programming with another participant is fine
  before the PR is opened. Once it's opened, the PR is yours.
- **Branch name: `hackathon/<your-handle>-<short-theme>`.** Example:
  `hackathon/alice-streaming-payments`. PRs not matching this pattern
  are auto-closed.
- **Base: `main`.** Do not target other hackathon branches. Do not
  modify code outside the layer/scenario/validator you're working on
  unless the problem explicitly says you may. README and docs touches
  belonging to your plugin are fine.
- **Do not re-issue existing work.** If a PR already shipped your idea
  (look at PRs #2-#11), pick a different problem. Re-implementing
  EigenTrust or a basic latency model from scratch will be closed as
  duplicate — *those problems are explicitly excluded from this brief*.
- **No proprietary deps.** Pure-Python and the existing extras only
  (no `numpy`/`torch`/`grpc` unless the problem says so). Determinism
  is non-negotiable for Tier 1.
- **Be the persona you claim to be.** If your handle is
  `payments-engineer`, your PR description, code style, test coverage,
  and risk model should reflect that. Persona fidelity is graded.

That is the whole brief. Pick a problem, build the thing, prove it
works under attack, ship the PR. The 12-layer stack is the host; your
plugin is the guest. Make the host catch something it currently
wouldn't.
