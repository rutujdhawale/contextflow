"""Reproducible hackathon demo runner.

Runs offline evaluation always and the live HydraDB flow when a token is
provided. It writes one JSON report so the demonstration is inspectable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from continual_evaluate import run_continual_evaluation
from evaluate import run_evaluation
from hydradb_smoke import _rows
from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError
from pathcontext.hydradb_retriever import HydraDBContextCompiler


def run_live(question: str) -> dict:
    client = HydraDBClient(
        base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
        graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
        cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
        token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
    )
    probe = client.query("MATCH (n:Incident) RETURN n.id AS probe")
    packet = HydraDBContextCompiler(client).compile(question)
    if not packet.facts or client.last_read_epoch is None:
        raise HydraDBError("live demo did not produce facts and a HydraDB read epoch")
    return {
        "status": "passed",
        "probe_rows": len(_rows(probe)),
        "packet": packet.to_dict(),
        "hydradb": client.telemetry(),
        "source": "prebuilt_hydradb_graph",
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/hackathon_report.json"))
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--require-live", action="store_true", help="require the read-only HydraDB demo")
    args = parser.parse_args()
    fixture = Path(__file__).parent / "fixtures" / "incidents.json"
    report = {
        "demo": "PathContext",
        "question": "Which change caused INC-1042, who owns it, and what worked previously?",
        "offline_evaluation": run_evaluation(fixture, repetitions=args.repetitions),
        "continual_ingestion": run_continual_evaluation(fixture),
    }
    token = os.getenv("PATHCONTEXT_HYDRADB_TOKEN")
    if token:
        try:
            report["live_hydradb"] = run_live(
                "Which change caused INC-1042, who owns it, and what worked previously?",
            )
        except HydraDBError as error:
            report["live_hydradb"] = {"status": "failed", "error": str(error)}
    else:
        report["live_hydradb"] = {
            "status": "not_run",
            "error": "Set PATHCONTEXT_HYDRADB_TOKEN to run live HydraDB acceptance.",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    if args.require_live and report["live_hydradb"]["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
