"""Runs everything for one submission: GitHub snapshot, integrity checks, then the ADK agents."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agents import build_feedback_agent, build_review_agent
from .agents.review import REPO_TAG, VIDEO_TAG
from .config import Settings, get_settings
from .github_client import GitHubClient, GitHubError
from .integrity import run_checks
from .models import (
    CodeReview,
    DemoReview,
    FeedbackDraft,
    FlagLevel,
    IntegrityFlag,
    IntegrityReport,
    ProjectBrief,
    RepoSnapshot,
    Review,
    Submission,
)
from .rubric import RUBRIC
from .untrusted import RULE, fence, repo_bundle, submission_block

APP = "aidevcamp_judge"
_YOUTUBE_RE = re.compile(r"^(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|live/)|youtu\.be/)[\w-]{6,}", re.I)


def is_youtube(url: str) -> bool:
    return bool(_YOUTUBE_RE.match(url.strip()))


def build_message(snap: RepoSnapshot, video_url: str) -> types.Content:
    parts = [types.Part(text=f"{REPO_TAG}\n{RULE}\n\n{repo_bundle(snap)}")]
    if is_youtube(video_url):
        parts.append(types.Part(text=f"{VIDEO_TAG} The team's demo video follows."))
        parts.append(types.Part(file_data=types.FileData(file_uri=video_url.strip(), mime_type="video/*")))
    else:
        parts.append(
            types.Part(
                text=f"{VIDEO_TAG} No watchable video. The link is not a public YouTube video ({video_url}). "
                "A judge needs to watch it directly."
            )
        )
    return types.Content(role="user", parts=parts)


def _as_model(cls, value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        return cls.model_validate_json(value)
    return cls.model_validate(value)


async def _run(agent, state: dict, message: types.Content) -> dict:
    runner = InMemoryRunner(agent=agent, app_name=APP)
    user_id, session_id = "judge", uuid.uuid4().hex
    await runner.session_service.create_session(app_name=APP, user_id=user_id, session_id=session_id, state=state)
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass
    session = await runner.session_service.get_session(app_name=APP, user_id=user_id, session_id=session_id)
    return dict(session.state)


async def review_submission(
    sub: Submission,
    settings: Settings | None = None,
    github: GitHubClient | None = None,
    snapshot: RepoSnapshot | None = None,
    model: Any = None,
) -> Review:
    """Prepare everything judges need for one project. Never raises: problems go into review.errors."""
    settings = settings or get_settings()
    errors: list[str] = []

    snap = snapshot
    if snap is None:
        own_client = github is None
        github = github or GitHubClient(settings.github_token)
        try:
            snap = github.snapshot(sub.repo_url)
        except (GitHubError, Exception) as exc:  # noqa: BLE001 - report, don't crash
            return Review(submission=sub, integrity=IntegrityReport(), errors=[f"Could not read the repo: {exc}"])
        finally:
            if own_client:
                github.close()

    integrity = run_checks(snap, sub, settings.event_start, settings.submission_deadline)
    review = Review(submission=sub, integrity=integrity)

    state = {
        "submission_block": submission_block(sub),
        "integrity": [f.model_dump(mode="json") for f in integrity.flags],
    }
    try:
        result = await _run(build_review_agent(model or settings.model), state, build_message(snap, sub.video_url))
        review.code_review = _as_model(CodeReview, result.get("code_review"))
        review.demo_review = _as_model(DemoReview, result.get("demo_review"))
        review.brief = _as_model(ProjectBrief, result.get("brief"))
        if review.code_review and review.code_review.suspicious_content:
            for quote in review.code_review.suspicious_content[:3]:
                review.integrity.flags.append(
                    IntegrityFlag(check="No hidden instructions", level=FlagLevel.check, detail=f'Reviewer spotted: "{quote[:200]}"')
                )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"The assistant could not finish the brief: {exc}")
    review.errors = errors
    return review


async def draft_feedback(
    brief: ProjectBrief | None,
    judge_notes: list[str],
    average_scores: dict[str, float],
    settings: Settings | None = None,
    model: Any = None,
) -> FeedbackDraft:
    settings = settings or get_settings()
    names = {c.key: c.name for c in RUBRIC}
    scores = "\n".join(f"- {names.get(k, k)}: {v:.1f} / 5" for k, v in average_scores.items())
    notes = "\n".join(f"- {n}" for n in judge_notes) or "- (no notes)"
    text = (
        "Judges' notes:\n" + notes + "\n\nAverage score per area:\n" + scores + "\n\n"
        + fence("PROJECT BRIEF", json.dumps(brief.model_dump() if brief else {}, indent=2))
    )
    result = await _run(build_feedback_agent(model or settings.model), {}, types.Content(role="user", parts=[types.Part(text=text)]))
    return _as_model(FeedbackDraft, result.get("feedback"))
