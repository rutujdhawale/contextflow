"""A bounded graph abstraction used by both tests and the HydraDB adapter."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import Entity, Relationship


class GraphStore:
    """Small canonical graph store for deterministic local demos and tests."""

    def __init__(
        self,
        entities: Iterable[Entity] = (),
        relationships: Iterable[Relationship] = (),
    ) -> None:
        self.backend = "indexed_graph"
        self._edge_scans = 0
        self._node_lookups = 0
        self.entities: dict[tuple[str, str], Entity] = {
            (entity.type.lower(), entity.id): entity for entity in entities
        }
        self.relationships: list[Relationship] = list(relationships)
        self._outgoing: dict[tuple[str, str], list[Relationship]] = defaultdict(list)
        self._incoming: dict[tuple[str, str], list[Relationship]] = defaultdict(list)
        for relationship in self.relationships:
            self._outgoing[
                (relationship.source_type.lower(), relationship.source_id)
            ].append(relationship)
            self._incoming[
                (relationship.target_type.lower(), relationship.target_id)
            ].append(relationship)

    def get(self, entity_type: str, entity_id: str) -> Entity | None:
        self._node_lookups += 1
        return self.entities.get((entity_type.lower(), entity_id))

    def outgoing(
        self, entity: Entity, relationship_type: str | None = None
    ) -> list[tuple[Relationship, Entity]]:
        candidates = self._outgoing.get((entity.type.lower(), entity.id), [])
        self._edge_scans += len(candidates)
        return [
            (relationship, target)
            for relationship in candidates
            if (relationship_type is None or relationship.type == relationship_type)
            and (target := self.get(relationship.target_type, relationship.target_id))
            is not None
        ]

    def incoming(
        self, entity: Entity, relationship_type: str | None = None
    ) -> list[tuple[Relationship, Entity]]:
        candidates = self._incoming.get((entity.type.lower(), entity.id), [])
        self._edge_scans += len(candidates)
        return [
            (relationship, source)
            for relationship in candidates
            if (relationship_type is None or relationship.type == relationship_type)
            and (source := self.get(relationship.source_type, relationship.source_id))
            is not None
        ]

    @property
    def node_count(self) -> int:
        return len(self.entities)

    @property
    def edge_count(self) -> int:
        return len(self.relationships)

    def reset_metrics(self) -> None:
        self._edge_scans = 0
        self._node_lookups = 0

    def metrics(self) -> dict[str, int | str]:
        return {
            "backend": self.backend,
            "edge_scans": self._edge_scans,
            "node_lookups": self._node_lookups,
        }

    def extend(
        self, entities: Iterable[Entity], relationships: Iterable[Relationship]
    ) -> None:
        """Apply an incremental fixture batch and rebuild only local adjacency maps."""
        for entity in entities:
            self.entities[(entity.type.lower(), entity.id)] = entity
        for relationship in relationships:
            self.relationships.append(relationship)
            self._outgoing[
                (relationship.source_type.lower(), relationship.source_id)
            ].append(relationship)
            self._incoming[
                (relationship.target_type.lower(), relationship.target_id)
            ].append(relationship)
