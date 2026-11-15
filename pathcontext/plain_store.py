"""Unindexed record-store control used to test whether graph structure matters."""

from __future__ import annotations

from collections.abc import Iterable

from .schema import Entity, Relationship


class PlainStore:
    """Same canonical records as GraphStore, but every relationship lookup scans all edges."""

    backend = "plain_record_store"

    def __init__(
        self,
        entities: Iterable[Entity] = (),
        relationships: Iterable[Relationship] = (),
    ) -> None:
        self.entities = {(entity.type.lower(), entity.id): entity for entity in entities}
        self.relationships = list(relationships)
        self._edge_scans = 0
        self._node_lookups = 0

    def get(self, entity_type: str, entity_id: str) -> Entity | None:
        self._node_lookups += 1
        return self.entities.get((entity_type.lower(), entity_id))

    def outgoing(self, entity: Entity, relationship_type: str | None = None):
        matches = []
        for relationship in self.relationships:
            self._edge_scans += 1
            if (
                relationship.source_type.lower() == entity.type.lower()
                and relationship.source_id == entity.id
                and (relationship_type is None or relationship.type == relationship_type)
            ):
                target = self.get(relationship.target_type, relationship.target_id)
                if target is not None:
                    matches.append((relationship, target))
        return matches

    def incoming(self, entity: Entity, relationship_type: str | None = None):
        matches = []
        for relationship in self.relationships:
            self._edge_scans += 1
            if (
                relationship.target_type.lower() == entity.type.lower()
                and relationship.target_id == entity.id
                and (relationship_type is None or relationship.type == relationship_type)
            ):
                source = self.get(relationship.source_type, relationship.source_id)
                if source is not None:
                    matches.append((relationship, source))
        return matches

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
        self.entities.update(
            ((entity.type.lower(), entity.id), entity) for entity in entities
        )
        self.relationships.extend(relationships)
