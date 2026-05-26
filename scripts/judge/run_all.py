# SPDX-License-Identifier: Apache-2.0
"""CLI that scores every open ``hackathon/*`` PR and writes ``scores.json``.

The output is idempotent: re-running only re-scores PRs whose HEAD SHA has
changed. If ``ANTHROPIC_API_KEY`` is unset, the CLI falls back to a
:class:`MockJudgeClient` so the schema is exercised end-to-end without
spending budget; this is intended for CI smoke and for first-bootstrap.

Usage::

    uv run python -m scripts.judge.run_all --output docs/hackathon/scores.json
    uv run python -m scripts.judge.run_all --mock         # force mock judges
    uv run python -m scripts.judge.run_all --pr 2 --pr 3  # subset

Example::

    python -m scripts.judge.run_all --mock --output /tmp/scores.json
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from scripts.judge.judge_pr import (
    GITHUB_API,
    PRContext,
    _gh_get,  # pyright: ignore[reportPrivateUsage]
    fetch_pr_context,
    infer_layer,
    infer_persona,
    judge_pr,
)

SCOREBOARD_VERSION = 1


# --------------------------------------------------------------------------- #
# Mock judge — used when ANTHROPIC_API_KEY is unset (CI smoke) or in tests
# --------------------------------------------------------------------------- #


class MockJudgeClient:
    """Deterministic, content-derived mock judge for offline runs.

    Scores are derived from a hash of (judge_id, head_sha, dimension) so
    re-running produces a stable scoreboard, and different judges produce
    slightly different scores (so aggregation is non-trivial).

    Example::

        client = MockJudgeClient(judge_id=0, head_sha="abc...")
    """

    def __init__(self, *, judge_id: int, head_sha: str) -> None:
        self._judge_id = judge_id
        self._head_sha = head_sha

    async def judge(self, *, system_blocks: list[dict[str, Any]], user: str) -> str:
        # `system_blocks` and `user` are accepted for protocol compatibility.
        del system_blocks
        dims = (
            "correctness",
            "test_rigor",
            "api_fit",
            "docs_quality",
            "novelty",
            "persona_fidelity",
        )
        scores: dict[str, int] = {}
        for dim in dims:
            key = f"{self._head_sha}|{self._judge_id}|{dim}|{len(user) % 97}".encode()
            digest = hashlib.sha256(key).digest()
            scores[dim] = 2 + (digest[0] % 4)  # 2..5 inclusive
        rationale = (
            f"Mock judge {self._judge_id}: deterministic synthetic score. "
            f"This rationale exists only because ANTHROPIC_API_KEY was unset "
            f"or --mock was passed. Re-run with a live key to replace."
        )
        return json.dumps({"scores": scores, "rationale": rationale})


# --------------------------------------------------------------------------- #
# Branch listing
# --------------------------------------------------------------------------- #


def list_hackathon_prs(owner: str, repo: str) -> list[dict[str, Any]]:
    """Return open PRs whose head ref starts with ``hackathon/``.

    Example::

        prs = list_hackathon_prs("mariagorskikh", "nest")
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls?state=open&per_page=100"
    try:
        body = _gh_get(url).decode("utf-8")
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"warning: failed to list PRs ({exc}); returning empty list", file=sys.stderr)
        return []
    data = cast("list[dict[str, Any]]", json.loads(body))
    out: list[dict[str, Any]] = []
    for pr in data:
        head_ref = str(pr.get("head", {}).get("ref", ""))
        if head_ref.startswith("hackathon/"):
            out.append(pr)
    out.sort(key=lambda p: int(p["number"]))
    return out


# --------------------------------------------------------------------------- #
# Score aggregation across the cohort
# --------------------------------------------------------------------------- #


def load_existing(path: Path) -> dict[str, Any]:
    """Read an existing scoreboard or return an empty skeleton.

    Example::

        prior = load_existing(Path("docs/hackathon/scores.json"))
    """
    if not path.exists():
        return {"version": SCOREBOARD_VERSION, "generated_at": "", "submissions": []}
    try:
        data = cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
        if data.get("version") != SCOREBOARD_VERSION:
            return {"version": SCOREBOARD_VERSION, "generated_at": "", "submissions": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"version": SCOREBOARD_VERSION, "generated_at": "", "submissions": []}


