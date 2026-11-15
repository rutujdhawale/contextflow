"""Explicit, bounded traversal recipes for the incident demonstration."""

from __future__ import annotations

from datetime import datetime

from .graph import GraphStore
from .schema import Entity, EvidencePath, Relationship, parse_time


def _step(
    graph: GraphStore,
    entity: Entity,
    relationship_type: str,
    direction: str = "outgoing",
) -> list[tuple[Relationship, Entity]]:
    return (
        graph.outgoing(entity, relationship_type)
        if direction == "outgoing"
        else graph.incoming(entity, relationship_type)
    )


def change_attribution(
    graph: GraphStore, incident: Entity, max_paths: int = 20
) -> list[EvidencePath]:
    incident_time = parse_time(incident.properties.get("occurred_at"))
    paths: list[EvidencePath] = []
    for affects, service in _step(graph, incident, "AFFECTS"):
        for deployed, deployment in _step(graph, service, "DEPLOYED_AS"):
            deployed_at = parse_time(deployment.properties.get("deployed_at"))
            if incident_time and deployed_at and deployed_at > incident_time:
                continue
            for contains, commit in _step(graph, deployment, "CONTAINS"):
                for touched, file in _step(graph, commit, "TOUCHED"):
                    paths.append(
                        EvidencePath(
                            (incident, service, deployment, commit, file),
                            (affects, deployed, contains, touched),
                            _score(deployment, incident_time),
                            "change_attribution",
                        )
                    )
    return sorted(paths, key=lambda path: path.score, reverse=True)[:max_paths]


def ownership_resolution(
    graph: GraphStore, incident: Entity, max_paths: int = 20
) -> list[EvidencePath]:
    paths: list[EvidencePath] = []
    for change in change_attribution(graph, incident, max_paths):
        file = change.nodes[-1]
        for owned, team in _step(graph, file, "OWNED_BY"):
            paths.append(
                EvidencePath(
                    change.nodes + (team,),
                    change.relationships + (owned,),
                    change.score + 1.0,
                    "ownership_resolution",
                )
            )
    return sorted(paths, key=lambda path: path.score, reverse=True)[:max_paths]


def historical_precedent(
    graph: GraphStore, incident: Entity, max_paths: int = 20
) -> list[EvidencePath]:
    incident_time = parse_time(incident.properties.get("occurred_at"))
    paths: list[EvidencePath] = []
    for affects, service in _step(graph, incident, "AFFECTS"):
        for reverse_affects, previous in _step(graph, service, "AFFECTS", "incoming"):
            if previous.id == incident.id:
                continue
            previous_time = parse_time(previous.properties.get("occurred_at"))
            if incident_time and previous_time and previous_time >= incident_time:
                continue
            for resolved, mitigation in _step(graph, previous, "RESOLVED_BY"):
                if mitigation.properties.get("outcome", "successful") != "successful":
                    continue
                paths.append(
                    EvidencePath(
                        (incident, service, previous, mitigation),
                        (affects, reverse_affects, resolved),
                        3.0,
                        "historical_precedent",
                    )
                )
    return sorted(paths, key=lambda path: path.score, reverse=True)[:max_paths]


def runbook_resolution(
    graph: GraphStore, incident: Entity, max_paths: int = 20
) -> list[EvidencePath]:
    paths: list[EvidencePath] = []
    for affects, service in _step(graph, incident, "AFFECTS"):
        for runbook_edge, runbook in _step(graph, service, "HAS_RUNBOOK"):
            paths.append(
                EvidencePath(
                    (incident, service, runbook),
                    (affects, runbook_edge),
                    2.0,
                    "runbook_resolution",
                )
            )
    return paths[:max_paths]


def _score(deployment: Entity, incident_time: datetime | None) -> float:
    deployed_at = parse_time(deployment.properties.get("deployed_at"))
    if not incident_time or not deployed_at:
        return 1.0
    minutes = max((incident_time - deployed_at).total_seconds() / 60, 0)
    return max(0.1, 10.0 - minutes / 60.0)
