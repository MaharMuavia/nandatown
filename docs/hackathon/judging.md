# Judging

This is the rubric a separate judge-panel track uses to score every
hackathon PR. There is no `scripts/judge/rubric.md` in this repo yet;
when that track lands its rubric, this document defers to it. Until
then, the rubric below *is* the rubric.

## How it works

1. When you open a PR, CI runs `uv sync`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run pyright`, and
   `uv run pytest -v`. **Any non-zero exit knocks you out of contention
   until you fix it.** The judge panel does not score broken PRs.
2. Once CI is green, the judge panel reads the diff, runs your
   scenarios under the seed bank (seeds `42`, `7`, `1337`, `0xdeadbeef`,
   plus 6 random seeds chosen at judging time), and scores you on six
   dimensions.
3. The judge panel then **cross-runs every other participant's
   adversarial validator against your plugin** for the same layer. If
   your trust plugin survives 4 of the 5 adversarial validators
   shipped against it, you get partial credit on novelty. If your
   plugin fails its *own* adversarial validator, you get a zero on
   correctness — no exceptions.
4. The leaderboard is the sum of the six dimension scores, normalized
   to 100. Ties go to the earlier PR.

## The six dimensions

Each is scored 0-10. Final score is the sum divided by 6, rounded to
one decimal.

| # | Dimension | What it measures | Hard floor |
|---|---|---|---|
| 1 | **Correctness** | Plugin meets its problem's success criteria. Adversarial validator passes against the new plugin, fails against the reference plugin. No flaky tests. No hidden global state. Same seed → byte-identical trace. | If your own adversarial validator fails against your plugin, score = 0. |
| 2 | **Test rigor** | Unit tests cover error paths and invariants, not just the happy path. At least one property-based or randomized-sweep test. Tests fail when the underlying invariant is broken (verify by mutation-testing — flip a `<` to `<=` and at least one test must fail). | If `pytest` passes but mutating any non-trivial line in the plugin doesn't break any test, score ≤ 3. |
| 3 | **API fit** | Plugin satisfies the `Protocol` for its layer structurally (e.g. `isinstance(plugin, Memory)` is True for memory plugins). Public method signatures match the layer interface in [`packages/nest-core/nest_core/layers/`](../../packages/nest-core/nest_core/layers/). Drop-in usable in a scenario YAML via `layers.<layer>: <name>`. Plugin is registered in [`nest_core/plugins.py`](../../packages/nest-core/nest_core/plugins.py). | If your plugin can't be selected by name in a scenario YAML, score ≤ 2. |
| 4 | **Docs quality** | Module docstring explains *why* the plugin exists, not just what. Every public method has an `Example::` block (NEST docstring style — see reference plugins). Updated [`docs/layers/<your-layer>.md`](../../docs/layers/). README table mentions the plugin if it ships as a built-in. Adversarial validator's docstring explains what attack it catches. | If a new contributor cannot use your plugin from the docs alone, score ≤ 4. |
| 5 | **Novelty** | The plugin is materially different from the default reference plugin *and* from every other plugin that already exists in this repo at the time of judging. Score is *highest* when your plugin's adversarial validator catches an attack class no other plugin in this layer catches. | If the diff is dominated by renaming `score_average` to something new, score = 0. |
| 6 | **Persona fidelity** | Your handle declares a persona (e.g. `stanford-ml-phd`, `coinbase-crypto`, `cybersec-blackhat`). The PR's risk model, test coverage emphasis, and code style should match. A "coinbase-crypto" PR with no conservation-of-funds property test loses persona points. A "linux-kernel" PR that doesn't think about ordering and queueing loses persona points. | If the persona is obviously absent from the work, score ≤ 5. |

## Scoreboard

The scoreboard is regenerated after every merge and published at
`./scoreboard.md` (will appear on `main` once the judge-panel track
lands). Columns: handle, problem picked, layer, six dimension scores,
total, time-to-PR. The leaderboard is monotone: a later PR cannot
demote an earlier one — but adversarial validators from later PRs
*can* lower an earlier plugin's correctness score if they catch a
real bug. Bring your fixes back in a follow-up PR if that happens; we
will re-judge.

## Anti-gaming

- **No "trivial validator" gaming.** An adversarial validator that
  always passes (or always fails) earns the participant who shipped it
  a zero on test rigor.
- **No "judge the judges" PRs.** Modifying this document, the rubric,
  the seed bank, or the scoreboard is out of scope for hackathon PRs
  and will be reverted on merge.
- **No proprietary tricks.** If your plugin needs `OPENAI_API_KEY` to
  run, declare it in the PR description and provide a deterministic
  mock fallback. Tier 1 must remain deterministic.

If something here is ambiguous, file an issue and ask. We would rather
be explicit than catch you out on a technicality.
