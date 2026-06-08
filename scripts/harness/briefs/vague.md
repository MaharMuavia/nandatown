# Nanda Town Hackathon Brief — Vague Track

You are participating in the Nanda Town research hackathon.

**Task**: Improve Nanda Town. Submit a pull request to
https://github.com/projnanda/nandatown.

That's it. Pick whatever you think is most valuable. Open a PR against `main`
from a branch named `hackathon/<your-handle>-<topic>`.

## Submission rules

- Stay in your own branch. Do not push to `main`, `master`, `hackathon/*`
  (other people's branches), or `claude/*`.
- Run the local checks before you push:
  - `uv sync`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pyright`
  - `uv run pytest -v`
- Open one PR. Include in the PR body what you did and why.
