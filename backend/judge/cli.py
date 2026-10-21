"""Command line for trying the assistant on real repos.

    python -m judge.cli check  https://github.com/OWNER/REPO
    python -m judge.cli review https://github.com/OWNER/REPO --video https://youtu.be/ID
    python -m judge.cli similar URL1 URL2 [URL3 ...]

For a project built before today, pass --start/--deadline (ISO times) so the
"built on the day" checks use a window that makes sense.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from datetime import datetime

from .config import LONDON, get_settings
from .github_client import GitHubClient
from .integrity import find_similar_pairs, run_checks
from .models import FlagLevel, Review, Submission
from .pipeline import review_submission


def _settings(args):
    settings = get_settings()
    if args.start:
        settings = replace(settings, event_start=datetime.fromisoformat(args.start).replace(tzinfo=LONDON))
    if args.deadline:
        settings = replace(settings, submission_deadline=datetime.fromisoformat(args.deadline).replace(tzinfo=LONDON))
    return settings


def _print_flags(flags) -> None:
    for f in flags:
        mark = "OK   " if f.level == FlagLevel.ok else "CHECK"
        print(f"  [{mark}] {f.check}: {f.detail}")


def _print_review(review: Review) -> None:
    s = review.submission
    print(f"\n{s.project_name}  ·  {s.team_name}\n{'=' * 60}")
    print("\nChecks")
    _print_flags(review.integrity.flags)
    b = review.brief
    if b:
        print(f"\n{b.one_liner}\n\nWhat they built\n  {b.what_they_built}\n\nWho it's for\n  {b.who_its_for}")
        print("\nHow it uses ADK")
        for e in b.how_it_uses_adk:
            print(f"  - {e.point}" + (f"  ({e.where})" if e.where else ""))
        print("\nWhat the demo shows")
        for e in b.what_the_demo_shows:
            print(f"  - {e.where + '  ' if e.where else ''}{e.point}")
        print("\nStrengths")
        for x in b.strengths:
            print(f"  - {x}")
        print("\nGaps")
        for x in b.gaps:
            print(f"  - {x}")
        print("\nQuestions to ask in the pitch")
        for i, q in enumerate(b.pitch_questions, 1):
            print(f"  {i}. {q}")
    for err in review.errors:
        print(f"\n! {err}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judge")
    parser.add_argument("--start", help="Override event start, e.g. 2026-10-21T09:00")
    parser.add_argument("--deadline", help="Override deadline, e.g. 2026-10-21T16:00")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="Integrity checks only (no Gemini key needed)")
    p_check.add_argument("repo")

    p_review = sub.add_parser("review", help="Full brief for judges")
    p_review.add_argument("repo")
    p_review.add_argument("--video", default="")
    p_review.add_argument("--team", default="Test team")
    p_review.add_argument("--name", default="")
    p_review.add_argument("--json", action="store_true", help="Print raw JSON")

    p_sim = sub.add_parser("similar", help="Compare repos for copied code")
    p_sim.add_argument("repos", nargs="+")

    args = parser.parse_args(argv)
    settings = _settings(args)

    if args.cmd == "check":
        with GitHubClient(settings.github_token) as gh:
            snap = gh.snapshot(args.repo)
        report = run_checks(snap, None, settings.event_start, settings.submission_deadline)
        print(f"{snap.url}  ({len(snap.commits)} commits, {len(snap.files)} files read)")
        _print_flags(report.flags)
        return 0

    if args.cmd == "similar":
        with GitHubClient(settings.github_token) as gh:
            snaps = {url: gh.snapshot(url) for url in args.repos}
        pairs = find_similar_pairs(snaps, threshold=0.0)
        for a, b, score in pairs:
            print(f"{score:5.0%}  {a}  <->  {b}")
        return 0

    submission = Submission(team_name=args.team, project_name=args.name or args.repo.rstrip("/").split("/")[-1], repo_url=args.repo, video_url=args.video)
    review = asyncio.run(review_submission(submission, settings))
    if args.json:
        print(json.dumps(review.model_dump(mode="json"), indent=2))
    else:
        _print_review(review)
    return 1 if review.errors else 0


if __name__ == "__main__":
    sys.exit(main())
