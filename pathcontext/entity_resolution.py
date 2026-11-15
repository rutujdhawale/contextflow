"""Conservative seed resolution; graph structure remains the source of truth."""

from __future__ import annotations

import re

from .graph import GraphStore
from .schema import Entity


_ID_PATTERN = re.compile(r"\b(?:INC|SVC|DEP|COMMIT|FILE|TEAM|RB|MIT)-[\w-]+\b", re.I)


def resolve_entity_states(
    question: str, graph: GraphStore, seeds: list[dict[str, str]] | None = None
) -> tuple[list[Entity], list[dict[str, object]]]:
    """Resolve explicit IDs and aliases without silently choosing collisions."""
    candidates: list[tuple[str, str]] = []
    for seed in seeds or []:
        candidates.append((f"{seed['type']}:{seed['id']}", seed["id"]))
    candidates.extend((match, match) for match in _ID_PATTERN.findall(question))
    lowered_question = question.casefold()
    for entity in graph.entities.values():
        aliases_value = entity.properties.get("aliases", [])
        aliases_list = (
            aliases_value if isinstance(aliases_value, list) else [aliases_value]
        )
        aliases = [
            str(entity.properties.get("name", "")),
            *[str(alias) for alias in aliases_list],
        ]
        for alias in aliases:
            if alias and len(alias) >= 3 and alias.casefold() in lowered_question:
                candidates.append((alias, alias))

    resolved: list[Entity] = []
    states: list[dict[str, object]] = []
    seen_mentions: set[str] = set()
    for mention, value in candidates:
        key = mention.casefold()
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        matches = [
            entity
            for entity in graph.entities.values()
            if value.casefold() == entity.id.casefold()
            or value.casefold() == str(entity.properties.get("external_id", "")).casefold()
            or value.casefold() in {
                str(alias).casefold()
                for alias in (
                    entity.properties.get("aliases", [])
                    if isinstance(entity.properties.get("aliases", []), list)
                    else [entity.properties.get("aliases", "")]
                )
            }
        ]
        if len(matches) == 1:
            entity = matches[0]
            if entity not in resolved:
                resolved.append(entity)
            states.append({"mention": mention, "state": "resolved", "entity": entity.key})
        elif len(matches) > 1:
            states.append(
                {
                    "mention": mention,
                    "state": "ambiguous",
                    "candidates": [entity.key for entity in matches],
                }
            )
        else:
            states.append({"mention": mention, "state": "unresolved"})
    if not candidates:
        states.append({"mention": question, "state": "unresolved"})
    return resolved, states


def resolve_entities(
    question: str, graph: GraphStore, seeds: list[dict[str, str]] | None = None
) -> list[Entity]:
    resolved, _ = resolve_entity_states(question, graph, seeds)
    return resolved
