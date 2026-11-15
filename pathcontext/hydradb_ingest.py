"""Parameterized graph writes for HydraDB's supported client batch API."""

from __future__ import annotations

from typing import Any


def write_graph(
    client: Any,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> int:
    """Write labelled nodes and directed edges using UNWIND batches.

    ``nodes`` contain ``id``, ``label``, ``external_id`` and optional
    ``properties``. ``edges`` contain ``src``, ``dst`` and ``type``. The
    caller owns stable integer IDs; HydraDB does not generate them. Each
    label batch uses explicit row-field assignments because HydraDB does not
    support map expansion in its UNWIND vertex-upsert grammar.
    """
    operations = 0
    by_label: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_label.setdefault(str(node["label"]), []).append(
            {
                "vertex": int(node["id"]),
                "external_id": str(node["external_id"]),
                **dict(node.get("properties", {})),
            }
        )
    for label, rows in by_label.items():
        field_names = sorted(
            {
                name
                for row in rows
                for name in row
                if name not in {"vertex", "external_id"}
            }
        )
        assignments = [
            f"n:{label}",
            "n.external_id = row.external_id",
            *[
                f"n.{_property_name(name)} = row.{_property_name(name)}"
                for name in field_names
            ],
        ]
        parameter_rows = [
            {name: row.get(name) for name in ("vertex", "external_id", *field_names)}
            for row in rows
        ]
        client.query(
            "UNWIND $rows AS row "
            "MERGE (n {id: row.vertex}) SET " + ", ".join(assignments),
            {"rows": parameter_rows},
        )
        operations += len(rows)

    by_type: dict[str, list[dict[str, int]]] = {}
    for edge in edges:
        by_type.setdefault(str(edge["type"]), []).append(
            {"src": int(edge["src"]), "dst": int(edge["dst"])}
        )
    for edge_type, rows in by_type.items():
        client.query(
            f"UNWIND $rows AS row CREATE "
            f"(a {{id: row.src}})-[:{edge_type}]->(b {{id: row.dst}})",
            {"rows": rows},
        )
        operations += len(rows)
    return operations


def _property_name(name: str) -> str:
    if not name or not name.replace("_", "a").isalnum() or not (name[0].isalpha() or name[0] == "_"):
        raise ValueError(f"unsupported HydraDB property name: {name!r}")
    return name


def _cypher_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ") + "'"
