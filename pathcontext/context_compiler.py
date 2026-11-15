"""Compile bounded graph paths into a compact, provenance-preserving packet."""

from __future__ import annotations

import time
from collections import defaultdict

from .entity_resolution import resolve_entity_states
from .evidence_requirements import covered_evidence, missing_evidence, required_evidence
from .graph import GraphStore
from .schema import EvidencePacket, EvidencePath, Fact
from .traversal_recipes import (
    change_attribution,
    historical_precedent,
    ownership_resolution,
    runbook_resolution,
)


class ContextCompiler:
    def __init__(
        self,
        graph: GraphStore,
        *,
        max_hops: int = 6,
        max_paths: int = 20,
        max_edges: int = 500,
    ) -> None:
        self.graph = graph
        self.max_hops = max_hops
        self.max_paths = max_paths
        self.max_edges = max_edges

    def compile(
        self,
        question: str,
        *,
        seed_entities: list[dict[str, str]] | None = None,
        context_budget_tokens: int = 800,
    ) -> EvidencePacket:
        started = time.perf_counter()
        self.graph.reset_metrics()
        seeds, resolution = resolve_entity_states(question, self.graph, seed_entities)
        incidents = [entity for entity in seeds if entity.type.lower() == "incident"]
        paths: list[EvidencePath] = []
        for incident in incidents[: self.max_paths]:
            paths.extend(change_attribution(self.graph, incident, self.max_paths))
            paths.extend(ownership_resolution(self.graph, incident, self.max_paths))
            paths.extend(historical_precedent(self.graph, incident, self.max_paths))
            paths.extend(runbook_resolution(self.graph, incident, self.max_paths))
        paths = [path for path in paths if len(path.nodes) - 1 <= self.max_hops]
        facts = self._select_facts(paths, context_budget_tokens)
        contradictions = self._find_contradictions(paths)
        uncertainty = self._find_uncertainty(seeds, paths, resolution)
        required = required_evidence(question)
        recipe_names = {
            "change_attribution": "change",
            "ownership_resolution": "owner",
            "historical_precedent": "history",
            "runbook_resolution": "runbook",
        }
        covered = covered_evidence(
            required,
            (recipe_names.get(path.recipe, path.recipe) for path in paths),
        )
        missing = missing_evidence(required, covered)
        if missing:
            uncertainty.append("Missing required evidence: " + ", ".join(missing))
        answerability = self._answerability(facts, contradictions, uncertainty, missing)
        context = self._render(facts, contradictions, uncertainty)
        return EvidencePacket(
            context=context,
            facts=facts,
            contradictions=contradictions,
            uncertainty=uncertainty,
            answerability=answerability,
            retrieval_stats={
                "nodes_traversed": min(self.graph.node_count, self.max_edges),
                "edges_traversed": min(self.graph.edge_count, self.max_edges),
                "input_tokens": sum(fact.token_cost for fact in facts),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "read_epoch": "local",
                **self.graph.metrics(),
            },
            required_evidence=required,
            covered_evidence=covered,
            missing_evidence=missing,
            entity_resolution=tuple(resolution),
        )

    def _select_facts(self, paths: list[EvidencePath], budget: int) -> list[Fact]:
        facts: list[Fact] = []
        seen: set[tuple[str, ...]] = set()
        for path in sorted(paths, key=lambda item: item.score, reverse=True):
            fact = _path_to_fact(path)
            if fact.path in seen or fact.token_cost + sum(f.token_cost for f in facts) > budget:
                continue
            seen.add(fact.path)
            facts.append(fact)
        return facts

    @staticmethod
    def _find_contradictions(paths: list[EvidencePath]) -> list[str]:
        by_incident: dict[str, list[EvidencePath]] = defaultdict(list)
        for path in paths:
            if path.recipe == "change_attribution":
                by_incident[path.nodes[0].id].append(path)
        contradictions: list[str] = []
        for incident_id, candidates in by_incident.items():
            deployments = {path.nodes[2].id for path in candidates}
            if len(deployments) > 1:
                contradictions.append(
                    f"{incident_id} has multiple plausible deployments: "
                    + ", ".join(sorted(deployments))
                )
        return contradictions

    @staticmethod
    def _find_uncertainty(
        seeds: list, paths: list[EvidencePath], resolution: list[dict[str, object]]
    ) -> list[str]:
        states = {item.get("state") for item in resolution}
        uncertainty: list[str] = []
        if "ambiguous" in states:
            uncertainty.append("One or more question entities are ambiguous.")
        if "unresolved" in states and not seeds:
            uncertainty.append("The question entity could not be resolved.")
        if not seeds:
            return uncertainty or ["No known seed entity was resolved from the question."]
        if not paths:
            uncertainty.append("No tested traversal recipe produced a connected evidence path.")
        return uncertainty

    @staticmethod
    def _answerability(
        facts: list[Fact],
        contradictions: list[str],
        uncertainty: list[str],
        missing: tuple[str, ...] = (),
    ) -> str:
        if not facts:
            return "insufficient"
        if contradictions:
            return "contradictory"
        if uncertainty or missing:
            return "mixed"
        return "supported"

    @staticmethod
    def _render(
        facts: list[Fact], contradictions: list[str], uncertainty: list[str]
    ) -> str:
        lines = ["Evidence:"]
        lines.extend(f"- {fact.text} [source: {fact.source}]" for fact in facts)
        if contradictions:
            lines.append("Contradictions:")
            lines.extend(f"- {item}" for item in contradictions)
        if uncertainty:
            lines.append("Uncertainty:")
            lines.extend(f"- {item}" for item in uncertainty)
        return "\n".join(lines)


def _path_to_fact(path: EvidencePath) -> Fact:
    names = [f"{node.type.lower()} {node.id}" for node in path.nodes]
    text = " -> ".join(names)
    token_cost = max(1, len(text.split()))
    return Fact(
        text=text,
        source=path.source,
        path=tuple(path.labels),
        confidence="supported" if path.score >= 2 else "mixed",
        score=path.score,
        token_cost=token_cost,
    )
