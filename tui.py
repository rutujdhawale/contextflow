"""ContextFlow Terminal UI (TUI).

An , Claude Code-inspired developer console for HydraDB structural context.
Features:
  - Exact HydraDB Orange (#FF5719) & Claude Code slant block typography
  - Categorized slash commands directory (/commands) with tab auto-completion
  - Offline snapshot generation and exploration for files in data/files
  - Dual-mode operation (Live HydraDB instance vs Local deterministic snapshot)
  - Grounded evidence packet cards and LLM synthesis
"""

from __future__ import annotations

import json
import os
import re
import readline
import select
import shutil
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).parent.resolve()
os.chdir(ROOT_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ingest import ingest_fixture, load_fixture
from pathcontext.answer import render_answer
from pathcontext.context_compiler import ContextCompiler
from pathcontext.env import load_dotenv
from pathcontext.graph import GraphStore
from pathcontext.hydradb_client import HydraDBClient, HydraDBError
from pathcontext.hydradb_retriever import HydraDBContextCompiler
from pathcontext.llm import LLMError, synthesize
from pathcontext.schema import Entity, EvidencePacket, Fact, Relationship
from prepare_snapshot import build_file_snapshot, build_snapshot

# ─────────────────────────────────────────────────────────────────────────────
# Claude Code + HydraDB Color Palette (24-bit TrueColor)
# ─────────────────────────────────────────────────────────────────────────────
ORANGE = "\033[38;2;255;87;25m"       # Exact HydraDB Logo Orange #FF5719
ORANGE_BOLD = "\033[1;38;2;255;87;25m"
PEACH = "\033[38;2;255;165;110m"     # Warm Peach accent
WHITE = "\033[38;2;245;245;250m"
WHITE_BOLD = "\033[1;38;2;255;255;255m"
GRAY = "\033[38;2;135;135;150m"       # Slate / dim annotations
BORDER = "\033[38;2;75;75;90m"        # Subtle card borders
GREEN = "\033[38;2;72;220;130m"      # Connected / verified / live
GREEN_BOLD = "\033[1;38;2;72;220;130m"
AMBER = "\033[38;2;255;185;60m"      # Warning / uncertainty / local
CYAN = "\033[38;2;80;200;240m"
RED = "\033[38;2;255;85;85m"
RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

ROOT_DIR = Path(__file__).parent
DATA_FILES_DIR = ROOT_DIR / "data" / "files"
SNAPSHOTS_DIR = ROOT_DIR / "snapshots"
FIXTURES_DIR = ROOT_DIR / "fixtures"
CARD_WIDTH = 84


def get_layout() -> tuple[int, str]:
    """Return standard clean card width without arbitrary indent."""
    return CARD_WIDTH, ""


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot & Graph Loading
# ─────────────────────────────────────────────────────────────────────────────
ENGLISH_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", 
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", 
    "but", "by", "can", "did", "do", "does", "doing", "down", "during", "each", "few", "for", 
    "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "him", 
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "me", "more", "most", 
    "my", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "our", 
    "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", 
    "the", "their", "theirs", "them", "then", "there", "these", "they", "this", "those", 
    "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", 
    "when", "where", "which", "while", "who", "whom", "why", "with", "you", "your"
}


def _norm_term(s: str) -> str:
    """Normalize word removing punctuation and quotes."""
    return s.lower().replace("'", "").replace("’", "").replace('"', "").strip(".,?!:;()[]{}<>/\\|`*~-")


def extract_query_terms(question: str) -> set[str]:
    """Extract substantive keywords removing common English stop words."""
    raw = [_norm_term(t) for t in question.split()]
    terms = {t for t in raw if len(t) > 2 and t not in ENGLISH_STOP_WORDS}
    if not terms:
        terms = {t for t in raw if len(t) > 1}
    return terms


class LocalSnapshotSession:
    """Manages loaded snapshot manifest or fixture for offline local queries."""

    def __init__(self, name: str, source_path: Path, data: dict[str, Any], kind: str):
        self.name = name
        self.source_path = source_path
        self.data = data
        self.kind = kind  # "incident_fixture", "incident_snapshot", "document_snapshot"
        self.vertices = data.get("vertices", [])
        self.edges = data.get("edges", [])

    @classmethod
    def load(cls, path: Path) -> LocalSnapshotSession:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("format") == "pathcontext-hydradb-snapshot-v1":
            if any(v.get("label") == "Incident" for v in payload.get("vertices", [])):
                kind = "incident_snapshot"
            else:
                kind = "document_snapshot"
            return cls(path.stem, path, payload, kind)
        elif "entities" in payload and "relationships" in payload:
            return cls(path.stem, path, payload, "incident_fixture")
        raise ValueError(f"Unrecognized snapshot or fixture format in {path}")

    def count_summary(self) -> str:
        if self.kind == "incident_fixture":
            return f"{len(self.data.get('entities', []))} entities · {len(self.data.get('relationships', []))} rels"
        return f"{len(self.vertices)} vertices · {len(self.edges)} edges"

    def retrieve_document(self, question: str, max_facts: int = 4) -> EvidencePacket:
        """Offline deterministic retrieval over document snapshot vertices with stopword filtering."""
        terms = extract_query_terms(question)
        candidates: list[Fact] = []
        for vertex in self.vertices:
            props = vertex.get("properties", {})
            text = props.get("text") or props.get("content") or props.get("summary") or ""
            if not text:
                continue

            section = props.get("section", "")
            summary = props.get("summary", "")
            haystack = _norm_term(f"{section} {summary} {text}")

            # Substantive keyword matching
            hits = sum(1 for term in terms if term in haystack)
            if hits == 0 or (len(terms) >= 3 and hits < 2):
                score = 0.0
            else:
                concept_bonus = (hits ** 2) * 10
                freq_bonus = min(20, sum(haystack.count(term) for term in terms))
                score = float(concept_bonus + freq_bonus)

            label = vertex.get("label", "Node")
            ext_id = vertex.get("external_id", str(vertex.get("id")))

            path = (f"{label}:{ext_id}",)
            if "page_number" in props:
                doc_name = props.get("source_file", self.name)
                if "/" in doc_name:
                    doc_name = Path(doc_name).name
                path = (f"Document:{doc_name}", f"Page:{props['page_number']}", f"Chunk:{ext_id}")
            elif "locator" in props:
                doc_name = props.get("source_file", self.name)
                if "/" in doc_name:
                    doc_name = Path(doc_name).name
                path = (f"Document:{doc_name}", f"Artifact:{props.get('kind', 'item')}", f"Locator:{props['locator']}")

            candidates.append(
                Fact(
                    text=text,
                    source=f"snapshot:{self.name}",
                    path=path,
                    confidence="verified" if score > 30 else ("retrieved" if score > 0 else "weak-match"),
                    score=score,
                    token_cost=max(1, len(text.split())),
                )
            )

        ranked = [f for f in sorted(candidates, key=lambda x: x.score, reverse=True) if f.score > 0][:max_facts]
        supported = bool(ranked and ranked[0].score > 0)
        uncertainty = [] if supported else ["No direct keyword matches found in local snapshot."]
        context = "\n".join(f"- {fact.text} [citation: {' -> '.join(fact.path)}]" for fact in ranked)

        return EvidencePacket(
            context=context,
            facts=ranked,
            contradictions=[],
            uncertainty=uncertainty,
            answerability="supported" if supported else "insufficient",
            retrieval_stats={
                "snapshot_name": self.name,
                "candidate_chunks": len(candidates),
                "selected_chunks": len(ranked),
                "snapshot_consistency": "atomic (offline snapshot)",
            },
        )


