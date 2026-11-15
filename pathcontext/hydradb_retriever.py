"""HydraDB-backed context compiler for the incident demonstration."""

from __future__ import annotations

import time
import re
from typing import Any

from .hydradb_client import HydraDBClient, HydraDBError
from .evidence_requirements import covered_evidence, missing_evidence, required_evidence
from .schema import EvidencePacket, Fact


def _recipes(incident_id: str) -> dict[str, str]:
    escaped_id = incident_id.replace("\\", "\\\\").replace("'", "\\'")
    return {
    "change": (
        f"MATCH (i:Incident {{external_id: '{escaped_id}'}})-[:AFFECTS]->(s)"
        "-[:DEPLOYED_AS]->(d)-[:CONTAINS]->(c)"
        "-[:TOUCHED]->(f)-[:OWNED_BY]->(t) "
        "RETURN i.external_id AS incident, s.external_id AS service, "
        "d.external_id AS deployment, c.external_id AS commit, "
        "f.external_id AS file, t.external_id AS team"
    ),
    "history": (
        f"MATCH (i:Incident {{external_id: '{escaped_id}'}})-[:AFFECTS]->(s)"
        "<-[:AFFECTS]-(p)-[:RESOLVED_BY]->(m) "
        "RETURN i.external_id AS incident, s.external_id AS service, "
        "p.external_id AS previous_incident, m.external_id AS mitigation"
    ),
    "runbook": (
        f"MATCH (i:Incident {{external_id: '{escaped_id}'}})-[:AFFECTS]->(s)"
        "-[:HAS_RUNBOOK]->(r) "
        "RETURN i.external_id AS incident, s.external_id AS service, "
        "r.external_id AS runbook"
    ),
    }


def _service_recipes(service_id: str) -> dict[str, str]:
    escaped_id = service_id.replace("\\", "\\\\").replace("'", "\\'")
    return {
        "runbook": (
            f"MATCH (s:Service {{external_id: '{escaped_id}'}})-[:HAS_RUNBOOK]->(r) "
            "RETURN s.external_id AS service, r.external_id AS runbook"
        )
    }


