"""PDF-to-HydraDB ingestion and graph-backed question answering.

The PDF remains a source artifact. HydraDB stores page and chunk metadata plus
text, while retrieval always returns the document/page/chunk path as evidence.
Extraction prefers the system ``pdftotext`` command and falls back to the
Python ``pypdf`` package when Poppler is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError
from pathcontext.hydradb_ingest import write_graph
from pathcontext.llm import LLMError, synthesize
from pathcontext.schema import EvidencePacket, Fact


DATA_DIR = Path(__file__).parent / "data"
FILES_DIR = DATA_DIR / "files"


def _configured(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith(("replace-with", "your-")):
        return None
    return value


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "PDF extraction requires pdftotext and pdfinfo. "
            "Install poppler-utils, then rerun."
        ) from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip()
        raise RuntimeError(f"PDF extraction failed: {detail}") from error
    return result.stdout


def copy_pdf(source: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PDF not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file: {source}")
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    target = FILES_DIR / source.name
    if source != target:
        shutil.copy2(source, target)
    return target


def extract_pages(pdf: Path) -> list[str]:
    try:
        metadata = _run(["pdfinfo", str(pdf)])
        pages_line = next(
            (line for line in metadata.splitlines() if line.startswith("Pages:")),
            "",
        )
        page_count = int(pages_line.split(":", 1)[1].strip())
        return [
            " ".join(
                _run(
                    [
                        "pdftotext",
                        "-layout",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        str(pdf),
                        "-",
                    ]
                ).split()
            )
            for page in range(1, page_count + 1)
        ]
    except (FileNotFoundError, RuntimeError, IndexError, ValueError):
        reader = PdfReader(str(pdf))
        return [" ".join((page.extract_text() or "").split()) for page in reader.pages]


def _id(prefix: str, value: str) -> int:
    digest = hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()
    return int(digest[:12], 16) % 2_000_000_000


def _cypher(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ") + "'"


def _chunks(text: str, size: int = 900) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if current and length + len(word) + 1 > size:
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += len(word) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


def pdf_statements(pdf: Path, pages: list[str]) -> list[str]:
    document_id = _id("document", str(pdf.name))
    statements = [
        f"MERGE (d:Document {{id: {document_id}}})",
        f"MATCH (d:Document {{id: {document_id}}}) SET "
        f"d.external_id = {_cypher(pdf.name)}, d.source_file = {_cypher(str(pdf))}",
    ]
    previous_chunk_id: int | None = None
    for page_number, text in enumerate(pages, start=1):
        page_id = _id("page", f"{pdf.name}:{page_number}")
        statements.extend(
            [
                f"MERGE (p:Page {{id: {page_id}}})",
                f"MATCH (p:Page {{id: {page_id}}}) SET "
                f"p.external_id = {_cypher(f'{pdf.name}:page:{page_number}')}, "
                f"p.page_number = {page_number}, p.text = {_cypher(text)}",
                f"MERGE (d:Document {{id: {document_id}}})-[:HAS_PAGE]->"
                f"(p:Page {{id: {page_id}}})",
            ]
        )
        for chunk_number, chunk in enumerate(_chunks(text), start=1):
            chunk_id = _id("chunk", f"{pdf.name}:{page_number}:{chunk_number}")
            statements.extend(
                [
                    f"MERGE (c:Chunk {{id: {chunk_id}}})",
                    f"MATCH (c:Chunk {{id: {chunk_id}}}) SET "
                    f"c.external_id = {_cypher(f'{pdf.name}:p{page_number}:c{chunk_number}')}, "
                    f"c.page_number = {page_number}, c.chunk_number = {chunk_number}, "
                    f"c.text = {_cypher(chunk)}",
                    f"MERGE (p:Page {{id: {page_id}}})-[:HAS_CHUNK]->"
                    f"(c:Chunk {{id: {chunk_id}}})",
                ]
            )
            if previous_chunk_id is not None:
                statements.append(
                    f"MERGE (previous:Chunk {{id: {previous_chunk_id}}})"
                    f"-[:NEXT_CHUNK]->(c:Chunk {{id: {chunk_id}}})"
                )
            previous_chunk_id = chunk_id
    return statements


def pdf_graph(pdf: Path, pages: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    document_id = _id("document", pdf.name)
    nodes: list[dict[str, Any]] = [{
        "id": document_id, "label": "Document", "external_id": pdf.name,
        "properties": {"source_file": str(pdf)},
    }]
    edges: list[dict[str, Any]] = []
    previous_chunk_id: int | None = None
    for page_number, text in enumerate(pages, start=1):
        page_id = _id("page", f"{pdf.name}:{page_number}")
        nodes.append({
            "id": page_id, "label": "Page",
            "external_id": f"{pdf.name}:page:{page_number}",
            "properties": {"page_number": page_number, "text": text},
        })
        edges.append({"src": document_id, "dst": page_id, "type": "HAS_PAGE"})
        for chunk_number, chunk in enumerate(_chunks(text), start=1):
            chunk_id = _id("chunk", f"{pdf.name}:{page_number}:{chunk_number}")
            nodes.append({
                "id": chunk_id, "label": "Chunk",
                "external_id": f"{pdf.name}:p{page_number}:c{chunk_number}",
                "properties": {
                    "page_number": page_number,
                    "chunk_number": chunk_number,
                    "text": chunk,
                },
            })
            edges.append({"src": page_id, "dst": chunk_id, "type": "HAS_CHUNK"})
            if previous_chunk_id is not None:
                edges.append({"src": previous_chunk_id, "dst": chunk_id, "type": "NEXT_CHUNK"})
            previous_chunk_id = chunk_id
    return nodes, edges


def _decode(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def retrieve(client: HydraDBClient, document_name: str, question: str) -> EvidencePacket:
    payload = client.query(
        "MATCH (d:Document {external_id: %s})-[:HAS_PAGE]->(p:Page)"
        "-[:HAS_CHUNK]->(c:Chunk) "
        "RETURN d.external_id AS document, p.page_number AS page, "
        "c.external_id AS chunk, c.text AS text"
        % _cypher(document_name)
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise HydraDBError("HydraDB returned no document chunk rows")
    question_terms = set(question.lower().split())
    candidates: list[Fact] = []
    for row in payload["rows"]:
        values = [_decode(item) for item in row]
        if len(values) < 4:
            continue
        document, page, chunk, text = values[:4]
        text_value = str(text)
        score = sum(term in text_value.lower() for term in question_terms)
        candidates.append(
            Fact(
                text=text_value,
                source="hydradb:pdf",
                path=(f"Document:{document}", f"Page:{page}", f"Chunk:{chunk}"),
                confidence="retrieved",
                score=float(score),
                token_cost=max(1, len(text_value.split())),
            )
        )
    facts = sorted(candidates, key=lambda item: item.score, reverse=True)[:6]
    uncertainty = [] if facts and facts[0].score else ["No question terms matched; inspect citations carefully."]
    context = "\n".join(
        f"- {fact.text} [citation: {' -> '.join(fact.path)}]"
        for fact in facts
    )
    return EvidencePacket(
        context=context,
        facts=facts,
        contradictions=[],
        uncertainty=uncertainty,
        answerability="supported" if facts and facts[0].score else "insufficient",
        retrieval_stats={**client.telemetry(), "candidate_chunks": len(candidates)},
    )


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ingest and query a PDF via HydraDB")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--question")
    args = parser.parse_args()
    try:
        target = copy_pdf(args.pdf)
        pages = extract_pages(target)
        client = HydraDBClient(
            base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
            graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
            cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
            token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
        )
        if args.ingest:
            nodes, edges = pdf_graph(target, pages)
            write_graph(client, nodes, edges)
            print(json.dumps({"status": "ingested", "file": str(target), "pages": len(pages)}))
        if args.question:
            packet = retrieve(client, target.name, args.question)
            output: dict[str, Any] = {"packet": packet.to_dict()}
            groq_key = _configured("GROQ_API_KEY")
            if packet.answerability == "supported" and groq_key:
                try:
                    output["answer"] = synthesize(
                        args.question, packet,
                        groq_api_key=groq_key,
                        groq_model=os.getenv("GROQ_MODEL"),
                    ).__dict__
                except LLMError as error:
                    output["llm_error"] = str(error)
            print(json.dumps(output, indent=2, default=str))
        return 0
    except (HydraDBError, OSError, RuntimeError, ValueError) as error:
        print(f"PDF pipeline failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
