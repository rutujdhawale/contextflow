"""Verify the real PathContext-to-HydraDB HTTP path.

This is intentionally separate from the in-memory evaluator. A successful run
must prove that the configured HydraDB endpoint accepted a query, returned
rows, and exposed a read epoch or bookmark.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from ingest import ingest_fixture
from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _scalar(payload: Any) -> Any:
    rows = _rows(payload)
    if not rows or not rows[0]:
        return None
    value = rows[0][0]
    return value.get("value") if isinstance(value, dict) else value


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Smoke-test PathContext against HydraDB")
    parser.add_argument("--ingest", action="store_true", help="load the demo fixture first")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "incidents.json",
    )
    args = parser.parse_args()
    client = HydraDBClient(
        base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
        graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
        cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
        token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
    )
    try:
        # HydraDB requires read queries to be anchored by a node predicate;
        # a bare `RETURN 1` is valid Neo4j but intentionally unsupported here.
        probe = client.query("MATCH (n:Incident) RETURN n.id AS pathcontext_probe")
        if not _rows(probe) and not isinstance(probe, dict):
            raise HydraDBError("probe returned no recognizable JSON result")
        if args.ingest:
            statements = ingest_fixture(client, args.fixture)
            print(f"ingested_operations={statements}")
            fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
            node_counts = {}
            for label in sorted({item["type"] for item in fixture["entities"]}):
                node_counts[label] = _scalar(
                    client.query(
                        f"MATCH (n:{label}) RETURN count(*) AS node_count"
                    )
                )
            relationship_counts = {}
            for relation in sorted(
                {item["type"] for item in fixture["relationships"]}
            ):
                relationship_counts[relation] = _scalar(
                    client.query(
                        f"MATCH ()-[r:{relation}]->() RETURN count(*) AS edge_count"
                    )
                )
            expected_nodes = {
                label: sum(item["type"] == label for item in fixture["entities"])
                for label in node_counts
            }
            expected_edges = {
                relation: sum(
                    item["type"] == relation for item in fixture["relationships"]
                )
                for relation in relationship_counts
            }
            if node_counts != expected_nodes or relationship_counts != expected_edges:
                raise HydraDBError(
                    "HydraDB ingestion readback mismatch: "
                    f"nodes={node_counts} expected_nodes={expected_nodes}; "
                    f"edges={relationship_counts} expected_edges={expected_edges}"
                )
        result = client.query(
            "MATCH (n:Incident) RETURN count(*) AS node_count"
        )
        report = {
            "status": "ok",
            "probe_rows": len(_rows(probe)),
            "node_count_rows": _rows(result),
            "hydradb": client.telemetry(),
        }
        if args.ingest:
            report["ingestion_readback"] = {
                "node_counts": node_counts,
                "relationship_counts": relationship_counts,
                "expected_nodes": expected_nodes,
                "expected_relationships": expected_edges,
            }
        print(json.dumps(report, indent=2, default=str))
        if client.last_read_epoch is None:
            raise HydraDBError(
                "HydraDB responded but exposed no read_epoch/bookmark; "
                "do not claim snapshot-consistent integration yet"
            )
        return 0
    except HydraDBError as error:
        print(f"PathContext HydraDB smoke test failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
