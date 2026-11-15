"""Question-derived evidence requirements shared by local and live compilers."""

from __future__ import annotations

from collections.abc import Iterable


def required_evidence(question: str) -> tuple[str, ...]:
    lowered = question.casefold()
    required = ["change"]
    if any(term in lowered for term in ("who owns", "owner", "team")):
        required.append("owner")
    if any(term in lowered for term in ("previous", "worked", "mitigation", "history")):
        required.append("history")
    if "runbook" in lowered:
        required.append("runbook")
    return tuple(dict.fromkeys(required))


def covered_evidence(
    required: Iterable[str], recipes: Iterable[str]
) -> tuple[str, ...]:
    available = set(recipes)
    return tuple(item for item in required if item in available)


def missing_evidence(
    required: Iterable[str], covered: Iterable[str]
) -> tuple[str, ...]:
    present = set(covered)
    return tuple(item for item in required if item not in present)
