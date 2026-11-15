"""A deliberately explicit, fair lexical retrieval baseline.

It represents the common non-graph approach: rank independent records by token
overlap and return the top records without joining their relationships.
"""

from __future__ import annotations

import re
import time
from typing import Any

from .graph import GraphStore
from .schema import EvidencePacket, Fact


def lexical_baseline(
    graph: GraphStore,
    question: str,
    *,
    context_budget_tokens: int = 800,
    top_k: int = 8,
) -> EvidencePacket:
    started = time.perf_counter()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]+", question.lower()))
    ranked: list[tuple[int, str, str]] = []
    for entity in graph.entities.values():
        searchable = " ".join(
            [entity.id, entity.type]
            + [str(value) for value in entity.properties.values()]
        ).lower()
        overlap = len(tokens & set(re.findall(r"[a-z0-9][a-z0-9_-]+", searchable)))
        if overlap:
            ranked.append((overlap, entity.type, entity.id))
    facts: list[Fact] = []
    used = 0
    for overlap, entity_type, entity_id in sorted(ranked, reverse=True)[:top_k]:
        text = f"{entity_type} {entity_id}"
        cost = len(text.split())
        if used + cost > context_budget_tokens:
            continue
        used += cost
        facts.append(
            Fact(
                text=text,
                source=f"{entity_type}:{entity_id}",
                path=(f"{entity_type}:{entity_id}",),
                confidence="mixed",
                score=float(overlap),
                token_cost=cost,
            )
        )
    uncertainty = [] if facts else ["Lexical baseline found no matching records."]
    return EvidencePacket(
        context="\n".join(f"- {fact.text}" for fact in facts),
        facts=facts,
        contradictions=[],
        uncertainty=uncertainty,
        answerability="supported" if facts else "insufficient",
        retrieval_stats={
            "backend": "lexical_baseline",
            "nodes_traversed": len(graph.entities),
            "edges_traversed": 0,
            "input_tokens": used,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "read_epoch": "local",
        },
    )
