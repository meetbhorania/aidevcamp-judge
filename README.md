# AIDevCamp Judge

Judging assistant for the GDG London AIDevCamp 2026 Agentic Hackathon (31 October 2026).

The judges do all the scoring. This system helps them by:

- writing a short **brief** for every project as soon as it is submitted (what it does, how it uses ADK, what the demo shows)
- running **integrity checks** (built on the day, last-minute uploads, forks, copied projects, hidden instructions in the README)
- suggesting **questions to ask in the pitch**
- turning judges' notes into **feedback drafts** that judges approve before teams see them

Nothing the assistant produces counts towards a team's score.

## Layout

```
backend/   Python: ADK agents, integrity checks, API
frontend/  Next.js dashboards for teams, judges and the public (coming next)
docs/      Rubric and planning notes
```

## Running the backend locally

Requires Python 3.11+.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # then fill in your own keys
pytest
```

Review one project from the command line:

```bash
python -m judge.cli review https://github.com/OWNER/REPO --video https://youtu.be/VIDEO_ID
```

Integrity checks only (no Gemini key needed, uses the GitHub API):

```bash
python -m judge.cli check https://github.com/OWNER/REPO
```

## Secrets

Never commit keys. Put them in `.env` (ignored by git). See `.env.example` for the list.