class HydraDBContextCompiler:
    """Compile context using HydraDB for relationship traversal."""

    def __init__(self, client: HydraDBClient) -> None:
        self.client = client

    def compile(self, question: str, context_budget_tokens: int = 800) -> EvidencePacket:
        if not question.strip():
            raise ValueError("question must not be empty")
        if context_budget_tokens < 1:
            raise ValueError("context_budget_tokens must be positive")
        started = time.perf_counter()
        incident_id = _incident_id(question)
        service_id = _service_id(question)
        service_runbook_question = service_id is not None and _asks_for_runbook(question)
        if incident_id is None and not service_runbook_question:
            required = required_evidence(question)
            return EvidencePacket(
                context="Uncertainty:\n- No incident ID was resolved from the question.",
                facts=[],
                contradictions=[],
                uncertainty=["No incident ID was resolved from the question."],
                answerability="insufficient",
                retrieval_stats={**self.client.telemetry(), "recipe_count": 0},
                required_evidence=required,
                missing_evidence=required,
            )
        if incident_id is not None:
            selected = self._select_recipes(question)
            recipes = _recipes(incident_id)
            required = required_evidence(question)
        else:
            selected = ["runbook"]
            recipes = _service_recipes(service_id)
            required = ("runbook",)
        facts: list[Fact] = []
        epochs: list[str | int] = []
        for recipe in selected:
            payload = self.client.query(recipes[recipe])
            if isinstance(payload, dict):
                epoch = payload.get("read_epoch", payload.get("bookmark"))
                if isinstance(epoch, (str, int)):
                    epochs.append(epoch)
            facts.extend(self._facts_from_response(recipe, payload))
        facts = _select_budget(facts, context_budget_tokens)
        covered = covered_evidence(
            required, (fact.source.removeprefix("hydradb:") for fact in facts)
        )
        if "owner" in required and any(
            any(part.startswith("team:") for part in fact.path) for fact in facts
        ):
            covered = tuple(dict.fromkeys((*covered, "owner")))
        missing = missing_evidence(required, covered)
        snapshot_consistent = len(set(epochs)) <= 1
        uncertainty = (
            []
            if facts
            else ["HydraDB returned no connected evidence for the selected recipes."]
        )
        if missing:
            uncertainty.append("Missing required evidence: " + ", ".join(missing))
        if not snapshot_consistent:
            uncertainty.append(
                "Recipes were read at different HydraDB epochs; this packet is non-atomic."
            )
        answerability = (
            "supported"
            if facts and not missing and snapshot_consistent
            else "mixed"
            if facts
            else "insufficient"
        )
        return EvidencePacket(
            context=_render(facts, uncertainty),
            facts=facts,
            contradictions=[],
            uncertainty=uncertainty,
            answerability=answerability,
            retrieval_stats={
                **self.client.telemetry(),
                "recipe_count": len(selected),
                "input_tokens": sum(fact.token_cost for fact in facts),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "snapshot_consistency": "atomic" if snapshot_consistent else "non_atomic",
                "read_epochs": ",".join(str(epoch) for epoch in dict.fromkeys(epochs)),
            },
            required_evidence=required,
            covered_evidence=covered,
            missing_evidence=missing,
        )

    @staticmethod
    def _select_recipes(question: str) -> list[str]:
        lowered = question.lower()
        selected = ["change"]
        if any(word in lowered for word in ("previous", "worked", "mitigation", "history")):
            selected.append("history")
        if "runbook" in lowered:
            selected.append("runbook")
        return selected

    @staticmethod
    def _facts_from_response(recipe: str, payload: Any) -> list[Fact]:
        if not isinstance(payload, dict):
            raise HydraDBError("HydraDB returned a non-object query response")
        rows = payload.get("rows")
        columns = payload.get("columns")
        if not isinstance(rows, list) or not isinstance(columns, list):
            raise HydraDBError("HydraDB response is missing rows or columns")
        facts = []
        seen: set[tuple[str, ...]] = set()
        for row in rows:
            values = [_decode_value(value) for value in row]
            record = dict(zip(columns, values))
            labels = tuple(f"{name}:{value}" for name, value in record.items())
            if labels in seen:
                continue
            seen.add(labels)
            text = " -> ".join(f"{name} {value}" for name, value in record.items())
            facts.append(
                Fact(
                    text=text,
                    source=f"hydradb:{recipe}",
                    path=labels,
                    confidence="supported",
                    score=3.0 if recipe == "change" else 2.0,
                    token_cost=max(1, len(text.split())),
                )
            )
        return facts


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _incident_id(question: str) -> str | None:
    match = re.search(r"\bINC-[A-Za-z0-9_-]+\b", question, re.IGNORECASE)
    return match.group(0) if match else None


def _service_id(question: str) -> str | None:
    match = re.search(r"\b[A-Za-z][A-Za-z0-9_-]*-api\b", question, re.IGNORECASE)
    return match.group(0) if match else None


def _asks_for_runbook(question: str) -> bool:
    lowered = question.casefold()
    return "runbook" in lowered or any(
        phrase in lowered
        for phrase in (
            "should be used",
            "should used",
            "to use",
            "use for",
            "applies to",
        )
    )


def _select_budget(facts: list[Fact], budget: int) -> list[Fact]:
    selected: list[Fact] = []
    used = 0
    for fact in sorted(facts, key=lambda item: item.score, reverse=True):
        if used + fact.token_cost > budget:
            continue
        selected.append(fact)
        used += fact.token_cost
    return selected


def _render(facts: list[Fact], uncertainty: list[str]) -> str:
    lines = ["Evidence:"]
    lines.extend(f"- {fact.text} [source: {fact.source}]" for fact in facts)
    if uncertainty:
        lines.append("Uncertainty:")
        lines.extend(f"- {item}" for item in uncertainty)
    return "\n".join(lines)
