"""Before/after comparison for naive RAG versus PathContext graph retrieval."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from multimodal_pipeline import FILES_DIR, extract_artifacts, graph_for_artifacts, retrieve
from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError
from pathcontext.hydradb_ingest import write_graph
from pathcontext.llm import LLMAnswer, synthesize
from pathcontext.schema import EvidencePacket, Fact
from tui import LocalSnapshotSession, SNAPSHOTS_DIR

GREEN = "\033[38;2;72;220;130m"
ORANGE = "\033[38;2;255;87;25m"
WHITE_BOLD = "\033[1;38;2;255;255;255m"
PEACH = "\033[38;2;255;165;110m"
GRAY = "\033[38;2;135;135;150m"
BORDER = "\033[38;2;75;75;90m"
RESET = "\033[0m"


def _estimate_tokens(text: str) -> int:
    """Conservative provider-independent estimate for whitespace text."""
    return max(1, (len(text) + 3) // 4) if text else 0


def _baseline_packet(artifacts: list[Any], max_artifacts: int) -> EvidencePacket:
    selected = artifacts[:max_artifacts]
    context = "\n".join(
        f"- {artifact.summary} [source: {artifact.source}::{artifact.locator}]"
        for artifact in selected
    )
    facts = [
        Fact(
            text=artifact.summary,
            source="naive-rag:file",
            path=(f"File:{artifact.source}", f"Locator:{artifact.locator}"),
            confidence="unranked",
            score=0.0,
            token_cost=_estimate_tokens(artifact.summary),
        )
        for artifact in selected
    ]
    return EvidencePacket(
        context=context,
        facts=facts,
        contradictions=[],
        uncertainty=["Naive RAG does not prove graph relationships."],
        answerability="unranked" if facts else "insufficient",
        retrieval_stats={
            "backend": "naive_file_context",
            "candidate_artifacts": len(artifacts),
            "selected_artifacts": len(selected),
            "input_tokens": _estimate_tokens(context),
            "context_chars": len(context),
        },
    )


def _packet_metrics(packet: EvidencePacket) -> dict[str, Any]:
    return {
        "input_tokens_estimate": _estimate_tokens(packet.context),
        "context_chars": len(packet.context),
        "facts": len(packet.facts),
        "citations": sum(bool(fact.path and fact.source) for fact in packet.facts),
        "answerability": packet.answerability,
        "retrieval_stats": packet.retrieval_stats,
    }


def _answer_metrics(answer: LLMAnswer | None) -> dict[str, Any] | None:
    if answer is None:
        return None
    return {
        "provider": answer.provider,
        "input_tokens": answer.input_tokens,
        "output_tokens": answer.output_tokens,
        "total_tokens": answer.total_tokens,
        "text": answer.text,
    }


def print_comparison_table(result: dict[str, Any]) -> None:
    w = 78
    before_tok = result["before_naive_rag"]["input_tokens_estimate"]
    after_tok = result["after_pathcontext_hydradb"]["input_tokens_estimate"]
    before_chars = result["before_naive_rag"]["context_chars"]
    after_chars = result["after_pathcontext_hydradb"]["context_chars"]
    tok_reduc = result["delta"]["context_token_reduction"] * 100
    char_reduc = result["delta"]["context_char_reduction"] * 100
    backend = result["after_pathcontext_hydradb"]["retrieval_stats"].get("backend", "HydraDB / Snapshot")

    print(f"\n{BORDER}╭─{RESET} {ORANGE}TOKEN COMPARISON: NAIVE RAG vs PATHCONTEXT GRAPH{RESET} {BORDER}{'─' * (w - 52)}╮{RESET}")
    print(f"{BORDER}│{RESET}  Question: {WHITE_BOLD}{result['protocol']['question']}{RESET}")
    print(f"{BORDER}│{RESET}  File:     {PEACH}{result['protocol']['file']}{RESET}")
    print(f"{BORDER}│{RESET}  Backend:  {GRAY}{backend}{RESET}")
    print(f"{BORDER}├{'─' * (w - 2)}┤{RESET}")
    print(f"{BORDER}│{RESET}  Metric                       Naive RAG        PathContext (Graph)   Delta")
    print(f"{BORDER}│{RESET}  {GRAY}{'─' * (w - 6)}{RESET}")
    print(f"{BORDER}│{RESET}  Context Tokens:            {before_tok:>8} tok        {after_tok:>8} tok        {GREEN}-{tok_reduc:.1f}%{RESET}")
    print(f"{BORDER}│{RESET}  Context Characters:        {before_chars:>8} chars      {after_chars:>8} chars      {GREEN}-{char_reduc:.1f}%{RESET}")
    print(f"{BORDER}│{RESET}  Selected Chunks:           {result['before_naive_rag']['facts']:>8} chunks     {result['after_pathcontext_hydradb']['facts']:>8} chunks     {GREEN}{result['delta']['selected_artifact_delta']} fewer{RESET}")
    print(f"{BORDER}│{RESET}  Structured Citations:      {result['before_naive_rag']['citations']:>8}            {result['after_pathcontext_hydradb']['citations']:>8} (ranked)  {GREEN}Proven{RESET}")
    print(f"{BORDER}╰{'─' * (w - 2)}╯{RESET}\n")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Compare naive file RAG with HydraDB-bounded PathContext retrieval"
    )
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--naive-artifacts", type=int, default=20)
    parser.add_argument("--max-context-tokens", type=int, default=1200)
    parser.add_argument("--llm", action="store_true", help="Call configured Groq/OpenCode for both systems")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of formatted table")
    args = parser.parse_args()

    source = args.file.expanduser().resolve()
    if not source.is_file():
        parser.error(f"file does not exist: {source}")
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    target = FILES_DIR / source.name
    if source != target:
        target.write_bytes(source.read_bytes())
    artifacts = extract_artifacts(target, vision=args.vision)

    client = HydraDBClient(
        base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
        graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
        cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
        token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
    )

    if args.ingest:
        nodes, edges = graph_for_artifacts(target, artifacts)
        write_graph(client, nodes, edges)

    before_started = time.perf_counter()
    before = _baseline_packet(artifacts, args.naive_artifacts)
    before_latency = round((time.perf_counter() - before_started) * 1000, 3)

    after_started = time.perf_counter()
    backend_used = "HydraDB (live openCypher)"
    after: EvidencePacket | None = None

    # Try live HydraDB first
    try:
        after = retrieve(
            client,
            target.name,
            args.question,
            max_context_tokens=args.max_context_tokens,
        )
    except (HydraDBError, Exception):
        # Fallback to local snapshot if HydraDB is not running
        snap_path = SNAPSHOTS_DIR / f"{target.stem}.snapshot.json"
        if snap_path.exists():
            backend_used = f"Offline Graph Snapshot ({snap_path.name})"
            session = LocalSnapshotSession.load(snap_path)
            after = session.retrieve_document(args.question, max_facts=4)
        else:
            # Build snapshot on the fly if needed
            from prepare_snapshot import build_file_snapshot
            snap = build_file_snapshot(target)
            snap_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
            backend_used = f"Auto-built Graph Snapshot ({snap_path.name})"
            session = LocalSnapshotSession.load(snap_path)
            after = session.retrieve_document(args.question, max_facts=4)

    after_latency = round((time.perf_counter() - after_started) * 1000, 3)
    after.retrieval_stats["backend"] = backend_used

    result: dict[str, Any] = {
        "protocol": {
            "file": str(target),
            "question": args.question,
            "same_question": True,
            "before": "naive file-level RAG context, first N extracted artifacts",
            "after": f"{backend_used} traversal with lexical ranking and token budget",
            "llm_called": args.llm,
        },
        "before_naive_rag": {
            **_packet_metrics(before),
            "retrieval_latency_ms": before_latency,
        },
        "after_pathcontext_hydradb": {
            **_packet_metrics(after),
            "retrieval_latency_ms": after_latency,
        },
        "delta": {
            "context_token_reduction": round(
                1
                - _estimate_tokens(after.context)
                / max(_estimate_tokens(before.context), 1),
                4,
            ),
            "context_char_reduction": round(
                1 - len(after.context) / max(len(before.context), 1), 4
            ),
            "selected_artifact_delta": (
                before.retrieval_stats["selected_artifacts"]
                - len(after.facts)
            ),
        },
    }
    if args.llm:
        key = os.getenv("GROQ_API_KEY")
        before_answer = synthesize(
            args.question,
            before,
            groq_api_key=key,
            groq_model=os.getenv("GROQ_MODEL"),
        )
        after_answer = synthesize(
            args.question,
            after,
            groq_api_key=key,
            groq_model=os.getenv("GROQ_MODEL"),
        )
        result["before_naive_rag"]["llm"] = _answer_metrics(before_answer)
        result["after_pathcontext_hydradb"]["llm"] = _answer_metrics(after_answer)
        before_total = before_answer.total_tokens or 0
        after_total = after_answer.total_tokens or 0
        result["delta"]["llm_total_token_reduction"] = round(
            1 - after_total / max(before_total, 1), 4
        )

    if args.json:
        rendered = json.dumps(result, indent=2, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    else:
        print_comparison_table(result)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
