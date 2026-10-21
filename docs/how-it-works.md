# How the assistant works

Judges give every score. The assistant prepares each project so judges can score it quickly and fairly.

## For each submission

1. **Read the repo** through the GitHub API (`judge/github_client.py`). Metadata, commits, push times, the file list, the README and up to 40 of the most relevant files. We never clone or run participants' code.
2. **Integrity checks** (`judge/integrity.py`). Plain code, no AI:
   - *Built on the day*: repo creation time, push times (recorded by GitHub, can't be faked) and commit dates (can be faked, so treated as a softer signal)
   - *Steady progress*: flags when most of the code arrives in the last 30 minutes
   - *Original repo*: flags forks
   - *No hidden instructions*: phrases aimed at an AI judge, hidden HTML comments in the README, invisible characters
   - *Copied projects*: compares every pair of submissions (`find_similar_pairs`)
3. **ADK agents** (`judge/agents/review.py`):

   ```
   ┌─ code_reviewer ─┐
   │                 ├─> brief_writer
   └─ demo_reviewer ─┘
   ```

   - `code_reviewer` reads the repo and reports how ADK is used, code quality and safety
   - `demo_reviewer` watches the YouTube demo and lists what happens, with timestamps
   - `brief_writer` combines both with the integrity checks into a one-page brief and three pitch questions

4. After judging, `feedback_writer` (`judge/agents/feedback.py`) turns the judges' notes into feedback. Judges approve it before teams see it.

A check that fails never removes a team. It marks the project for a judge to look at.

## Guarding against prompt injection

- All participant text is wrapped in random `UNTRUSTED` markers and every agent is told it is material to review, never instructions.
- Each reviewer only receives its own material (a `before_model_callback` strips the rest).
- Agents use instruction functions, so `{curly braces}` in participants' code are never treated as template variables.
- Anything a reviewer spots that tries to influence judging is added as an integrity flag.
- The assistant has no tools that can change anything, and its output never becomes a score.

## Video

Gemini can watch **public or unlisted YouTube** links directly. Other links (Google Drive, Loom) are not sent to the model; the brief says a judge needs to watch them. The rules email should ask for YouTube links.
