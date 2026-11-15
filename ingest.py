"""Load deterministic fixtures into a local GraphStore and optionally HydraDB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pathcontext.graph import GraphStore
from pathcontext.hydradb_ingest import write_graph
from pathcontext.schema import Entity, Relationship


def load_fixture(path: str | Path) -> GraphStore:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return GraphStore(
        entities=(Entity(**item) for item in payload["entities"]),
        relationships=(Relationship(**item) for item in payload["relationships"]),
    )


def cypher_for_fixture(path: str | Path) -> list[str]:
    """Return relationship/property statements for already-created nodes.

    HydraDB reserves ``id`` as an integer vertex key. PathContext keeps its
    human-readable IDs in ``external_id`` and assigns stable integer keys.
    Use ``ingest_fixture`` for a live HydraDB write because it creates missing
    nodes with the engine-supported ``CREATE`` form first.
    """
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    entity_keys = {
        (entity["type"], entity["id"]): index
        for index, entity in enumerate(payload["entities"], start=1)
    }
    statements: list[str] = []
    for entity in payload["entities"]:
        key = entity_keys[(entity["type"], entity["id"])]
        properties = {"external_id": entity["id"], **entity.get("properties", {})}
        rendered = ", ".join(
            f"n.{name} = {_cypher_value(value)}"
            for name, value in properties.items()
        )
        statements.append(
            f"MATCH (n:{entity['type']} {{id: {key}}}) SET {rendered}"
        )
    for relationship in payload["relationships"]:
        source_key = entity_keys[
            (relationship["source_type"], relationship["source_id"])
        ]
        target_key = entity_keys[
            (relationship["target_type"], relationship["target_id"])
        ]
        statements.append(
            "MATCH (a:%s {id: %d}) MATCH (b:%s {id: %d}) "
            "MERGE (a)-[:%s]->(b)"
            % (
                relationship["source_type"],
                source_key,
                relationship["target_type"],
                target_key,
                relationship["type"],
            )
        )
    return statements


def ingest_fixture(client: Any, path: str | Path) -> int:
    """Upsert fixture vertices and edges through HydraDB's batch mutations.

    The HTTP client sends list-of-map parameters because HydraDB's specialized
    UNWIND mutation path is the supported bulk-ingest implementation. Vertex
    batches use one static label and explicit row-field assignments; edge
    batches create relationships after vertices are present.
    """
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    entity_keys = {
        (entity["type"], entity["id"]): index
        for index, entity in enumerate(payload["entities"], start=1)
    }
    nodes = [
        {
            "id": entity_keys[(entity["type"], entity["id"])],
            "label": entity["type"],
            "external_id": entity["id"],
            "properties": entity.get("properties", {}),
        }
        for entity in payload["entities"]
    ]
    edges = [
        {
            "src": entity_keys[(relationship["source_type"], relationship["source_id"])],
            "dst": entity_keys[(relationship["target_type"], relationship["target_id"])],
            "type": relationship["type"],
        }
        for relationship in payload["relationships"]
    ]
    return write_graph(client, nodes, edges)


def _cypher_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"
