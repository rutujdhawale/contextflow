"""Token-efficient multimodal ingestion for PDF, text, CSV, and images.

The pipeline keeps raw files local. HydraDB receives a compact graph of
documents and typed artifacts; question answering receives only selected
artifact summaries and source paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pathcontext.env import load_dotenv
from pathcontext.hydradb_client import HydraDBClient, HydraDBError
from pathcontext.hydradb_ingest import write_graph
from pathcontext.llm import LLMError, describe_image, synthesize
from pathcontext.schema import EvidencePacket, Fact
from pdf_pipeline import _chunks, _cypher, _id, extract_pages


FILES_DIR = Path(__file__).parent / "data" / "files"
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".json"}
TABLE_EXTENSIONS = {".csv", ".tsv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class Artifact:
    kind: str
    source: str
    locator: str
    text: str
    summary: str
    raw_bytes: int = 0


def _compact(text: str, limit: int = 1200) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3] + "..."


def _read_table(path: Path) -> list[Artifact]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter))
    if not rows:
        return [Artifact("table", path.name, "header", "", "Empty table")]
    header = rows[0]
    data = rows[1:]
    sample = data[:3]
    summary = (
        f"Table with {len(data)} data rows and {len(header)} columns. "
        f"Columns: {', '.join(header[:30])}. "
        f"Sample rows: {json.dumps(sample, ensure_ascii=False)}"
    )
    return [
        Artifact(
            "table",
            path.name,
            "table",
            json.dumps({"columns": header, "sample_rows": sample}, ensure_ascii=False),
            _compact(summary),
            path.stat().st_size,
        )
    ]


def _read_text(path: Path) -> list[Artifact]:
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = _chunks(text, size=1200) or [""]
    return [
        Artifact(
            "text",
            path.name,
            f"chunk:{index}",
            chunk,
            _compact(chunk),
            path.stat().st_size,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]


def _image_artifact(path: Path, vision_summary: str | None = None) -> Artifact:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    summary = vision_summary or (
        f"Image artifact ({mime}, {path.stat().st_size} bytes). "
        "No vision summary was generated; configure GROQ_API_KEY to analyze it."
    )
    return Artifact(
        "image",
        path.name,
        "image",
        json.dumps({"mime_type": mime, "file": path.name}),
        _compact(summary),
        path.stat().st_size,
    )


def extract_artifacts(path: Path, *, vision: bool = False) -> list[Artifact]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = extract_pages(path)
        artifacts: list[Artifact] = []
        for page, text in enumerate(pages, start=1):
            for chunk, value in enumerate(_chunks(text, 1200), start=1):
                artifacts.append(
                    Artifact(
                        "pdf_text",
                        path.name,
                        f"page:{page}:chunk:{chunk}",
                        value,
                        _compact(value),
                        path.stat().st_size,
                    )
                )
            if vision and os.getenv("GROQ_API_KEY"):
                with tempfile.TemporaryDirectory(prefix="pathcontext-page-") as temp_dir:
                    image_base = Path(temp_dir) / f"page-{page}"
                    try:
                        subprocess.run(
                            [
                                "pdftoppm",
                                "-f",
                                str(page),
                                "-l",
                                str(page),
                                "-png",
                                "-singlefile",
                                str(path),
                                str(image_base),
                            ],
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        image_path = image_base.with_suffix(".png")
                        summary = describe_image(image_path, os.environ["GROQ_API_KEY"])
                        artifacts.append(
                            Artifact(
                                "pdf_visual",
                                path.name,
                                f"page:{page}:visual",
                                json.dumps({"page": page}),
                                _compact(summary),
                                path.stat().st_size,
                            )
                        )
                    except (FileNotFoundError, subprocess.CalledProcessError, LLMError):
                        # Text extraction remains valid if optional visual analysis
                        # is unavailable for a page.
                        pass
        return artifacts
    if suffix in TABLE_EXTENSIONS:
        return _read_table(path)
    if suffix in TEXT_EXTENSIONS:
        return _read_text(path)
    if suffix in IMAGE_EXTENSIONS:
        summary = None
        if vision and os.getenv("GROQ_API_KEY"):
            try:
                summary = describe_image(path, os.environ["GROQ_API_KEY"])
            except LLMError:
                summary = None
        return [_image_artifact(path, summary)]
    raise ValueError(f"Unsupported file type: {path.suffix}")


def statements(path: Path, artifacts: list[Artifact]) -> list[str]:
    document_id = _id("multimodal-document", path.name)
    result = [
        f"MERGE (d:Document {{id: {document_id}}})",
        f"MATCH (d:Document {{id: {document_id}}}) SET "
        f"d.external_id = {_cypher(path.name)}, d.source_file = {_cypher(str(path))}, "
        f"d.modality = {_cypher(path.suffix.lower().lstrip('.'))}, "
        f"d.artifact_count = {len(artifacts)}",
    ]
    for artifact in artifacts:
        artifact_id = _id("multimodal-artifact", f"{path.name}:{artifact.locator}")
        result.extend(
            [
                f"MERGE (a:Artifact {{id: {artifact_id}}})",
                f"MATCH (a:Artifact {{id: {artifact_id}}}) SET "
                f"a.external_id = {_cypher(f'{path.name}:{artifact.locator}')}, "
                f"a.kind = {_cypher(artifact.kind)}, "
                f"a.locator = {_cypher(artifact.locator)}, "
                f"a.summary = {_cypher(artifact.summary)}, "
                f"a.content = {_cypher(artifact.text)}, "
                f"a.raw_bytes = {artifact.raw_bytes}",
                f"MERGE (d:Document {{id: {document_id}}})-[:HAS_ARTIFACT]->"
                f"(a:Artifact {{id: {artifact_id}}})",
            ]
        )
    return result


def graph_for_artifacts(
    path: Path, artifacts: list[Artifact]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    document_id = _id("multimodal-document", path.name)
    nodes: list[dict[str, Any]] = [{
        "id": document_id, "label": "Document", "external_id": path.name,
        "properties": {
            "source_file": str(path),
            "modality": path.suffix.lower().lstrip("."),
            "artifact_count": len(artifacts),
        },
    }]
    edges: list[dict[str, Any]] = []
    for artifact in artifacts:
        artifact_id = _id("multimodal-artifact", f"{path.name}:{artifact.locator}")
        nodes.append({
            "id": artifact_id,
            "label": "Artifact",
            "external_id": f"{path.name}:{artifact.locator}",
            "properties": {
                "kind": artifact.kind,
                "locator": artifact.locator,
                "summary": artifact.summary,
                "content": artifact.text,
                "raw_bytes": artifact.raw_bytes,
            },
        })
        edges.append({"src": document_id, "dst": artifact_id, "type": "HAS_ARTIFACT"})
    return nodes, edges


def _decode(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def retrieve(
    client: HydraDBClient,
    document_name: str,
    question: str,
    *,
    max_facts: int = 4,
    max_context_tokens: int = 1200,
) -> EvidencePacket:
    payload = client.query(
        "MATCH (d:Document {external_id: %s})-[:HAS_ARTIFACT]->(a:Artifact) "
        "RETURN d.external_id AS document, a.kind AS kind, "
        "a.locator AS locator, a.summary AS summary, a.content AS content"
        % _cypher(document_name)
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise HydraDBError("HydraDB returned no multimodal artifact rows")
    terms = {term.strip(".,?!:;").lower() for term in question.split() if len(term) > 2}
    candidates: list[Fact] = []
    for row in payload["rows"]:
        values = [_decode(item) for item in row]
        if len(values) < 5:
            continue
        document, kind, locator, summary, content = values[:5]
        haystack = f"{summary} {content}".lower()
        score = sum(term in haystack for term in terms)
        text = str(summary or content)
        candidates.append(
            Fact(
                text=text,
                source=f"hydradb:{kind}",
                path=(
                    f"Document:{document}",
                    f"Artifact:{kind}",
                    f"Locator:{locator}",
                ),
                confidence="retrieved" if score else "weak-match",
                score=float(score),
                token_cost=max(1, len(text.split())),
            )
        )
    ranked = [fact for fact in sorted(candidates, key=lambda item: item.score, reverse=True)
              if fact.score > 0]
    selected: list[Fact] = []
    used = 0
    for fact in ranked:
        if len(selected) >= max_facts or used + fact.token_cost > max_context_tokens:
            continue
        selected.append(fact)
        used += fact.token_cost
    supported = bool(selected and selected[0].score > 0)
    uncertainty = [] if supported else ["No strong multimodal artifact match was found."]
    context = "\n".join(
        f"- {fact.text} [citation: {' -> '.join(fact.path)}]" for fact in selected
    )
    return EvidencePacket(
        context=context,
        facts=selected,
        contradictions=[],
        uncertainty=uncertainty,
        answerability="supported" if supported else "insufficient",
        retrieval_stats={
            **client.telemetry(),
            "candidate_artifacts": len(candidates),
            "selected_artifacts": len(selected),
            "input_tokens": used,
            "token_budget": max_context_tokens,
        },
    )


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ingest and query multimodal files")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--question")
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--max-context-tokens", type=int, default=1200)
    args = parser.parse_args()
    try:
        source = args.file.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        FILES_DIR.mkdir(parents=True, exist_ok=True)
        target = FILES_DIR / source.name
        if source != target:
            shutil.copy2(source, target)
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
        output: dict[str, Any] = {
            "file": str(target),
            "artifacts": len(artifacts),
            "modality_counts": {
                kind: sum(item.kind == kind for item in artifacts)
                for kind in sorted({item.kind for item in artifacts})
            },
        }
        if args.question:
            packet = retrieve(
                client,
                target.name,
                args.question,
                max_context_tokens=args.max_context_tokens,
            )
            output["packet"] = packet.to_dict()
            key = os.getenv("GROQ_API_KEY")
            if packet.answerability == "supported" and key and not key.startswith("replace-"):
                output["answer"] = synthesize(
                    args.question,
                    packet,
                    groq_api_key=key,
                    groq_model=os.getenv("GROQ_MODEL"),
                ).__dict__
        print(json.dumps(output, indent=2, default=str))
        return 0
    except (HydraDBError, LLMError, OSError, RuntimeError, ValueError) as error:
        print(f"Multimodal pipeline failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
