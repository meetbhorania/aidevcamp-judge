"""Settings, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv

    # Look for .env in the repo root and in backend/.
    for candidate in (Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            break
except ImportError:  # pragma: no cover
    pass

LONDON = ZoneInfo("Europe/London")


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


@dataclass(frozen=True)
class Settings:
    model: str
    github_token: str | None
    event_start: datetime
    submission_deadline: datetime

    @classmethod
    def from_env(cls) -> "Settings":
        event_day = date.fromisoformat(os.getenv("EVENT_DATE", "2026-10-31"))
        start = datetime.combine(event_day, _parse_time(os.getenv("EVENT_START", "09:00")), LONDON)
        deadline = datetime.combine(event_day, _parse_time(os.getenv("SUBMISSION_DEADLINE", "16:00")), LONDON)
        return cls(
            model=os.getenv("JUDGE_MODEL", "gemini-2.5-flash"),
            github_token=os.getenv("GITHUB_TOKEN") or None,
            event_start=start,
            submission_deadline=deadline,
        )


def get_settings() -> Settings:
    return Settings.from_env()
