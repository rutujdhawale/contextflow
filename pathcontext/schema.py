"""Domain types shared by ingestion, traversal, and context compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)
    source: str = "fixture"

    @property
    def key(self) -> str:
        return f"{self.type.lower()}:{self.id}"


@dataclass(frozen=True)
class Relationship:
    source_id: str
    source_type: str
    type: str
    target_id: str
    target_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    source: str = "fixture"


@dataclass(frozen=True)
class EvidencePath:
    nodes: tuple[Entity, ...]
    relationships: tuple[Relationship, ...]
    score: float
    recipe: str

    @property
    def labels(self) -> list[str]:
        return [f"{node.type}:{node.id}" for node in self.nodes]

    @property
    def source(self) -> str:
        return self.labels[-1]


@dataclass(frozen=True)
class Fact:
    text: str
    source: str
    path: tuple[str, ...]
    confidence: str
    score: float
    token_cost: int


@dataclass
class EvidencePacket:
    context: str
    facts: list[Fact]
    contradictions: list[str]
    uncertainty: list[str]
    answerability: str
    retrieval_stats: dict[str, int | float | str]
    required_evidence: tuple[str, ...] = ()
    covered_evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    entity_resolution: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context,
            "facts": [
                {
                    "text": fact.text,
                    "source": fact.source,
                    "path": list(fact.path),
                    "confidence": fact.confidence,
                }
                for fact in self.facts
            ],
            "contradictions": self.contradictions,
            "uncertainty": self.uncertainty,
            "answerability": self.answerability,
            "retrieval_stats": self.retrieval_stats,
            "required_evidence": list(self.required_evidence),
            "covered_evidence": list(self.covered_evidence),
            "missing_evidence": list(self.missing_evidence),
            "entity_resolution": list(self.entity_resolution),
        }


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
