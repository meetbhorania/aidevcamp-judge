"""Reads a public GitHub repo: metadata, commits, push times and the most useful files.

We never clone or run participants' code. Everything is read through the GitHub API.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx

from .models import CommitInfo, RepoFile, RepoSnapshot

API = "https://api.github.com"

# Files are read in priority order until these budgets run out.
MAX_FILES = 40
MAX_FILE_CHARS = 20_000
MAX_TOTAL_CHARS = 150_000
MAX_COMMITS = 300
MAX_COMMIT_STATS = 50

SKIP_DIRS = ("node_modules/", ".venv/", "venv/", "__pycache__/", ".git/", "dist/", "build/", ".next/", "site-packages/")
SKIP_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock")
CONFIG_FILES = ("requirements.txt", "pyproject.toml", "package.json", "setup.py", "Dockerfile", ".env.example")
CODE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".yaml", ".yml", ".toml", ".md")

_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?(?:[#?].*)?$")


class GitHubError(Exception):
    pass


def parse_repo_url(url: str) -> tuple[str, str]:
    """Turn 'https://github.com/owner/repo' into ('owner', 'repo')."""
    match = _URL_RE.match(url.strip())
    if not match:
        raise GitHubError(f"Not a GitHub repo link: {url!r}")
    return match.group(1), match.group(2)


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def file_priority(path: str) -> int | None:
    """Lower is more important. None means skip the file."""
    lower = path.lower()
    if any(part in lower for part in SKIP_DIRS) or lower.rsplit("/", 1)[-1] in SKIP_FILES:
        return None
    name = lower.rsplit("/", 1)[-1]
    if name in (c.lower() for c in CONFIG_FILES):
        return 0
    if not lower.endswith(CODE_EXTS):
        return None
    if lower.endswith(".md"):
        return 6 if name != "readme.md" else None  # README is read separately
    score = 3
    if "agent" in lower:
        score = 1
    elif any(word in lower for word in ("tool", "main", "app", "server", "prompt")):
        score = 2
    if "test" in lower:
        score += 2
    return score


def select_paths(paths: list[str]) -> list[str]:
    ranked = [(p, file_priority(p)) for p in paths]
    kept = [(p, s) for p, s in ranked if s is not None]
    kept.sort(key=lambda item: (item[1], len(item[0])))
    return [p for p, _ in kept[:MAX_FILES]]


class GitHubClient:
    def __init__(self, token: str | None = None, transport: httpx.BaseTransport | None = None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(base_url=API, headers=headers, timeout=30, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, **kwargs) -> httpx.Response:
        response = self._http.get(path, **kwargs)
        if response.status_code == 404:
            raise GitHubError("Repo not found. Is it public?")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError("GitHub rate limit reached. Add a GITHUB_TOKEN.")
        if response.status_code in (401, 403):
            raise GitHubError(f"GitHub refused access ({response.status_code}). Check the repo is public and the token is valid.")
        response.raise_for_status()
        return response

    def _raw(self, path: str) -> str:
        response = self._get(path, headers={"Accept": "application/vnd.github.raw+json"})
        return response.text

    def snapshot(self, repo_url: str) -> RepoSnapshot:
        owner, name = parse_repo_url(repo_url)
        base = f"/repos/{owner}/{name}"
        meta = self._get(base).json()
        branch = meta.get("default_branch") or "main"

        snap = RepoSnapshot(
            owner=owner,
            name=name,
            url=f"https://github.com/{owner}/{name}",
            created_at=_ts(meta["created_at"]),
            pushed_at=_ts(meta.get("pushed_at")),
            is_fork=bool(meta.get("fork")),
            fork_parent=(meta.get("parent") or {}).get("full_name"),
            default_branch=branch,
        )

        if meta.get("size", 0) == 0 and not meta.get("pushed_at"):
            return snap  # empty repo

        snap.commits = self._commits(base, branch)
        snap.push_times = self._push_times(base)
        tree = self._get(f"{base}/git/trees/{branch}", params={"recursive": "1"}).json()
        snap.all_paths = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]

        try:
            snap.readme = self._raw(f"{base}/readme")[:MAX_FILE_CHARS]
        except (GitHubError, httpx.HTTPStatusError):
            snap.readme = ""

        total = 0
        for path in select_paths(snap.all_paths):
            if total >= MAX_TOTAL_CHARS:
                break
            try:
                text = self._raw(f"{base}/contents/{path}")
            except (GitHubError, httpx.HTTPStatusError):
                continue
            truncated = len(text) > MAX_FILE_CHARS
            text = text[:MAX_FILE_CHARS]
            total += len(text)
            snap.files.append(RepoFile(path=path, content=text, truncated=truncated))
        return snap

    def _commits(self, base: str, branch: str) -> list[CommitInfo]:
        commits: list[CommitInfo] = []
        page = 1
        while len(commits) < MAX_COMMITS:
            batch = self._get(f"{base}/commits", params={"sha": branch, "per_page": 100, "page": page}).json()
            if not batch:
                break
            for item in batch:
                c = item["commit"]
                commits.append(
                    CommitInfo(
                        sha=item["sha"],
                        message=c["message"].splitlines()[0][:200] if c.get("message") else "",
                        authored_at=_ts(c["author"]["date"]),
                        committed_at=_ts(c["committer"]["date"]),
                    )
                )
            if len(batch) < 100:
                break
            page += 1
        for commit in commits[:MAX_COMMIT_STATS]:
            stats = self._get(f"{base}/commits/{commit.sha}").json().get("stats") or {}
            commit.additions = stats.get("additions")
            commit.deletions = stats.get("deletions")
        return commits

    def _push_times(self, base: str) -> list[datetime]:
        """When GitHub actually received pushes. Unlike commit dates, these can't be faked locally."""
        try:
            events = self._get(f"{base}/events", params={"per_page": 100}).json()
        except (GitHubError, httpx.HTTPStatusError):
            return []
        return sorted(_ts(e["created_at"]) for e in events if e.get("type") in ("PushEvent", "CreateEvent"))