def _build_submission(
    *,
    ctx: PRContext,
    result_dict: dict[str, Any],
) -> dict[str, Any]:
    """Project a JudgeResult dict into the public ``scores.json`` shape.

    Example::

        _build_submission(ctx=ctx, result_dict=result.to_dict())
    """
    persona = infer_persona(ctx.head_ref, ctx.title)
    layer = infer_layer(ctx.title, ctx.body)
    return {
        "pr": ctx.number,
        "handle": persona,
        "layer": layer,
        "title": ctx.title,
        "author": ctx.author,
        "head_sha": ctx.head_sha,
        "head_ref": ctx.head_ref,
        "model": result_dict["model"],
        "rubric_version": result_dict["rubric_version"],
        "diff_truncated": result_dict["diff_truncated"],
        "scores": result_dict["scores"],
        "median": result_dict["median"],
        "consensus": result_dict["consensus"],
        "judges": result_dict["judges"],
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def _ctx_from_cache_entry(entry: dict[str, Any]) -> PRContext:
    """Build a PRContext from a pre-fetched JSON cache entry.

    Used when the GitHub API isn't reachable (e.g., CI smoke without a
    GITHUB_TOKEN). The cache file is a list of objects with: ``number``,
    ``title``, ``body``, ``author``, ``head_sha``, ``head_ref``, ``diff``,
    and optional ``checks_summary``.

    Example::

        ctx = _ctx_from_cache_entry({"number": 2, "title": "...", ...})
    """
    from scripts.judge.judge_pr import truncate_diff

    diff_in: str = str(entry.get("diff", ""))
    diff, was_truncated = truncate_diff(diff_in)
    return PRContext(
        number=int(entry["number"]),
        title=str(entry.get("title", "")),
        body=str(entry.get("body", "") or ""),
        author=str(entry.get("author", "")),
        head_sha=str(entry["head_sha"]),
        head_ref=str(entry["head_ref"]),
        diff=diff,
        diff_truncated=was_truncated,
        checks_summary=str(entry.get("checks_summary", "no check runs reported")),
    )


async def _score_one(
    pr_meta: dict[str, Any],
    *,
    owner: str,
    repo: str,
    n_judges: int,
    model: str,
    use_mock: bool,
    cache_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch PR context and run the judges, returning the submission dict.

    If ``cache_entry`` is provided, the GitHub API is skipped entirely.

    Example::

        sub = await _score_one(pr_meta, owner="o", repo="r", ...)
    """
    pr_number = int(pr_meta["number"])
    if cache_entry is not None:
        ctx = _ctx_from_cache_entry(cache_entry)
    else:
        ctx = fetch_pr_context(pr_number, owner=owner, repo=repo)
    if use_mock:
        # One MockJudgeClient *per judge* so each judge gets its own seed.
        # judge_pr only takes a single client, so we run judges in a loop here
        # to give each its own mock instance while still using asyncio.gather.
        from scripts.judge.judge_pr import (
            _build_user_prompt,  # pyright: ignore[reportPrivateUsage]
            _system_blocks,  # pyright: ignore[reportPrivateUsage]
            aggregate,
            load_rubric,
            parse_verdict,
        )

        rubric = load_rubric()
        system_blocks = _system_blocks(rubric)
        user_prompt = _build_user_prompt(ctx)

        async def one(judge_id: int) -> Any:
            client = MockJudgeClient(judge_id=judge_id, head_sha=ctx.head_sha)
            raw = await client.judge(system_blocks=system_blocks, user=user_prompt)
            return parse_verdict(raw, judge_id)

        verdicts = list(await asyncio.gather(*(one(i) for i in range(n_judges))))
        result = aggregate(
            verdicts,
            ctx,
            model=f"mock:{model}",
            persona=infer_persona(ctx.head_ref, ctx.title),
        )
    else:
        result = await judge_pr(
            pr_number,
            n_judges=n_judges,
            model=model,
            owner=owner,
            repo=repo,
            ctx=ctx,
        )
    return _build_submission(ctx=ctx, result_dict=result.to_dict())


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score open hackathon PRs.")
    parser.add_argument("--owner", default="mariagorskikh")
    parser.add_argument("--repo", default="nest")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/hackathon/scores.json"),
        help="Path to write the scoreboard JSON.",
    )
    parser.add_argument("--n-judges", type=int, default=3)
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument(
        "--pr",
        type=int,
        action="append",
        default=None,
        help="Limit to specific PR number(s); may be repeated.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force the mock judge (also auto-enabled if ANTHROPIC_API_KEY is unset).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-score every PR even if the head SHA matches a prior run.",
    )
    parser.add_argument(
        "--prs-cache",
        type=Path,
        default=None,
        help=(
            "Path to a pre-fetched PR cache JSON (list of {number, title, body, "
            "author, head_sha, head_ref, diff}). When provided, the GitHub API "
            "is not called. Useful for offline CI smoke runs."
        ),
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    use_mock = bool(args.mock or not os.environ.get("ANTHROPIC_API_KEY"))
    if use_mock and not args.mock:
        print(
            "ANTHROPIC_API_KEY not set; using deterministic mock judges. "
            "Output will be marked accordingly.",
            file=sys.stderr,
        )

    cache_by_pr: dict[int, dict[str, Any]] = {}
    if args.prs_cache:
        cache_data = cast(
            "list[dict[str, Any]]",
            json.loads(Path(args.prs_cache).read_text(encoding="utf-8")),
        )
        cache_by_pr = {int(cast("int", e["number"])): e for e in cache_data}
        prs = [
            {"number": e["number"], "head": {"sha": e["head_sha"], "ref": e["head_ref"]}}
            for e in cache_data
        ]
    else:
        prs = list_hackathon_prs(args.owner, args.repo)
    if args.pr:
        wanted = {int(cast("int", p)) for p in args.pr}
        prs = [p for p in prs if int(cast("int", p["number"])) in wanted]
    if not prs:
        print("no open hackathon/* PRs found; nothing to score", file=sys.stderr)
        return 0

    existing = load_existing(args.output)
    prior_by_pr = {int(cast("int", s["pr"])): s for s in existing.get("submissions", [])}

    submissions: list[dict[str, Any]] = []
    for pr_meta in prs:
        pr_number = int(cast("int", pr_meta["number"]))
        head_sha = str(cast("dict[str, Any]", pr_meta["head"])["sha"])
        prior = prior_by_pr.get(pr_number)
        if (
            prior is not None
            and not args.force
            and prior.get("head_sha") == head_sha
            and prior.get("model", "").startswith("mock:") == use_mock
        ):
            print(f"PR #{pr_number}: head SHA unchanged, reusing prior score", file=sys.stderr)
            submissions.append(prior)
            continue
        print(f"PR #{pr_number}: scoring (mock={use_mock})", file=sys.stderr)
        try:
            sub = await _score_one(
                pr_meta,
                owner=args.owner,
                repo=args.repo,
                n_judges=args.n_judges,
                model=args.model,
                use_mock=use_mock,
                cache_entry=cache_by_pr.get(pr_number),
            )
            if sub.get("diff_truncated"):
                print(
                    f"PR #{pr_number}: diff was truncated (some file exceeded 5000 lines)",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001 - one PR's failure shouldn't sink the run
            print(f"PR #{pr_number}: FAILED ({exc})", file=sys.stderr)
            if prior is not None:
                submissions.append(prior)
            continue
        submissions.append(sub)

    submissions.sort(key=lambda s: int(s["pr"]))
    scoreboard = {
        "version": SCOREBOARD_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "mock": use_mock,
        "submissions": submissions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scoreboard, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(submissions)} submissions to {args.output}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Example::

        sys.exit(main(["--mock", "--output", "/tmp/scores.json"]))
    """
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(_main_async(args))


# pragma: explicitly re-export the helper used in tests
__all__ = [
    "MockJudgeClient",
    "list_hackathon_prs",
    "load_existing",
    "main",
]


# Reference asdict so 'pyright --strict' doesn't flag the import as unused;
# the symbol is here so downstream tooling can use it on judge dataclasses.
_ = asdict


if __name__ == "__main__":
    sys.exit(main())
