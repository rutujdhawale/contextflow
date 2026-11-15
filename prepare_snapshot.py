"""Build a deterministic, HydraDB-compatible graph snapshot manifest.

This command is intentionally offline. It prepares the graph image that an
operator provisions into HydraDB before starting the read server; it never
claims to perform live writes through the application API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_snapshot(fixture: Path) -> dict[str, Any]:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    entities = payload["entities"]
    ids = {
        (entity["type"], entity["id"]): index
        for index, entity in enumerate(entities, start=1)
    }
    vertices = [
        {
            "id": ids[(entity["type"], entity["id"])],
            "label": entity["type"],
            "external_id": entity["id"],
            "properties": entity.get("properties", {}),
        }
        for entity in entities
    ]
    edges = [
        {
            "source": ids[(edge["source_type"], edge["source_id"])],
            "target": ids[(edge["target_type"], edge["target_id"])],
            "type": edge["type"],
        }
        for edge in payload["relationships"]
    ]
    return {
        "format": "pathcontext-hydradb-snapshot-v1",
        "source_fixture": str(fixture),
        "identity": "stable integer id; external_id preserves source identity",
        "vertices": vertices,
        "edges": edges,
        "counts": {"vertices": len(vertices), "edges": len(edges)},
    }


def build_file_snapshot(file_path: Path) -> dict[str, Any]:
    file_path = file_path.expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        from pdf_pipeline import extract_pages, pdf_graph

        pages = extract_pages(file_path)
        nodes, edges_raw = pdf_graph(file_path, pages)
    else:
        from multimodal_pipeline import extract_artifacts, graph_for_artifacts

        artifacts = extract_artifacts(file_path)
        nodes, edges_raw = graph_for_artifacts(file_path, artifacts)

    vertices = [
        {
            "id": node["id"],
            "label": node["label"],
            "external_id": node["external_id"],
            "properties": node.get("properties", {}),
        }
        for node in nodes
    ]
    edges = [
        {
            "source": edge["src"],
            "target": edge["dst"],
            "type": edge["type"],
        }
        for edge in edges_raw
    ]
    return {
        "format": "pathcontext-hydradb-snapshot-v1",
        "source_file": str(file_path),
        "filename": file_path.name,
        "modality": suffix.lstrip("."),
        "identity": "stable integer id; external_id preserves source identity",
        "vertices": vertices,
        "edges": edges,
        "counts": {"vertices": len(vertices), "edges": len(edges)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an offline HydraDB graph snapshot")
    root = Path(__file__).parent
    parser.add_argument("--fixture", type=Path, help="JSON fixture to snapshot (e.g. fixtures/incidents.json)")
    parser.add_argument("--file", type=Path, help="Document file from data/files to snapshot (e.g. data/files/ArtOfWar.pdf)")
    parser.add_argument("--all-files", action="store_true", help="Snapshot all files found in data/files")
    parser.add_argument(
        "--output",
        type=Path,
        help="Custom output file path for single snapshot",
    )
    args = parser.parse_args()

    snapshots_dir = root / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    if args.all_files:
        files_dir = root / "data" / "files"
        candidates = [f for f in files_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
        results = []
        for cand in candidates:
            try:
                snap = build_file_snapshot(cand)
                out_path = snapshots_dir / f"{cand.stem}.snapshot.json"
                out_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
                results.append({"file": cand.name, "status": "prepared", "output": str(out_path), **snap["counts"]})
            except Exception as exc:
                results.append({"file": cand.name, "status": "error", "error": str(exc)})
        print(json.dumps(results, indent=2))
        return 0

    if args.file:
        snapshot = build_file_snapshot(args.file)
        out_path = args.output or (snapshots_dir / f"{args.file.stem}.snapshot.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "prepared", "output": str(out_path), **snapshot["counts"]}, indent=2))
        return 0

    fixture_path = args.fixture or (root / "fixtures" / "incidents.json")
    snapshot = build_snapshot(fixture_path)
    out_path = args.output or (snapshots_dir / "incidents.snapshot.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "prepared", "output": str(out_path), **snapshot["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
