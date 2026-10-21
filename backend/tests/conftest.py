from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import AsyncGenerator

import pytest
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

from judge.config import LONDON, Settings
from judge.models import CommitInfo, RepoFile, RepoSnapshot, Submission

START = datetime(2026, 10, 31, 9, 0, tzinfo=LONDON)
DEADLINE = datetime(2026, 10, 31, 16, 0, tzinfo=LONDON)


@pytest.fixture
def settings() -> Settings:
    return Settings(model="fake", github_token=None, event_start=START, submission_deadline=DEADLINE)


def at(hour: int, minute: int = 0) -> datetime:
    return START.replace(hour=hour, minute=minute)


def make_snapshot(**overrides) -> RepoSnapshot:
    commits = [
        CommitInfo(sha=f"c{i}", message=f"step {i}", authored_at=at(9, 20) + timedelta(minutes=30 * i),
                   committed_at=at(9, 20) + timedelta(minutes=30 * i), additions=80, deletions=5)
        for i in range(10)
    ]
    data = dict(
        owner="team", name="shelflife", url="https://github.com/team/shelflife",
        created_at=at(9, 5), pushed_at=at(14, 45), commits=commits,
        push_times=[c.committed_at + timedelta(minutes=1) for c in commits],
        all_paths=["README.md", "agents/pipeline.py", "tools/maps.py", "requirements.txt"],
        files=[
            RepoFile(path="requirements.txt", content="google-adk\n"),
            RepoFile(path="agents/pipeline.py", content=(
                "from google.adk.agents import LlmAgent, SequentialAgent\n"
                "reader = LlmAgent(name='stock_reader', model='gemini-2.5-flash', instruction='Read the surplus list {stock}')\n"
                "matcher = LlmAgent(name='charity_matcher', model='gemini-2.5-flash', tools=[search_charities])\n"
                "root_agent = SequentialAgent(name='shelflife', sub_agents=[reader, matcher])\n"
            )),
        ],
        readme="# ShelfLife\nGets surplus food from cafes to charities.\n",
    )
    data.update(overrides)
    return RepoSnapshot(**data)


def make_submission(**overrides) -> Submission:
    data = dict(team_name="Byte Club", project_name="ShelfLife", summary="Surplus food to charities",
                problem="Cafes waste food", repo_url="https://github.com/team/shelflife",
                video_url="https://youtu.be/dQw4w9WgXcQ")
    data.update(overrides)
    return Submission(**data)


# ---------- A fake Gemini, so tests run without a key or network ----------

CANNED = {
    "code_reviewer": {
        "what_it_does": "Matches cafe surplus food with nearby charities and books a pickup.",
        "uses_adk": True,
        "adk_usage": [{"point": "SequentialAgent with two LlmAgents", "where": "agents/pipeline.py"}],
        "code_notes": [{"point": "README has no setup steps", "where": "README.md"}],
        "safety_notes": [{"point": "Books pickups without asking first", "where": "agents/pipeline.py"}],
        "suspicious_content": [],
    },
    "demo_reviewer": {
        "watched": True,
        "moments": [{"point": "Cafe uploads a list", "where": "0:05"}, {"point": "Pickup booked", "where": "2:10"}],
        "works_end_to_end": True,
        "concerns": [],
    },
    "brief_writer": {
        "one_liner": "An agent that gets surplus cafe food to charities.",
        "what_they_built": "A two-agent pipeline that reads a surplus list and books a charity pickup.",
        "who_its_for": "Small cafes and local charities.",
        "how_it_uses_adk": [{"point": "SequentialAgent with two LlmAgents", "where": "agents/pipeline.py"}],
        "what_the_demo_shows": [{"point": "Pickup booked end to end", "where": "2:10"}],
        "strengths": ["Clear problem", "Works end to end in the demo"],
        "gaps": ["No confirmation before booking", "README lacks setup steps"],
        "pitch_questions": ["What if a charity cancels?", "Why no confirmation step?", "How is food safety judged?"],
    },
    "feedback_writer": {
        "worked_well": ["Clear agent design"],
        "to_improve": ["Ask before booking"],
        "note": "Great work.",
    },
}

MARKERS = {
    "Read the repository": "code_reviewer",
    "Watch the demo": "demo_reviewer",
    "one-page brief": "brief_writer",
    "draft private feedback": "feedback_writer",
}


class FakeLlm(BaseLlm):
    model: str = "fake"
    calls: list = []
    overrides: dict = {}

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        system = str(llm_request.config.system_instruction or "")
        agent = next((name for marker, name in MARKERS.items() if marker in system), "unknown")
        self.calls.append({"agent": agent, "system": system, "contents": llm_request.contents})
        payload = self.overrides.get(agent, CANNED.get(agent, {}))
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(payload))]))


@pytest.fixture
def fake_llm() -> FakeLlm:
    return FakeLlm(calls=[], overrides={})
