"""Repeatable evaluation of quality, graph work, and baseline improvement."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from ingest import load_fixture
from pathcontext.baseline import lexical_baseline
from pathcontext.context_compiler import ContextCompiler
from pathcontext.plain_store import PlainStore


CASES = [
    {
        "name": "multi-hop attribution",
        "question": "Which change caused INC-1042 and who owns it?",
        "gold": {"Deployment:deploy-8842", "Team:Payments-Platform"},
    },
    {
        "name": "historical mitigation",
        "question": "What worked previously for INC-1042?",
        "gold": {"Incident:INC-991", "Mitigation:mit-77"},
    },
    {
        "name": "runbook lookup",
        "question": "Which runbook applies to INC-1042?",
        "gold": {"Runbook:runbook-checkout"},
    },
]


def _records(store):
    return list(store.entities.values()), list(store.relationships)


def _quality(packet, gold: set[str]) -> dict[str, float]:
    returned = {item for fact in packet.facts for item in fact.path}
    recall = len(returned & gold) / len(gold)
    citation_accuracy = (
        sum(bool(fact.source and fact.path) for fact in packet.facts) / len(packet.facts)
        if packet.facts
        else 0.0
    )
    unsupported_claim_rate = (
        sum(not fact.source or not fact.path for fact in packet.facts) / len(packet.facts)
        if packet.facts
        else 0.0
    )
    input_tokens = float(packet.retrieval_stats["input_tokens"])
    return {
        "relevant_fact_recall": recall,
        "citation_accuracy": citation_accuracy,
        "unsupported_claim_rate": unsupported_claim_rate,
        "context_density_per_1000_tokens": (
            recall * 1000 / input_tokens if input_tokens else 0.0
        ),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows]

    return {
        "runs": len(rows),
        "mean": {key: round(statistics.fmean(values(key)), 4) for key in rows[0] if key != "seed"},
        "p50": {
            key: round(statistics.median(values(key)), 4)
            for key in rows[0]
            if key != "seed"
        },
        "p95": {
            key: round(sorted(values(key))[max(0, int(len(rows) * 0.95) - 1)], 4)
            for key in rows[0]
            if key != "seed"
        },
    }


def run_evaluation(
    fixture: Path,
    *,
    repetitions: int = 10,
    context_budget_tokens: int = 800,
    seed: int = 7,
) -> dict[str, Any]:
    graph = load_fixture(fixture)
    entities, relationships = _records(graph)
    graph_compiler = ContextCompiler(graph)
    plain_compiler = ContextCompiler(PlainStore(entities, relationships))
    rows: dict[str, list[dict[str, Any]]] = {
        "pathcontext_graph": [],
        "pathcontext_plain_store": [],
        "lexical_baseline": [],
    }
    rng = random.Random(seed)
    for repetition in range(repetitions):
        run_seed = rng.randrange(1_000_000)
        cases = CASES.copy()
        random.Random(run_seed).shuffle(cases)
        for case in cases:
            graph_packet = graph_compiler.compile(
                case["question"], context_budget_tokens=context_budget_tokens
            )
            plain_packet = plain_compiler.compile(
                case["question"], context_budget_tokens=context_budget_tokens
            )
            baseline_packet = lexical_baseline(
                graph, case["question"], context_budget_tokens=context_budget_tokens
            )
            for name, packet in (
                ("pathcontext_graph", graph_packet),
                ("pathcontext_plain_store", plain_packet),
                ("lexical_baseline", baseline_packet),
            ):
                quality = _quality(packet, case["gold"])
                rows[name].append(
                    {
                        "seed": run_seed,
                        **quality,
                        "input_tokens": packet.retrieval_stats["input_tokens"],
                        "latency_ms": packet.retrieval_stats["latency_ms"],
                        "edge_scans": packet.retrieval_stats.get("edge_scans", 0),
                    }
                )
    summary = {name: _summarize(values) for name, values in rows.items()}
    graph_mean = summary["pathcontext_graph"]["mean"]
    baseline_mean = summary["lexical_baseline"]["mean"]
    plain_mean = summary["pathcontext_plain_store"]["mean"]
    return {
        "protocol": {
            "repetitions": repetitions,
            "seed": seed,
            "fixture": str(fixture),
            "same_questions_and_budget": True,
            "baseline": "top-k lexical entity records with no relationship joins",
            "graph_test": "same compiler and records through an unindexed plain store",
        },
        "systems": summary,
        "improvement_over_lexical_baseline": {
            "relevant_fact_recall_delta": round(
                graph_mean["relevant_fact_recall"] - baseline_mean["relevant_fact_recall"], 4
            ),
            "citation_accuracy_delta": round(
                graph_mean["citation_accuracy"] - baseline_mean["citation_accuracy"], 4
            ),
        },
        "graph_work": {
            "edge_scan_reduction_vs_plain_store": round(
                1 - graph_mean["edge_scans"] / max(plain_mean["edge_scans"], 1), 4
            ),
            "interpretation": "Indexed adjacency should reduce scans as the graph grows; quality must remain equal.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_evaluation(
        Path(__file__).parent / "fixtures" / "incidents.json",
        repetitions=args.repetitions,
        seed=args.seed,
    )
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