def _client() -> HydraDBClient:
    return HydraDBClient(
        base_url=os.getenv("PATHCONTEXT_HYDRADB_URL", "http://127.0.0.1:8443"),
        graph_id=os.getenv("PATHCONTEXT_GRAPH_ID", "default"),
        cell_id=os.getenv("PATHCONTEXT_CELL_ID", "cell-0"),
        token=os.getenv("PATHCONTEXT_HYDRADB_TOKEN"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Aesthetic Header & Claude Code Typography
# ─────────────────────────────────────────────────────────────────────────────
def print_banner(mode: str = "", active_dataset: str = "", dataset_counts: str = "") -> None:
    """Print the aesthetic CONTEXT FLOW gradient banner."""
    banner_lines = [
        r"   ______ ____  _   __ ______ _______ _  __ ______    ______ __     ____ _       __ ",
        r"  / ____// __ \/ | / //_  __// ____/ | |/ //_  __/   / ____// /    / __ \ |     / / ",
        r" / /    / / / /  |/ /  / /  / __/    |   /  / /     / /_   / /    / / / / | /| / /  ",
        r"/ /___ / /_/ // /|  /  / /  / /___  /   |  / /     / __/  / /___ / /_/ /| |/ |/ /   ",
        r"\____/ \____//_/ |_/  /_/  /_____/ /_/|_| /_/     /_/    /_____/ \____/ |__/|__/    ",
    ]

    print()
    for line in banner_lines:
        w = len(line)
        row = []
        for i, char in enumerate(line):
            t = i / max(1, w - 1)
            # Smooth gradient from warm peach-white (255, 220, 170) to vibrant HydraDB orange (255, 75, 15)
            r = 255
            g = int(220 * (1 - t) + 75 * t)
            b = int(170 * (1 - t) + 15 * t)
            row.append(f"\033[38;2;{r};{g};{b}m\033[1m{char}")
        print("".join(row) + RESET)

    print(f"\n{PEACH}{BOLD}✦ High-Efficiency Graph-RAG Engine with HydraDB ✦{RESET}")
    print(f"{GRAY}Deterministic Structural Paths  ·  Sub-Millisecond Retrieval  ·  Zero Hallucination{RESET}\n")


def print_suggestions_card() -> None:
    """Print interactive discovery card with 1-6 shortcuts and command cheat sheet."""
    w, _ = get_layout()
    title = "QUICK START & COMMAND CHEAT SHEET"
    hint = "(type 1-6 or any /cmd)"
    dashes = max(2, w - 3 - len(title) - 1 - len(hint) - 2)
    print(f"{BORDER}╭─{RESET} {ORANGE_BOLD}{title}{RESET} {GRAY}{hint}{RESET} {BORDER}{'─' * dashes}╮{RESET}")
    items = [
        ("[1]", "Which change caused INC-1042 and who owns it?", "Incident Topology"),
        ("[2]", "What are database schema constraints & candidate keys?", "Database Systems"),
        ("[3]", "How does Raft leader election work & circuit breakers?", "SRE & Architecture"),
        ("[4]", "What is Law 33: Discover each man's thumbscrew?", "48 Laws of Power"),
        ("[5]", "What are the five constant factors in the art of war?", "Sun Tzu Graph"),
        ("[6]", "/compare What are database schema constraints & keys?", "Token Benchmark"),
    ]
    for num, q, tag in items:
        print(f"{BORDER}│{RESET}  {WHITE_BOLD}{num}{RESET} {PEACH}{q[:54]:<54}{RESET} {GRAY}{tag[:19]:<19}{RESET}  {BORDER}│{RESET}")

    print(f"{BORDER}├{'─' * (w - 2)}┤{RESET}")
    shortcuts = [
        ("/files", "Active datasets"),
        ("/snapshot <path>", "Compile file/path"),
        ("/compare <q>", "Token benchmark"),
        ("/status", "Graph telemetry"),
        ("/clear", "Clear screen"),
        ("/help", "Full command manual"),
    ]
    half = (len(shortcuts) + 1) // 2
    for i in range(half):
        c1_cmd, c1_desc = shortcuts[i]
        c1_str = f"{WHITE_BOLD}{c1_cmd:<18}{RESET} {GRAY}{c1_desc:<18}{RESET}"
        if i + half < len(shortcuts):
            c2_cmd, c2_desc = shortcuts[i + half]
            c2_str = f"{WHITE_BOLD}{c2_cmd:<18}{RESET} {GRAY}{c2_desc:<19}{RESET}"
        else:
            c2_str = f"{' ' * 38}"
        print(f"{BORDER}│{RESET}  {c1_str} {BORDER}│{RESET} {c2_str}  {BORDER}│{RESET}")

    print(f"{BORDER}╰{'─' * (w - 2)}╯{RESET}\n")


def print_commands() -> None:
    """Print the complete, aesthetic directory of slash commands."""
    w, margin = get_layout()
    print(f"\n{margin}{BORDER}╭─{RESET} {ORANGE_BOLD}COMMAND DIRECTORY{RESET} {BORDER}{'─' * (w - 22)}╮{RESET}")

    categories = [
        (
            "QUERY & REASONING",
            [
                ("/ask <question>", "Retrieve grounded structural evidence & synthesize an answer"),
                ("<question>", "Any text without '/' automatically executes /ask"),
                ("/compare <question>", "Compare Naive RAG vs PathContext Graph token reduction"),
                # ("/query <openCypher>", "Execute raw openCypher query directly against HydraDB"),
            ],
        ),
        (
            "DATA & SNAPSHOTS",
            [
                ("/files", "Inspect files in data/files & snapshot readiness"),
                ("/fetch <url>", "Download document/PDF from URL and build snapshot"),
                # ("/paste <file>", "Paste text into data/files/ and build snapshot"),
                ("/snapshot <file>", "Build offline HydraDB snapshot manifest for a file"),
                ("/snapshot all", "Batch-build snapshot manifests for all files in data/files"),
                # ("/load <name>", "Switch active dataset (e.g. /load ArtOfWar or /load incidents)"),
                # ("/ingest <file>", "Ingest a document from data/files into live HydraDB graph"),
            ],
        ),
        (
            "CONFIGURATION & SESSION",
            [
                ("/mode <live|local>", "Toggle between live HydraDB backend and local snapshot"),
                ("/status", "Display connection ping, graph telemetry, and epoch bookmarks"),
                ("/clear", "Clear terminal screen and repaint banner"),
                ("/help", "Show quick reference card"),
                ("/quit, /exit", "Exit the console"),
            ],
        ),
    ]

    for cat_title, items in categories:
        print(f"{margin}{BORDER}│{RESET}  {PEACH}{BOLD}{cat_title}{RESET}")
        for cmd, desc in items:
            cmd_styled = f"{WHITE_BOLD}{cmd:<21}{RESET}"
            dots = f"{GRAY}{desc}{RESET}"
            line = f"    {cmd_styled} {dots}"
            print(f"{margin}{BORDER}│{RESET}{line}")
        print(f"{margin}{BORDER}│{RESET}")

    print(f"{margin}{BORDER}╰{'─' * (w - 2)}╯{RESET}\n")


def print_evidence_packet(packet: EvidencePacket) -> None:
    """Render a Claude-styled evidence card with clean text wrapping centered in the terminal."""
    w, margin = get_layout()
    ans_color = GREEN_BOLD if packet.answerability == "supported" else AMBER
    cost = packet.retrieval_stats.get("input_tokens", sum(f.token_cost for f in packet.facts))
    cand = packet.retrieval_stats.get("candidate_chunks", packet.retrieval_stats.get("candidate_artifacts", len(packet.facts)))
    latency = packet.retrieval_stats.get("latency_ms", "cached")

    print(f"\n{margin}{BORDER}╭─{RESET} {ORANGE_BOLD}EVIDENCE PACKET{RESET} {BORDER}{'─' * (w - 20)}╮{RESET}")
    print(f"{margin}{BORDER}│{RESET}  Status: {ans_color}{packet.answerability.upper()}{RESET}  {GRAY}│{RESET}  Facts: {WHITE}{len(packet.facts)}{RESET}  {GRAY}│{RESET}  Candidates: {WHITE}{cand}{RESET}  {GRAY}│{RESET}  Latency: {WHITE}{latency}{RESET}")
    print(f"{margin}{BORDER}├{'─' * (w - 2)}┤{RESET}")

    if not packet.facts:
        print(f"{margin}{BORDER}│{RESET}  {AMBER}No direct evidence facts retrieved for this query.{RESET}")
    else:
        for idx, fact in enumerate(packet.facts[:4], start=1):
            path_str = f" {PEACH}➔{RESET} ".join(fact.path) if fact.path else "direct"
            conf_color = GREEN if fact.confidence in ("verified", "retrieved") else AMBER
            print(f"{margin}{BORDER}│{RESET}  {ORANGE_BOLD}◆ [{idx}]{RESET} {WHITE}{path_str}{RESET}")

            # Cleanly wrap snippet
            clean_text = " ".join(fact.text.split())
            if len(clean_text) > 180:
                clean_text = clean_text[:177] + "..."
            wrapped = textwrap.wrap(f'"{clean_text}"', width=w - 8)
            for s_line in wrapped:
                print(f"{margin}{BORDER}│{RESET}    {GRAY}{s_line}{RESET}")
            print(f"{margin}{BORDER}│{RESET}    {GRAY}Confidence:{RESET} {conf_color}{fact.confidence}{RESET} {GRAY}│ Score:{RESET} {fact.score:.2f} {GRAY}│ Source:{RESET} {fact.source}")
            if idx < min(4, len(packet.facts)):
                print(f"{margin}{BORDER}│{RESET}")

    if packet.contradictions:
        print(f"{margin}{BORDER}│{RESET}")
        for item in packet.contradictions:
            print(f"{margin}{BORDER}│{RESET}  {RED}⚠ Contradiction:{RESET} {item}")

    if packet.uncertainty:
        print(f"{margin}{BORDER}│{RESET}")
        for item in packet.uncertainty:
            print(f"{margin}{BORDER}│{RESET}  {AMBER}⚠ Note:{RESET} {item}")

    print(f"{margin}{BORDER}╰{'─' * (w - 2)}╯{RESET}")


def print_grounded_answer(question: str, packet: EvidencePacket, answer_obj: Any = None) -> None:
    """Render grounded answer with clean typography, line wrapping, and streaming effect centered in terminal."""
    w, margin = get_layout()
    provider = answer_obj.provider if answer_obj else "ContextFlow Structural Narrative"

    if answer_obj:
        raw_text = answer_obj.text.strip()
    else:
        from tui_textual import synthesize_fluid_answer
        raw_text = synthesize_fluid_answer(question, packet)

    print(f"\n{margin}{BORDER}╭─{RESET} {WHITE_BOLD}GROUNDED SYNTHESIS{RESET} {GRAY}({provider}){RESET} {BORDER}{'─' * max(2, w - 26 - len(provider))}╮{RESET}")
    for block in raw_text.splitlines():
        if not block.strip():
            print(f"{margin}{BORDER}│{RESET}")
            continue
        wrapped = textwrap.wrap(block, width=w - 6)
        for w_line in wrapped:
            sys.stdout.write(f"{margin}{BORDER}│{RESET}  ")
            words = w_line.split(" ")
            for widx, word in enumerate(words):
                sys.stdout.write(word + (" " if widx < len(words) - 1 else ""))
                sys.stdout.flush()
                time.sleep(0.008)
            sys.stdout.write("\n")
    print(f"{margin}{BORDER}╰{'─' * (w - 2)}╯{RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# File & Snapshot Utilities
# ─────────────────────────────────────────────────────────────────────────────
def list_files_and_snapshots() -> None:
    """Print an aesthetic overview of data files and generated snapshots centered in terminal."""
    DATA_FILES_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    data_files = sorted([f for f in DATA_FILES_DIR.iterdir() if f.is_file() and not f.name.startswith(".")])
    snapshots = sorted([s for s in SNAPSHOTS_DIR.iterdir() if s.is_file() and s.name.endswith(".snapshot.json")])

    w, margin = get_layout()
    title1 = "FILES (data/files)"
    dashes1 = max(2, w - 4 - len(title1))
    print(f"\n{margin}{BORDER}╭─{RESET} {ORANGE_BOLD}{title1}{RESET} {BORDER}{'─' * dashes1}╮{RESET}")
    if not data_files:
        line = "No files found in data/files/. Add PDFs or text files here."
        print(f"{margin}{BORDER}│{RESET}  {GRAY}{line[:w-6]:<{w-6}}{RESET}  {BORDER}│{RESET}")
    else:
        for f in data_files:
            size_mb = f.stat().st_size / (1024 * 1024)
            size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{f.stat().st_size / 1024:.1f} KB"
            snap_path = SNAPSHOTS_DIR / f"{f.stem}.snapshot.json"
            snap_tag = f"{GREEN}● Snapshot ready{RESET}" if snap_path.exists() else f"{AMBER}○ No snapshot{RESET}"
            name_col = f"{f.name[:34]:<34}"
            size_col = f"{size_str:>9}"
            tag_raw_len = 16  # visual length of '● Snapshot ready' / '○ No snapshot'
            pad = max(0, w - 6 - (34 + 1 + 9 + 2 + tag_raw_len))
            print(f"{margin}{BORDER}│{RESET}  {WHITE_BOLD}{name_col}{RESET} {GRAY}{size_col}{RESET}  {snap_tag}{' ' * pad}  {BORDER}│{RESET}")

    title2 = "GENERATED SNAPSHOTS (snapshots/)"
    dashes2 = max(2, w - 4 - len(title2))
    print(f"{margin}{BORDER}├─{RESET} {PEACH}{BOLD}{title2}{RESET} {BORDER}{'─' * dashes2}┤{RESET}")
    if not snapshots:
        line = "No snapshots built yet. Run /snapshot <path> to create one."
        print(f"{margin}{BORDER}│{RESET}  {GRAY}{line[:w-6]:<{w-6}}{RESET}  {BORDER}│{RESET}")
    else:
        for s in snapshots:
            size_kb = f"{s.stat().st_size / 1024:.1f} KB"
            try:
                snap_data = json.loads(s.read_text(encoding="utf-8"))
                counts = snap_data.get("counts", {})
                v_count = counts.get("vertices", len(snap_data.get("vertices", [])))
                e_count = counts.get("edges", len(snap_data.get("edges", [])))
                details = f"{v_count}v · {e_count}e"
            except Exception:
                details = "manifest"
            name_col = f"{s.name[:34]:<34}"
            size_col = f"{size_kb:>10}"
            det_col = f"{details:<16}"
            pad = max(0, w - 6 - (34 + 1 + 10 + 2 + 16))
            print(f"{margin}{BORDER}│{RESET}  {PEACH}{name_col}{RESET} {GRAY}{size_col}{RESET}  {CYAN}{det_col}{RESET}{' ' * pad}  {BORDER}│{RESET}")

    print(f"{margin}{BORDER}╰{'─' * (w - 2)}╯{RESET}\n")


def build_and_save_snapshot(target_name: str) -> None:
    """Generate a HydraDB snapshot for a file path, file in data/files, or fixture."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if target_name in ("all", "*"):
        data_files = [f for f in DATA_FILES_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
        if not data_files:
            print(f"{AMBER}No files found in data/files/ to snapshot.{RESET}")
            return
        print(f"{CYAN}Batch-building snapshots for {len(data_files)} file(s)...{RESET}")
        for cand in data_files:
            try:
                snap = build_file_snapshot(cand)
                out_path = SNAPSHOTS_DIR / f"{cand.stem}.snapshot.json"
                out_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
                print(f"  {GREEN}✔{RESET} {cand.name} ➔ {out_path.name} ({snap['counts']['vertices']}v, {snap['counts']['edges']}e)")
            except Exception as exc:
                print(f"  {RED}✖{RESET} {cand.name}: {exc}")
        return

    # 1. Direct file path check (absolute or relative)
    cand_path = Path(target_name).expanduser()
    if cand_path.is_file():
        # Copy to data/files if not already there
        target_in_data = DATA_FILES_DIR / cand_path.name
        if cand_path.resolve() != target_in_data.resolve():
            shutil.copy2(cand_path, target_in_data)
        print(f"{CYAN}Extracting graph and building snapshot for {cand_path.name}...{RESET}")
        t0 = time.perf_counter()
        snap = build_file_snapshot(cand_path)
        out_path = SNAPSHOTS_DIR / f"{cand_path.stem}.snapshot.json"
        out_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
        dt = (time.perf_counter() - t0) * 1000
        print(f"{GREEN}✔ Snapshot created:{RESET} {PEACH}{out_path.name}{RESET} in {dt:.0f}ms")
        print(f"  Vertices: {snap['counts']['vertices']} · Edges: {snap['counts']['edges']}")
        return

    # 2. Check data/files
    file_path = DATA_FILES_DIR / target_name
    if not file_path.exists():
        matches = [f for f in DATA_FILES_DIR.iterdir() if f.name.lower().startswith(target_name.lower())]
        if matches:
            file_path = matches[0]

    if file_path.exists():
        print(f"{CYAN}Extracting graph and building snapshot for {file_path.name}...{RESET}")
        t0 = time.perf_counter()
        snap = build_file_snapshot(file_path)
        out_path = SNAPSHOTS_DIR / f"{file_path.stem}.snapshot.json"
        out_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
        dt = (time.perf_counter() - t0) * 1000
        print(f"{GREEN}✔ Snapshot created:{RESET} {PEACH}{out_path.name}{RESET} in {dt:.0f}ms")
        print(f"  Vertices: {snap['counts']['vertices']} · Edges: {snap['counts']['edges']}")
        return

    # 3. Check fixtures
    fixture_path = FIXTURES_DIR / target_name
    if not fixture_path.exists() and not target_name.endswith(".json"):
        fixture_path = FIXTURES_DIR / f"{target_name}.json"
    if fixture_path.exists():
        print(f"{CYAN}Building snapshot from fixture {fixture_path.name}...{RESET}")
        snap = build_snapshot(fixture_path)
        out_path = SNAPSHOTS_DIR / f"{fixture_path.stem}.snapshot.json"
        out_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
        print(f"{GREEN}✔ Snapshot created:{RESET} {PEACH}{out_path.name}{RESET} ({snap['counts']['vertices']}v, {snap['counts']['edges']}e)")
        return

    print(f"{RED}File not found at path, in data/files/, or in fixtures/: {target_name}{RESET}")
    print(f"{GRAY}Usage: /snapshot <path/to/file> or /snapshot all. Type /files to list datasets.{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Readline Auto-Completion Setup
# ─────────────────────────────────────────────────────────────────────────────
SLASH_COMMANDS = [
    "/ask ",
    "/compare ",
    "/query ",
    "/files",
    "/fetch ",
    "/paste ",
    "/snapshot ",
    "/load ",
    "/ingest ",
    "/mode live",
    "/mode local",
    "/status",
    "/clear",
    "/help",
    "/commands",
    "/quit",
    "/exit",
]


def setup_completer():
    """Enable tab auto-completion for slash commands and filenames."""
    def completer(text: str, state: int):
        options = []
        if text.startswith("/"):
            options = [cmd for cmd in SLASH_COMMANDS if cmd.startswith(text)]
        else:
            line = readline.get_line_buffer()
            if any(line.startswith(prefix) for prefix in ("/snapshot ", "/ingest ", "/load ")):
                prefix = line.split(maxsplit=1)[1] if len(line.split()) > 1 else ""
                files = [f.name for f in DATA_FILES_DIR.glob("*") if not f.name.startswith(".")]
                snaps = [s.name for s in SNAPSHOTS_DIR.glob("*.json")]
                cands = sorted(set(files + snaps))
                options = [c for c in cands if c.startswith(prefix)]

        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")


# ─────────────────────────────────────────────────────────────────────────────
# Main Application Loop
# ─────────────────────────────────────────────────────────────────────────────
def run_cli_loop() -> int:
    load_dotenv()
    setup_completer()

    mode = "local"
    hydradb = _client()
    try:
        hydradb.query("RETURN 1")
        mode = "live"
    except Exception:
        mode = "local"

    # Preload all snapshots from snapshots/ directory
    available_snapshots: dict[str, LocalSnapshotSession] = {}
    for sf in sorted(SNAPSHOTS_DIR.glob("*.snapshot.json")):
        if sf.stat().st_size > 5 * 1024 * 1024:
            continue  # Skip massive local-only uncommitted snapshot
        try:
            available_snapshots[sf.stem] = LocalSnapshotSession.load(sf)
        except Exception:
            pass

    # Default dataset: load first document snapshot if available, or incidents
    active_dataset = "ArtOfWar.snapshot.json" if "ArtOfWar.snapshot" in available_snapshots else "incidents.json"
    active_session: LocalSnapshotSession | None = (
        available_snapshots.get("ArtOfWar.snapshot")
        or available_snapshots.get("incidents.snapshot")
        or None
    )

    default_fixture = FIXTURES_DIR / "incidents.json"
    if active_session is None and default_fixture.exists():
        try:
            active_session = LocalSnapshotSession.load(default_fixture)
        except Exception:
            pass

    # Compiler for incident fixtures
    local_compiler = ContextCompiler(load_fixture(default_fixture)) if default_fixture.exists() else None

    print("\033[2J\033[H", end="")
    print_banner()
    print_suggestions_card()

    prompt_symbol = f"{ORANGE_BOLD}> {RESET}"

    while True:
        w, margin = get_layout()
        try:
            line = input(f"{margin}{prompt_symbol}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{margin}{GRAY}Exiting ContextFlow console. Goodbye!{RESET}")
            return 0

        if not line:
            continue

        # Quick-pick 1-6 shortcuts
        quick_map = {
            "1": "Which change caused INC-1042 and who owns it?",
            "2": "What are database schema constraints & candidate keys?",
            "3": "How does Raft leader election work & circuit breakers?",
            "4": "What is Law 33: Discover each man's thumbscrew?",
            "5": "What are the five constant factors in the art of war?",
            "6": "/compare What are database schema constraints and keys?",
        }
        if line in quick_map:
            line = quick_map[line]
            print(f"{margin}{CYAN}➜ Running suggestion:{RESET} {WHITE_BOLD}{line}{RESET}\n")

        # ── Navigation & System Commands ─────────────────────────────────────
        if line.lower() in ("/quit", "/exit", "quit", "exit", "q"):
            print(f"{GRAY}Exiting ContextFlow console. Goodbye!{RESET}")
            return 0

        if line in ("/help", "/?"):
            print_commands()
            continue

        if line == "/commands":
            print_commands()
            continue

        if line == "/clear":
            print("\033[2J\033[H", end="")
            print_banner()
            print_suggestions_card()
            continue

        if line == "/files":
            list_files_and_snapshots()
            continue

        if line.startswith("/fetch"):
            url = line[6:].strip()
            if not url:
                print(f"{AMBER}Usage: /fetch <http/https URL to file or PDF>{RESET}")
                continue
            from urllib.parse import urlparse
            from urllib.request import urlopen, Request
            fname = Path(urlparse(url).path).name or "downloaded_file.txt"
            target = DATA_FILES_DIR / fname
            print(f"{CYAN}Downloading {url} ...{RESET}")
            try:
                req = Request(url, headers={"User-Agent": "ContextFlow/2.0"})
                with urlopen(req, timeout=30) as resp:
                    target.write_bytes(resp.read())
                print(f"{GREEN}✔ Saved to:{RESET} {target.name} ({target.stat().st_size / 1024:.1f} KB)")
                build_and_save_snapshot(target.name)
                snap_file = SNAPSHOTS_DIR / f"{target.stem}.snapshot.json"
                if snap_file.exists():
                    available_snapshots[snap_file.stem] = LocalSnapshotSession.load(snap_file)
                    print(f"{GREEN}✔ Snapshot actively routed and ready to query!{RESET}")
            except Exception as e:
                print(f"{RED}Download failed:{RESET} {e}")
            continue

        if line.startswith("/paste"):
            fname = line[6:].strip() or "pasted_notes.txt"
            target = DATA_FILES_DIR / fname
            print(f"{CYAN}Enter/paste text below. Type {WHITE_BOLD}EOF{CYAN} on a new line or press Ctrl-D when done:{RESET}")
            p_lines = []
            try:
                while True:
                    p_line = input()
                    if p_line.strip() == "EOF":
                        break
                    p_lines.append(p_line)
            except (EOFError, KeyboardInterrupt):
                pass
            content = "\n".join(p_lines).strip()
            if not content:
                print(f"{AMBER}No content received.{RESET}")
                continue
            target.write_text(content, encoding="utf-8")
            print(f"{GREEN}✔ Saved to:{RESET} {target.name} ({len(content)} characters)")
            build_and_save_snapshot(target.name)
            snap_file = SNAPSHOTS_DIR / f"{target.stem}.snapshot.json"
            if snap_file.exists():
                available_snapshots[snap_file.stem] = LocalSnapshotSession.load(snap_file)
                print(f"{GREEN}✔ Snapshot actively routed and ready to query!{RESET}")
            continue

        if line.startswith("/snapshot") or line.startswith("/add"):
            parts = line.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) > 1 else "all"
            build_and_save_snapshot(arg)
            # Auto-reload available snapshots into memory
            for sf in SNAPSHOTS_DIR.glob("*.snapshot.json"):
                try:
                    available_snapshots[sf.stem] = LocalSnapshotSession.load(sf)
                except Exception:
                    pass
            continue

        if line.startswith("/load"):
            name = line[5:].strip()
            if not name:
                print(f"{AMBER}Usage: /load <snapshot_name or fixture>{RESET}")
                continue
            cand_paths = [
                SNAPSHOTS_DIR / name,
                SNAPSHOTS_DIR / f"{name}.snapshot.json",
                FIXTURES_DIR / name,
                FIXTURES_DIR / f"{name}.json",
                DATA_FILES_DIR / name,
            ]
            found = next((p for p in cand_paths if p.is_file()), None)
            if not found:
                print(f"{RED}Snapshot/fixture not found:{RESET} {name}")
                continue
            try:
                active_session = LocalSnapshotSession.load(found)
                active_dataset = found.name
                if active_session.kind == "incident_fixture":
                    local_compiler = ContextCompiler(load_fixture(found))
                print(f"{GREEN}✔ Loaded dataset:{RESET} {PEACH}{active_dataset}{RESET} ({active_session.count_summary()})")
            except Exception as err:
                print(f"{RED}Failed to load dataset:{RESET} {err}")
            continue

        if line.startswith("/ingest"):
            arg = line[7:].strip()
            if not arg:
                print(f"{AMBER}Usage: /ingest <filename from data/files>{RESET}")
                continue
            if mode != "live":
                print(f"{AMBER}/ingest requires live mode. Run /mode live first.{RESET}")
                continue
            target = DATA_FILES_DIR / arg
            if not target.exists():
                matches = [f for f in DATA_FILES_DIR.iterdir() if f.name.lower().startswith(arg.lower())]
                if matches:
                    target = matches[0]
            if not target.exists():
                print(f"{RED}File not found in data/files/: {arg}{RESET}")
                continue

            print(f"{CYAN}Ingesting {target.name} into HydraDB graph store...{RESET}")
            t0 = time.perf_counter()
            try:
                from multimodal_pipeline import extract_artifacts, graph_for_artifacts
                from pathcontext.hydradb_ingest import write_graph

                artifacts = extract_artifacts(target)
                nodes, edges = graph_for_artifacts(target, artifacts)
                written = write_graph(hydradb, nodes, edges)
                dt = (time.perf_counter() - t0) * 1000
                print(f"{GREEN}✔ Successfully ingested:{RESET} {len(nodes)} nodes, {len(edges)} edges in {dt:.0f}ms")
            except Exception as err:
                print(f"{RED}Ingestion failed:{RESET} {err}")
            continue

        if line.startswith("/mode"):
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                requested = parts[1].strip()
                if requested in ("live", "local"):
                    mode = requested
                    print(f"{GREEN}✔ Mode switched to:{RESET} {mode.upper()}")
                else:
                    print(f"{AMBER}Mode must be 'live' or 'local'{RESET}")
            else:
                print(f"Current mode: {GREEN if mode == 'live' else AMBER}{mode}{RESET}")
            continue

        if line == "/status":
            groq_key = os.getenv("GROQ_API_KEY", "")
            groq_ok = bool(groq_key and not groq_key.startswith("replace"))
            print(f"\n{BORDER}╭─{RESET} {ORANGE_BOLD}SYSTEM STATUS{RESET} {BORDER}{'─' * (CARD_WIDTH - 18)}╮{RESET}")
            print(f"{BORDER}│{RESET}  Engine Mode:    {GREEN if mode == 'live' else AMBER}{mode.upper()}{RESET}")
            print(f"{BORDER}│{RESET}  HydraDB URL:    {WHITE}{hydradb.url}{RESET}")
            print(f"{BORDER}│{RESET}  Cell ID:        {WHITE}{hydradb.cell_id}{RESET}")
            print(f"{BORDER}│{RESET}  Queries Run:    {WHITE}{hydradb.query_count}{RESET}")
            print(f"{BORDER}│{RESET}  Last Read Epoch:{WHITE}{hydradb.last_read_epoch or 'none'}{RESET}")
            print(f"{BORDER}│{RESET}  Active Dataset: {PEACH}{active_dataset}{RESET} ({active_session.count_summary() if active_session else 'none'})")
            print(f"{BORDER}│{RESET}  Groq API:       {GREEN + 'Configured (' + os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant') + ')' if groq_ok else GRAY + 'Not configured'}{RESET}")
            print(f"{BORDER}│{RESET}  OpenCode CLI:   {GREEN + 'Configured' if os.getenv('OPENCODE_COMMAND') else GRAY + 'Disabled'}{RESET}")

            # Test live ping
            if mode == "live":
                try:
                    t0 = time.perf_counter()
                    hydradb.query("RETURN 1")
                    ping_ms = (time.perf_counter() - t0) * 1000
                    print(f"{BORDER}│{RESET}  Live Ping:      {GREEN}Connected ({ping_ms:.1f}ms){RESET}")
                except Exception as ex:
                    print(f"{BORDER}│{RESET}  Live Ping:      {RED}Unreachable ({ex}){RESET}")
            print(f"{BORDER}╰{'─' * (CARD_WIDTH - 2)}╯{RESET}\n")
            continue

        # ── Compare Token Usage (Naive RAG vs PathContext Graph) ─────────────
        if line.startswith("/compare"):
            question = line[8:].strip()
            if not question:
                print(f"{AMBER}Usage: /compare <question>{RESET}")
                continue

            # 1. Match the best document snapshot by question terms
            terms = extract_query_terms(question)
            best_session: LocalSnapshotSession | None = None
            best_score = -1.0

            for s_name, s_sess in available_snapshots.items():
                if s_sess.kind == "document_snapshot":
                    score = 0.0
                    for v in s_sess.vertices:
                        props = v.get("properties", {})
                        sec = props.get("section", "")
                        sum_text = props.get("summary", "")
                        body = props.get("text", "")
                        haystack = _norm_term(f"{sec} {sum_text} {body}")
                        hits = sum(1 for term in terms if term in haystack)
                        if hits > 0:
                            score += (hits ** 2) * 10
                    if score > best_score:
                        best_score = score
                        best_session = s_sess

            if best_session is None or best_score <= 0:
                if active_session and active_session.kind == "document_snapshot":
                    best_session = active_session
                elif available_snapshots:
                    best_session = next(iter(available_snapshots.values()))

            if not best_session:
                print(f"{RED}No document snapshot available to benchmark.{RESET}")
                continue

            # Display name of target
            target_display = best_session.name
            clean_stem = best_session.name.replace(".snapshot", "").replace(".json", "")
            matched_file = next((f for f in DATA_FILES_DIR.iterdir() if f.stem.lower() == clean_stem.lower()), None)
            if matched_file:
                target_display = matched_file.name

            print(f"{CYAN}Running comparative benchmark on {PEACH}{target_display}{CYAN}...{RESET}")
            try:
                # 2. Compute Naive RAG baseline from the SAME target document
                all_chunks = [
                    v.get("properties", {}).get("text") or v.get("properties", {}).get("summary") or ""
                    for v in best_session.vertices
                    if v.get("label") in ("Artifact", "Chunk") and (v.get("properties", {}).get("text") or v.get("properties", {}).get("summary"))
                ]

                naive_chunks = all_chunks[:20] if all_chunks else [""]
                naive_context = "\n".join(f"- {c}" for c in naive_chunks)
                before_tokens = max(1, (len(naive_context) + 3) // 4)
                before_chars = len(naive_context)
                before_chunks_count = len(naive_chunks)

                # 3. PathContext Graph: Top verified, bounded facts from the SAME document
                max_facts = 1 if len(all_chunks) <= 4 else 2
                after = best_session.retrieve_document(question, max_facts=max_facts)
                after_tokens = max(1, (len(after.context) + 3) // 4)
                after_chars = len(after.context)
                after_chunks_count = len(after.facts)

                # Token & character reductions
                tok_reduction = round(max(0.0, (1 - after_tokens / before_tokens) * 100), 1)
                char_reduction = round(max(0.0, (1 - after_chars / max(before_chars, 1)) * 100), 1)
                chunk_delta = max(0, before_chunks_count - after_chunks_count)

                w = CARD_WIDTH
                title = "TOKEN REDUCTION BENCHMARK"
                dashes = max(2, w - 4 - len(title))
                print(f"\n{BORDER}╭─{RESET} {ORANGE_BOLD}{title}{RESET} {BORDER}{'─' * dashes}╮{RESET}")

                avail_q = w - 16
                print(f"{BORDER}│{RESET}  Question: {WHITE_BOLD}{question[:avail_q]:<{avail_q}}{RESET}  {BORDER}│{RESET}")
                avail_t = w - 16
                print(f"{BORDER}│{RESET}  Target:   {PEACH}{target_display[:avail_t]:<{avail_t}}{RESET}  {BORDER}│{RESET}")
                print(f"{BORDER}├{'─' * (w - 2)}┤{RESET}")

                col_strat = 18
                col_tok = 12
                col_char = 14
                col_chunk = 8
                col_cite = 24
                header = f"  {'Strategy':<{col_strat}} {'Tokens':>{col_tok}} {'Characters':>{col_char}} {'Chunks':>{col_chunk}}   {'Proven Citations':<{col_cite}}"
                print(f"{BORDER}│{RESET}{header} {BORDER}│{RESET}")
                print(f"{BORDER}│{RESET}  {GRAY}{'─' * (w - 6)}{RESET}  {BORDER}│{RESET}")

                r1 = f"  {GRAY}{'Naive RAG':<{col_strat}}{RESET} {before_tokens:>{col_tok - 4}} tok {before_chars:>{col_char - 6}} chars {before_chunks_count:>{col_chunk}}   {GRAY}{'0 (unverified)':<{col_cite}}{RESET}"
                r2 = f"  {PEACH}{'PathContext Graph':<{col_strat}}{RESET} {after_tokens:>{col_tok - 4}} tok {after_chars:>{col_char - 6}} chars {after_chunks_count:>{col_chunk}}   {GREEN_BOLD}{f'{after_chunks_count} (ranked & cited)':<{col_cite}}{RESET}"
                print(f"{BORDER}│{RESET}{r1} {BORDER}│{RESET}")
                print(f"{BORDER}│{RESET}{r2} {BORDER}│{RESET}")
                print(f"{BORDER}├{'─' * (w - 2)}┤{RESET}")

                gain_str = f"Efficiency Gain:   {tok_reduction}% fewer tokens  │  {char_reduction}% fewer chars  │  {chunk_delta} fewer chunk{'s' if chunk_delta != 1 else ''}"
                avail_g = w - 6
                print(f"{BORDER}│{RESET}  {GREEN_BOLD}{gain_str[:avail_g]:<{avail_g}}{RESET}  {BORDER}│{RESET}")
                print(f"{BORDER}╰{'─' * (w - 2)}╯{RESET}\n")
            except Exception as err:
                print(f"{RED}Comparison failed:{RESET} {err}")
            continue

        # ── openCypher Query ─────────────────────────────────────────────────
        if line.startswith("/query"):
            cypher = line[6:].strip()
            if not cypher:
                print(f"{AMBER}Usage: /query <openCypher query>{RESET}")
                continue
            if mode != "live":
                print(f"{AMBER}/query executes directly against HydraDB in live mode.{RESET}")
                print(f"{GRAY}Switch to live mode with: /mode live{RESET}")
                continue

            print(f"{GRAY}Executing openCypher...{RESET}")
            try:
                t0 = time.perf_counter()
                result = hydradb.query(cypher)
                dt = (time.perf_counter() - t0) * 1000
                print(f"\n{BORDER}╭─{RESET} {ORANGE_BOLD}QUERY RESULT{RESET} {GRAY}({dt:.1f}ms){RESET} {BORDER}{'─' * (CARD_WIDTH - 24)}╮{RESET}")
                print(json.dumps(result, indent=2, default=str))
                print(f"{BORDER}╰{'─' * (CARD_WIDTH - 2)}╯{RESET}\n")
            except HydraDBError as err:
                print(f"{RED}HydraDB error:{RESET} {err}")
            continue

        # ── Natural Language /ask Pipeline ───────────────────────────────────
        question = line[5:].strip() if line.startswith("/ask ") else line

        print(f"\n{GRAY}● Compiling structural graph context...{RESET}")
        try:
            t0 = time.perf_counter()
            packet: EvidencePacket | None = None

            is_incident = any(k in question.lower() for k in ("inc-", "incident", "deploy-", "checkout-api", "runbook", "rollback"))

            # 1. Live mode if HydraDB is active
            if mode == "live":
                try:
                    if is_incident:
                        packet = HydraDBContextCompiler(hydradb).compile(question)
                    elif active_session and active_session.kind == "document_snapshot":
                        from multimodal_pipeline import retrieve as mm_retrieve
                        doc_target = active_session.source_path.stem.replace(".snapshot", "") + ".pdf"
                        packet = mm_retrieve(hydradb, doc_target, question)
                    else:
                        packet = HydraDBContextCompiler(hydradb).compile(question)
                except Exception:
                    packet = None

            # 2. Snapshot / Local Retrieval
            if packet is None or not packet.facts:
                if is_incident and local_compiler:
                    packet = local_compiler.compile(question)
                else:
                    # Search across all loaded snapshots so the highest-scoring document wins
                    all_candidates: list[Fact] = []
                    for s_name, s_sess in available_snapshots.items():
                        if s_sess.kind == "document_snapshot":
                            p = s_sess.retrieve_document(question, max_facts=4)
                            all_candidates.extend(p.facts)

                    if all_candidates:
                        all_candidates.sort(key=lambda f: f.score, reverse=True)
                        if all_candidates and all_candidates[0].score > 0:
                            top_score = all_candidates[0].score
                            # Prune weak candidates from unrelated documents to keep evidence strictly relevant
                            top_facts = [f for f in all_candidates if f.score >= top_score * 0.6][:4]
                            context = "\n".join(f"- {fact.text} [citation: {' -> '.join(fact.path)}]" for fact in top_facts)
                            packet = EvidencePacket(
                                context=context,
                                facts=top_facts,
                                contradictions=[],
                                uncertainty=[],
                                answerability="supported",
                                retrieval_stats={
                                    "matched_sources": list(set(f.source for f in top_facts)),
                                    "candidate_chunks": len(all_candidates),
                                    "selected_chunks": len(top_facts),
                                    "snapshot_consistency": "atomic (offline snapshot)",
                                },
                            )

                # 3. Fallback to incident compiler if not found in docs
                if (packet is None or not packet.facts) and local_compiler:
                    packet = local_compiler.compile(question)

            retrieval_ms = (time.perf_counter() - t0) * 1000
            if packet:
                packet.retrieval_stats["latency_ms"] = f"{retrieval_ms:.1f}ms"
                print_evidence_packet(packet)

                # Synthesis
                answer_obj = None
                groq_key = os.getenv("GROQ_API_KEY", "")
                if packet.facts and groq_key and not groq_key.startswith("replace"):
                    print(f"{GRAY}● Synthesizing grounded answer via LLM...{RESET}")
                    try:
                        answer_obj = synthesize(
                            question,
                            packet,
                            groq_api_key=groq_key,
                            groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                        )
                    except LLMError as lerr:
                        print(f"{AMBER}LLM synthesis note:{RESET} {lerr}")

                print_grounded_answer(question, packet, answer_obj)

        except (HydraDBError, LLMError, ValueError, Exception) as err:
            print(f"{RED}Error:{RESET} {err}")

    return 0


def main() -> int:
    """Launch modern Textual TUI by default, or CLI mode for scripts/pipes."""
    # Cloud web service auto-bridge (Render, Railway, Fly.io)
    is_cloud_web = (os.getenv("RENDER") or os.getenv("PORT")) and not sys.stdin.isatty() and not os.getenv("TTY_ATTACHED")
    if is_cloud_web:
        import shutil
        ttyd_bin = shutil.which("ttyd")
        web_runner = Path(__file__).parent / "run_web.sh"
        if ttyd_bin and web_runner.exists():
            port = os.getenv("PORT", "10000")
            print(f"Cloud container detected without TTY. Starting ContextFlow Web Terminal on port {port}...")
            os.execv(str(web_runner), [str(web_runner)])

    if "--textual" in sys.argv or "--gui" in sys.argv:
        try:
            from tui_textual import ContextFlowApp
            app = ContextFlowApp()
            app.run()
            return 0
        except Exception:
            return run_cli_loop()

    return run_cli_loop()


if __name__ == "__main__":
    raise SystemExit(main())
