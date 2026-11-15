"""Evaluate incremental graph ingestion instead of claiming model learning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ingest import load_fixture
from pathcontext.baseline import lexical_baseline
from pathcontext.context_compiler import ContextCompiler
from pathcontext.schema import Entity, Relationship
from evaluate import _quality


INCREMENT = (
    [
        Entity(
            "INC-1050",
            "Incident",
            {"occurred_at": "2025-03-10T12:00:00+00:00", "category": "latency"},
        ),
        Entity("billing-api", "Service"),
        Entity("deploy-9001", "Deployment", {"deployed_at": "2025-03-10T11:35:00+00:00"}),
        Entity("commit-801", "Commit"),
        Entity("invoice-client.py", "File"),
        Entity("Billing-Platform", "Team"),
    ],
    [
        Relationship("INC-1050", "Incident", "AFFECTS", "billing-api", "Service"),
        Relationship("billing-api", "Service", "DEPLOYED_AS", "deploy-9001", "Deployment"),
        Relationship("deploy-9001", "Deployment", "CONTAINS", "commit-801", "Commit"),
        Relationship("commit-801", "Commit", "TOUCHED", "invoice-client.py", "File"),
        Relationship("invoice-client.py", "File", "OWNED_BY", "Billing-Platform", "Team"),
    ],
)


def run_continual_evaluation(fixture: Path) -> dict:
    graph = load_fixture(fixture)
    compiler = ContextCompiler(graph)
    question = "Which change caused INC-1050 and who owns it?"
    gold = {"Deployment:deploy-9001", "Team:Billing-Platform"}
    before = compiler.compile(question)
    before_baseline = lexical_baseline(graph, question)
    graph.extend(*INCREMENT)
    after = compiler.compile(question)
    after_baseline = lexical_baseline(graph, question)
    return {
        "protocol": {
            "rounds": ["before_increment", "after_increment"],
            "increment": "new incident, service, deployment, commit, file, and team",
            "meaning": "This tests continual graph ingestion and deterministic re-indexing; it is not an ML training claim.",
        },
        "pathcontext": {
            "before": _quality(before, gold),
            "after": _quality(after, gold),
            "after_answerability": after.answerability,
        },
        "lexical_baseline": {
            "before": _quality(before_baseline, gold),
            "after": _quality(after_baseline, gold),
        },
        "acceptance": {
            "new_evidence_retrieved": _quality(after, gold)["relevant_fact_recall"] == 1.0,
            "no_pre_ingestion_claim": _quality(before, gold)["relevant_fact_recall"] == 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_continual_evaluation(
        Path(__file__).parent / "fixtures" / "incidents.json"
    )
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
