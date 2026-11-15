"""Run the incident evidence recipes directly inside HydraDB.

Unlike the local compiler, this module does not reconstruct adjacency in
Python. HydraDB performs the multi-hop joins and returns the selected paths.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ingest import ingest_fixture
from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError


QUERIES = {
    "change_and_owner": """
        MATCH (i:Incident {external_id: 'INC-1042'})-[:AFFECTS]->(s:Service)
              -[:DEPLOYED_AS]->(d:Deployment)-[:CONTAINS]->(c:Commit)
              -[:TOUCHED]->(f:File)-[:OWNED_BY]->(t:Team)
        RETURN DISTINCT i.external_id AS incident, s.external_id AS service,
               d.external_id AS deployment, c.external_id AS commit,
               f.external_id AS file, t.external_id AS team
    """,
    "historical_mitigation": """
        MATCH (i:Incident {external_id: 'INC-1042'})-[:AFFECTS]->(s:Service)
              <-[:AFFECTS]-(previous:Incident)-[:RESOLVED_BY]->(m:Mitigation)
        RETURN DISTINCT i.external_id AS incident, s.external_id AS service,
               previous.external_id AS previous_incident,
               m.external_id AS mitigation
    """,
    "runbook": """
        MATCH (i:Incident {external_id: 'INC-1042'})-[:AFFECTS]->(s:Service)
              -[:HAS_RUNBOOK]->(r:Runbook)
        RETURN DISTINCT i.external_id AS incident, s.external_id AS service,
               r.external_id AS runbook
    """,
}


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run PathContext recipes in HydraDB")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    client = HydraDBClient(
        base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
        graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
        cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
        token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
    )
    try:
        if args.ingest:
            ingest_fixture(
                client, Path(__file__).parent / "fixtures" / "incidents.json"
            )
        results = {name: client.query(query) for name, query in QUERIES.items()}
        print(
            json.dumps(
                {
                    "status": "ok",
                    "recipes": results,
                    "hydradb": client.telemetry(),
                },
                indent=2,
                default=str,
            )
        )
        return 0
    except HydraDBError as error:
        print(f"HydraDB recipe execution failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
