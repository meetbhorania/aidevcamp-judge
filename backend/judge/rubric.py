"""The judging rubric. Judges score with it; the assistant only uses it to know what to look for."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    key: str
    name: str
    weight: int  # percent
    question: str
    levels: tuple[str, str, str, str, str]  # what a 1, 2, 3, 4 and 5 look like


RUBRIC: tuple[Criterion, ...] = (
    Criterion(
        "agentic", "Agentic design and ADK use", 25,
        "Is it a real agent built with ADK? Does it use tools, take steps and make decisions, rather than being a simple chatbot?",
        (
            "Not really an agent. A single prompt or chatbot with no tools.",
            "Uses ADK, but only for basic chat with one simple tool.",
            "A working agent with a few tools that completes a task in more than one step.",
            "A well-designed agent, or several agents working together. Good use of tools and memory.",
            "Excellent design. The agent plans, uses tools, handles a full workflow, and every part has a clear job.",
        ),
    ),
    Criterion(
        "working", "Working solution", 20,
        "Does the demo show the agent actually doing its main job from start to finish?",
        (
            "Nothing working is shown.",
            "Some parts work, but the main task fails or is faked.",
            "The main task works in the demo, with some rough edges.",
            "The main task works smoothly from start to finish.",
            "Works from start to finish, copes with things going wrong, and feels close to ready for real users.",
        ),
    ),
    Criterion(
        "impact", "Problem and impact", 20,
        "Is there a clear problem and a clear user? Would the solution actually help them?",
        (
            "No clear problem or user.",
            "The problem is vague, or the solution would not help much.",
            "Clear problem and user. The solution helps a little.",
            "A real problem, and the solution would save people real time or effort.",
            "An important problem, clearly explained, and the solution makes a real difference.",
        ),
    ),
    Criterion(
        "innovation", "Innovation", 15,
        "Is the idea or the approach fresh, or is it a copy of a tutorial?",
        (
            "A copy of a tutorial or sample project.",
            "A common idea with small changes.",
            "A known idea with one meaningful new twist.",
            "A fresh idea, or a clever way of solving a known problem.",
            "Something the judges have probably not seen before.",
        ),
    ),
    Criterion(
        "code", "Code quality", 10,
        "Is the code organised, and could someone else run it from the README?",
        (
            "Hard to follow, and no README.",
            "Works, but messy. The README is missing setup steps.",
            "Reasonably organised. The README explains how to run it.",
            "Clean structure, clear README, sensible names.",
            "Clean and well organised. Someone new could pick it up and run it easily.",
        ),
    ),
    Criterion(
        "responsible", "Responsible AI", 10,
        "Does the agent behave safely? Does it check before doing anything important, and handle mistakes?",
        (
            "Could cause harm, or takes risky actions without asking.",
            "Little thought given to errors or safety.",
            "Handles basic errors. No obvious risks.",
            "Asks before important actions and handles mistakes well.",
            "Safety and privacy have clearly been thought about throughout.",
        ),
    ),
)

assert sum(c.weight for c in RUBRIC) == 100


def weighted_total(scores: dict[str, float]) -> float:
    """Judges' 1-5 scores per criterion -> total out of 100."""
    return round(sum(scores[c.key] / 5 * c.weight for c in RUBRIC), 1)


def rubric_text() -> str:
    return "\n".join(f"- {c.name} ({c.weight}%): {c.question}" for c in RUBRIC)
