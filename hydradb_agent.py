"""CLI entry point for the live HydraDB-backed agent context tool."""

from __future__ import annotations

import argparse
import json
import os

from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError
from pathcontext.hydradb_retriever import HydraDBContextCompiler
from pathcontext.answer import render_answer


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--budget", type=int, default=800)
    parser.add_argument("--json", action="store_true", help="print only the packet JSON")
    args = parser.parse_args()
    client = HydraDBClient(
        base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
        graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
        cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
        token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
    )
    try:
        packet = HydraDBContextCompiler(client).compile(
            args.question, context_budget_tokens=args.budget
        )
    except (HydraDBError, ValueError) as error:
        print(f"PathContext HydraDB retrieval failed: {error}")
        return 1
    if not args.json:
        print("\nANSWER\n" + render_answer(args.question, packet))
        print("\nEVIDENCE\n")
    print(json.dumps(packet.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
