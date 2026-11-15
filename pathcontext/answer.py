"""Grounded, dependency-free answer rendering for the demo."""

from __future__ import annotations

from .schema import EvidencePacket


def render_answer(question: str, packet: EvidencePacket) -> str:
    """Render an answer using only facts present in the evidence packet.

    This is intentionally deterministic so the demo works without API keys.
    An LLM can still be used later for wording, but it receives the same
    packet and cannot add evidence.
    """
    if not packet.facts:
        return "I cannot answer from the available evidence."

    by_source = {fact.source.removeprefix("hydradb:"): fact for fact in packet.facts}
    lines: list[str] = []
    change = by_source.get("change")
    history = by_source.get("history")
    runbook = by_source.get("runbook")
    if change:
        lines.append(f"The change path is: {change.text}.")
    if history:
        lines.append(f"Previous mitigation evidence: {history.text}.")
    if runbook:
        lines.append(f"Relevant runbook: {runbook.text}.")
    if not lines:
        lines.append("Relevant evidence: " + " ".join(fact.text for fact in packet.facts))
    if packet.missing_evidence:
        lines.append(
            "I cannot fully support every part of the question because evidence "
            "is missing for: " + ", ".join(packet.missing_evidence) + "."
        )
    if packet.uncertainty:
        lines.append("Uncertainty: " + " ".join(packet.uncertainty))
    return " ".join(lines)
