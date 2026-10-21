import httpx
import pytest

from judge.github_client import GitHubClient, GitHubError, parse_repo_url, select_paths


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/meet/judge", ("meet", "judge")),
        ("https://github.com/meet/judge.git", ("meet", "judge")),
        ("github.com/meet/my.repo/", ("meet", "my.repo")),
        ("https://www.github.com/a-b/c_d?tab=readme", ("a-b", "c_d")),
    ],
)
def test_parse_repo_url(url, expected):
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize("url", ["https://gitlab.com/a/b", "https://github.com/onlyowner", "not a url"])
def test_parse_repo_url_rejects_other_links(url):
    with pytest.raises(GitHubError):
        parse_repo_url(url)


def test_select_paths_prefers_agent_code_and_skips_junk():
    paths = [
        "node_modules/x/index.js", "package-lock.json", "README.md", "docs/notes.md",
        "src/utils.py", "src/my_agent/agent.py", "requirements.txt", "tests/test_agent.py", "logo.png",
    ]
    chosen = select_paths(paths)
    assert chosen[0] == "requirements.txt"
    assert chosen[1] == "src/my_agent/agent.py"
    assert "node_modules/x/index.js" not in chosen and "package-lock.json" not in chosen
    assert "logo.png" not in chosen and "README.md" not in chosen


def _fake_github(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/repos/team/app":
        return httpx.Response(200, json={
            "created_at": "2026-10-31T09:05:00Z", "pushed_at": "2026-10-31T14:00:00Z", "fork": False,
            "default_branch": "main", "size": 12,
        })
    if path == "/repos/team/app/commits":
        return httpx.Response(200, json=[{
            "sha": "abc", "commit": {"message": "Add agent\n\nbody",
                                     "author": {"date": "2026-10-31T10:00:00Z"},
                                     "committer": {"date": "2026-10-31T10:00:00Z"}},
        }])
    if path == "/repos/team/app/commits/abc":
        return httpx.Response(200, json={"stats": {"additions": 120, "deletions": 3}})
    if path == "/repos/team/app/events":
        return httpx.Response(200, json=[{"type": "PushEvent", "created_at": "2026-10-31T10:01:00Z"}])
    if path == "/repos/team/app/git/trees/main":
        return httpx.Response(200, json={"tree": [
            {"path": "agent.py", "type": "blob"}, {"path": "README.md", "type": "blob"}, {"path": "src", "type": "tree"},
        ]})
    if path == "/repos/team/app/readme":
        return httpx.Response(200, text="# App")
    if path == "/repos/team/app/contents/agent.py":
        return httpx.Response(200, text="from google.adk.agents import LlmAgent")
    return httpx.Response(404)


def test_snapshot_reads_everything():
    with GitHubClient(transport=httpx.MockTransport(_fake_github)) as gh:
        snap = gh.snapshot("https://github.com/team/app")
    assert snap.commits[0].message == "Add agent"
    assert snap.commits[0].additions == 120
    assert snap.push_times and snap.readme == "# App"
    assert [f.path for f in snap.files] == ["agent.py"]
    assert snap.all_paths == ["agent.py", "README.md"]


def test_missing_repo_gives_clear_error():
    with GitHubClient(transport=httpx.MockTransport(_fake_github)) as gh:
        with pytest.raises(GitHubError, match="public"):
            gh.snapshot("https://github.com/team/missing")
