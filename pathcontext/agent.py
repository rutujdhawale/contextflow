"""Agent-callable interface with a stable JSON response shape."""

from __future__ import annotations

from typing import Any

from .context_compiler import ContextCompiler


def retrieve_structured_context(
    compiler: ContextCompiler,
    *,
    question: str,
    seed_entities: list[dict[str, str]] | None = None,
    context_budget_tokens: int = 800,
) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("question must not be empty")
    if context_budget_tokens < 1:
        raise ValueError("context_budget_tokens must be positive")
    return compiler.compile(
        question,
        seed_entities=seed_entities,
        context_budget_tokens=context_budget_tokens,
    ).to_dict()
