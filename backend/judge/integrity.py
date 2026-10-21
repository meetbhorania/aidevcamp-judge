"""Integrity checks. Plain code, no AI, so the results are predictable and explainable.

A failed check never removes a team. It only marks the project for a judge to look at.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from itertools import combinations

from .config import LONDON
from .models import FlagLevel, IntegrityFlag, IntegrityReport, RepoSnapshot, Submission

START_GRACE = timedelta(minutes=15)
LATE_WINDOW = timedelta(minutes=30)
LATE_SHARE = 0.6
SIMILARITY_THRESHOLD = 0.6


def _local(dt: datetime) -> str:
    return dt.astimezone(LONDON).strftime("%-I:%M%p %d %b").replace("AM", "am").replace("PM", "pm")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _ok(check: str, detail: str) -> IntegrityFlag:
    return IntegrityFlag(check=check, level=FlagLevel.ok, detail=detail)


def _flag(check: str, detail: str) -> IntegrityFlag:
    return IntegrityFlag(check=check, level=FlagLevel.check, detail=detail)


# ---------- Built on the day ----------

def check_build_window(snap: RepoSnapshot, start: datetime, deadline: datetime) -> list[IntegrityFlag]:
    flags: list[IntegrityFlag] = []
    earliest_allowed = start - START_GRACE

    if snap.created_at < earliest_allowed:
        flags.append(_flag("Built on the day", f"Repo was created at {_local(snap.created_at)}, before the event started."))

    early_pushes = [t for t in snap.push_times if t < earliest_allowed]
    if early_pushes:
        flags.append(_flag("Built on the day", f"{len(early_pushes)} push(es) to GitHub before 9:00am, first at {_local(early_pushes[0])}."))

    early_commits = [c for c in snap.commits if c.authored_at < earliest_allowed]
    if early_commits:
        flags.append(
            _flag(
                "Built on the day",
                f"{len(early_commits)} commit(s) dated before the event. Commit dates can be set locally, so check with the team.",
            )
        )

    late_pushes = [t for t in snap.push_times if t > deadline]
    if late_pushes:
        flags.append(_flag("Submitted on time", f"Code was pushed after 4:00pm (last at {_local(late_pushes[-1])}). Judge the version from before the deadline."))

    if not flags and snap.commits:
        first = min(c.authored_at for c in snap.commits)
        last = max(c.authored_at for c in snap.commits)
        flags.append(_ok("Built on the day", f"Repo created {_local(snap.created_at)}, {_plural(len(snap.commits), 'commit')} between {_local(first)} and {_local(last)}."))
    return flags


# ---------- Everything uploaded at the last minute ----------

def check_late_bulk_upload(snap: RepoSnapshot, deadline: datetime) -> list[IntegrityFlag]:
    with_stats = [c for c in snap.commits if c.additions is not None]
    if not with_stats:
        return []
    total = sum(c.additions for c in with_stats)
    if total == 0:
        return []
    late = sum(c.additions for c in with_stats if deadline - LATE_WINDOW <= c.authored_at <= deadline + timedelta(minutes=5))
    share = late / total
    if share >= LATE_SHARE and total > 200:
        biggest = max(with_stats, key=lambda c: c.additions)
        return [
            _flag(
                "Steady progress",
                f"{share:.0%} of all added lines arrived in the last 30 minutes. Biggest commit: {biggest.additions} lines at {_local(biggest.authored_at)}.",
            )
        ]
    if len(snap.commits) <= 2 and total > 500:
        return [_flag("Steady progress", f"Only {len(snap.commits)} commit(s) for {total} lines. Work may have been done elsewhere.")]
    return [_ok("Steady progress", f"Work spread across {_plural(len(snap.commits), 'commit')}.")]


# ---------- Forks ----------

def check_fork(snap: RepoSnapshot) -> list[IntegrityFlag]:
    if snap.is_fork:
        return [_flag("Original repo", f"This repo is a fork of {snap.fork_parent or 'another project'}. Check what the team added.")]
    return [_ok("Original repo", "Not a fork.")]


# ---------- Hidden instructions ----------

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier|other)\s+(instructions|prompts?|rules)",
    r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)",
    r"(you\s+are|act\s+as|pretend\s+to\s+be)\s+(now\s+)?(an?\s+)?(ai\s+)?(judge|evaluator|grader|reviewer)",
    r"(give|award|assign|rate|score)\s+(this|our|the)?\s*(project|submission|team|repo)?\s*(a\s+)?(10\s*/\s*10|5\s*/\s*5|100\s*/\s*100|full\s+marks|top\s+(score|marks)|the\s+highest|maximum|first\s+place)",
    r"(note|message|instructions?)\s+(to|for)\s+(the\s+)?(ai|llm|language\s+model|judge|judging\s+(agent|system|assistant))",
    r"system\s+prompt",
    r"this\s+(project|submission)\s+(must|should)\s+(win|be\s+ranked|rank)",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
_INVISIBLE = {"Cf"}  # format characters: zero-width spaces, direction overrides, tags


def find_hidden_instructions(text: str) -> list[str]:
    """Return short quotes of anything that looks like an attempt to instruct the reviewer."""
    hits: list[str] = []
    for match in _INJECTION_RE.finditer(text):
        lo, hi = max(0, match.start() - 40), min(len(text), match.end() + 40)
        hits.append(" ".join(text[lo:hi].split()))
    return hits


def count_invisible_chars(text: str) -> int:
    return sum(1 for ch in text if unicodedata.category(ch) in _INVISIBLE and ch not in "﻿")


def check_hidden_instructions(snap: RepoSnapshot, submission: Submission | None = None) -> list[IntegrityFlag]:
    sources: list[tuple[str, str]] = [("README", snap.readme)]
    sources += [(f.path, f.content) for f in snap.files]
    sources += [("commit messages", "\n".join(c.message for c in snap.commits))]
    if submission:
        sources.append(("submission form", f"{submission.summary}\n{submission.problem}"))

    flags: list[IntegrityFlag] = []
    for where, text in sources:
        if not text:
            continue
        for quote in find_hidden_instructions(text)[:3]:
            flags.append(_flag("No hidden instructions", f'In {where}: "{quote}"'))
        invisible = count_invisible_chars(text)
        if invisible >= 3:
            flags.append(_flag("No hidden instructions", f"{where} contains {invisible} invisible characters. Text may be hidden."))
        if where == "README":
            for comment in _HTML_COMMENT_RE.findall(text):
                if find_hidden_instructions(comment) or re.search(r"\b(ai|llm|judge|score)\b", comment, re.IGNORECASE):
                    flags.append(_flag("No hidden instructions", f'Hidden HTML comment in README: "{" ".join(comment.split())[:160]}"'))
    if not flags:
        flags.append(_ok("No hidden instructions", "Nothing found in the README, code, commits or form."))
    return flags


# ---------- Copied between submissions ----------

def _shingles(snap: RepoSnapshot, size: int = 3) -> set[int]:
    lines: list[str] = []
    for f in snap.files:
        if not f.path.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
            continue
        for line in f.content.splitlines():
            norm = " ".join(line.split()).lower()
            if len(norm) < 12 or norm.startswith(("import ", "from ", "#", "//", '"""')):
                continue
            lines.append(norm)
    return {hash("\n".join(lines[i : i + size])) for i in range(max(0, len(lines) - size + 1))}


def similarity(a: RepoSnapshot, b: RepoSnapshot) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def find_similar_pairs(snaps: dict[str, RepoSnapshot], threshold: float = SIMILARITY_THRESHOLD) -> list[tuple[str, str, float]]:
    """Compare every pair of submissions. Returns (team_a, team_b, overlap) above the threshold."""
    pairs = []
    for (ta, a), (tb, b) in combinations(snaps.items(), 2):
        score = similarity(a, b)
        if score >= threshold:
            pairs.append((ta, tb, score))
    return sorted(pairs, key=lambda p: -p[2])


# ---------- All checks for one project ----------

def run_checks(snap: RepoSnapshot, submission: Submission | None, start: datetime, deadline: datetime) -> IntegrityReport:
    flags = []
    flags += check_build_window(snap, start, deadline)
    flags += check_late_bulk_upload(snap, deadline)
    flags += check_fork(snap)
    flags += check_hidden_instructions(snap, submission)
    if not snap.commits:
        flags.append(_flag("Has code", "The repo has no commits."))
    return IntegrityReport(flags=flags)
