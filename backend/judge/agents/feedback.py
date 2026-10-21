"""Turns judges' notes into feedback for a team. Judges approve it before the team sees it."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from ..models import FeedbackDraft


def build_feedback_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="feedback_writer",
        model=model,
        description="Drafts private feedback for a team from the judges' notes.",
        instruction=(
            "You draft private feedback for a hackathon team, on behalf of the judging panel. The user "
            "message has the judges' own notes, their average score per area and the project brief.\n\n"
            "Base the feedback on the judges' notes first; use the brief only for detail. Be specific, kind "
            "and practical, like a senior engineer mentoring a junior one. Never invent praise or problems "
            "the judges did not raise. Do not mention scores, rankings or other teams. Do not mention that "
            "an AI wrote this. Plain, everyday English."
        ),
        output_schema=FeedbackDraft,
        output_key="feedback",
        generate_content_config=types.GenerateContentConfig(temperature=0.4),
    )
