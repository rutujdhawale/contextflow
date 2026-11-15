# ContextFlow

ContextFlow is a deterministic structural context compiler for AI agents. It
resolves known incident entities, runs bounded traversal recipes, selects a
minimum evidence set under a token budget, and returns provenance for every
fact.

For the complete from-scratch setup and the normal-RAG versus HydraDB
comparison runbook, see
[INSTRUCTIONS.md](/home/rutuj21/hydradb-hackathon/ContextFlow/INSTRUCTIONS.md).
For the source-verified architecture audit and current readiness gaps, see
[results/architecture_audit.md](/home/rutuj21/hydradb-hackathon/ContextFlow/results/architecture_audit.md).
For the detailed architecture decisions, tradeoffs, demo flow, and
cross-question rationale, see
[architecture_decisions.md](/home/rutuj21/hydradb-hackathon/ContextFlow/architecture_decisions.md).

## Repository layout: `ContextFlow`, `pathcontext`, and `hydradb`

There are two different levels in this workspace, which can make the names
look duplicated:

```text
/home/rutuj21/hydradb-hackathon/
├── hydradb/                 # HydraDB database engine repository
└── ContextFlow/             # PathContext application/demo repository
    ├── pathcontext/         # Reusable Python package/library
    ├── data/files/          # Local source PDFs and other input files
    ├── fixtures/            # Small deterministic incident graph fixtures
    ├── results/             # Generated evaluation reports
    ├── ingest.py            # Fixture and graph ingestion helpers
    ├── pdf_pipeline.py      # PDF -> Document/Page/Chunk graph pipeline
    ├── hydradb_smoke.py     # HydraDB connectivity and read-epoch check
    ├── hydradb_context.py   # Direct multi-hop HydraDB recipe demo
    ├── hydradb_agent.py     # Live structured context CLI
    ├── tui.py               # Interactive terminal UI
    ├── evaluate.py          # Graph/baseline repeated evaluation
    ├── continual_evaluate.py# Incremental-ingestion evaluation
    ├── prepare_snapshot.py  # Offline graph-image preparation
    ├── snapshots/           # Prepared HydraDB-compatible manifests
    ├── run_demo.py          # One-command hackathon acceptance runner
    ├── test_pathcontext.py  # Regression and provider tests
    ├── .env                 # Local secrets/runtime configuration (ignored)
    └── README.md            # This guide
```

### What each name means

**`hydradb/`** is the database engine. It contains the Rust server, native
dependencies, graph execution code, storage, HTTP API, and HydraDB's own
build/test configuration. You start this repository when you need the database
server running.

**`ContextFlow/`** is the application project built on top of HydraDB. It
contains the PathContext product, demos, evaluation harness, TUI, PDF
ingestion, and LLM integration. You normally run commands from this directory.

**`ContextFlow/pathcontext/`** is not a second application and not a second
database. It is the importable Python package inside the application. The
top-level scripts are executable entrypoints; this package contains the
reusable implementation:

| Module | Responsibility |
|---|---|
| `schema.py` | Typed entities, relationships, facts, paths, and evidence packets |
| `graph.py` | Indexed local graph store and traversal telemetry |
| `plain_store.py` | Unindexed control used to prove graph work is real |
| `traversal_recipes.py` | Explicit incident relationship recipes |
| `context_compiler.py` | Evidence selection, budgets, uncertainty, and formatting |
| `hydradb_client.py` | Authenticated HydraDB HTTP client |
| `hydradb_retriever.py` | HydraDB-backed incident evidence compiler |
| `llm.py` | Groq adapter and OpenCode fallback |
| `agent.py` | Stable structured context interface for agents |
| `env.py` | Dependency-free local `.env` loader |

The normal dependency direction is:

```text
entrypoint scripts
        ↓
ContextFlow/pathcontext package
        ↓
HydraDB HTTP API
        ↓
hydradb/ server process
```

### Start HydraDB with writes enabled

The default `cargo run --features server-runtime` starts the legacy query
engine. It can serve the existing graph but the mutation executor in that mode
can return `internal query execution error` for new writes. Start the
write-capable DataFusion build instead:

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow
bash start_hydradb_write_node.sh
```

The script builds HydraDB with `datafusion-cypher-engine`, sets
`GRAPH_CYPHER_ENGINE=datafusion`, provisions the pinned LAGraph dependency
under `hydradb/.hydradb/lagraph` when needed, and starts the node with the
same local ports, token, and store layout. Stop any existing graph-node
process first; two processes must not share the same store.

For a manual HydraDB build, install LAGraph and export its library directory:

```bash
cd /home/rutuj21/hydradb-hackathon/hydradb
bash scripts/install_lagraph.sh "$PWD/.hydradb/lagraph"
LAGRAPH_LIB_DIR="$PWD/.hydradb/lagraph/lib" \
  just build-datafusion-node
```

Do not treat a read-only smoke test as ingestion success. Use:

```bash
.venv/bin/python hydradb_smoke.py --ingest
```

It must print `ingested_operations` and exit non-zero if the write is rejected.

The Python package does not replace HydraDB. Python selects a bounded recipe,
asks HydraDB to execute graph traversal, compresses the returned evidence, and
optionally asks the LLM to explain only that evidence.

### Which directory should you use?

| Goal | Directory/command |
|---|---|
| Build or run the database engine | `cd /home/rutuj21/hydradb-hackathon/hydradb` |
| Run PathContext demos and tests | `cd /home/rutuj21/hydradb-hackathon/ContextFlow` |
| Add PDFs for ingestion | `ContextFlow/data/files/` |
| Import reusable retrieval code | `from pathcontext...` while running from `ContextFlow` |

Do not move `pathcontext/` beside `ContextFlow/`; it must remain a Python
package under the application root so the entrypoints can import it reliably.

## What the end-to-end system does

For incident data:

```text
Question
  -> entity and intent resolution
  -> explicit traversal recipe
  -> HydraDB graph query
  -> bounded EvidencePacket
  -> citations, uncertainty, telemetry
  -> optional Groq/OpenCode explanation
```

For a PDF:

```text
PDF
  -> page-preserving text extraction
  -> Document node
  -> Page nodes
  -> Chunk nodes
  -> Document -[:HAS_PAGE]-> Page -[:HAS_CHUNK]-> Chunk
  -> HydraDB graph query
  -> page/chunk citations
  -> optional LLM synthesis
```

HydraDB performs the relationship traversal. PathContext does not send the
whole database to the LLM and does not allow the LLM to invent arbitrary
Cypher. This boundary is important for reproducibility, security, cost, and
citation quality.

The proven live demo separates graph preparation from serving:

```text
Fixture/PDF
  -> offline graph builder
  -> HydraDB-compatible snapshot/image
  -> start HydraDB read server
  -> authenticated multi-hop traversal
  -> evidence packet
  -> agent answer
```

The read demo does not attempt live ingestion.

## Run the local demo

Create an isolated environment with `uv`:

```bash
cd ContextFlow
uv venv .venv
uv pip install --python .venv/bin/python -U pip
```

Then run with the venv Python:

```bash
.venv/bin/python app.py
```

The demo uses the deterministic fixture and does not require a running database.
`pathcontext.hydradb_client.HydraDBClient` targets HydraDB's documented JSON
endpoint at `/v1/graphs/<graph>/query` when a live graph is available. The
`ingest.cypher_for_fixture` helper produces the corresponding OpenCypher
statements.

## First-time setup checklist

Run these commands from `ContextFlow`:

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow

# Create the isolated Python environment.
uv venv .venv

# Install the Python dependencies used by PDF fallback extraction.
uv pip install --python .venv/bin/python -r requirements.txt

# Create local configuration. This file is ignored by git.
cp .env.example .env
```

Edit `.env` and set the HydraDB token. Add `GROQ_API_KEY` only when you want
real LLM synthesis. Environment variables already exported in the shell take
precedence over values in `.env`.

The project currently uses a small dependency-free `.env` loader, so commands
must be started from the project scripts listed below. You do not need to run
`source .env`.

Check that the Python environment is the one being used:

```bash
.venv/bin/python --version
.venv/bin/python -c "import sys; print(sys.executable)"
```

Do not commit `.env`, API keys, generated reports containing sensitive data, or
large/source PDFs. `.gitignore` excludes `.env`, `.venv/`, Python cache files,
compiled bytecode, and PDFs placed in `data/files/`. Keep only
`data/files/.gitkeep` in version control unless a specific source artifact is
explicitly approved for the repository.

## Complete workflow from scratch

This is the recommended sequence for a new machine or a new demo dataset.

### 1. Prepare the graph image offline

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow
python3 prepare_snapshot.py
```

This writes
[`snapshots/incidents.snapshot.json`](/home/rutuj21/hydradb-hackathon/ContextFlow/snapshots/incidents.snapshot.json)
with stable IDs, labels, properties, relationship types, and counts. Provision
this prepared image into the HydraDB store using the approved snapshot/import
procedure before starting the read server. The preparation command does not
claim to perform live HTTP mutations.

### 2. Start HydraDB for authenticated reads

Build/start the HydraDB server from the separate database repository:

```bash
cd /home/rutuj21/hydradb-hackathon/hydradb
# Use the HydraDB repository's documented start command.
```

Confirm the HTTP health endpoint before using PathContext:

```bash
curl http://127.0.0.1:8443/healthz
```

Expected response:

```json
{"status":"ok"}
```

HydraDB health only proves that the server is alive. The smoke test below
proves that authenticated graph queries work.

### 3. Create the PathContext environment

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
```

Set these values in `.env`:

```env
PATHCONTEXT_HYDRADB_URL=http://127.0.0.1:8443
PATHCONTEXT_GRAPH_ID=default
PATHCONTEXT_CELL_ID=cell-0
PATHCONTEXT_HYDRADB_TOKEN=your-hydradb-token
GROQ_API_KEY=your-groq-key
GROQ_MODEL=llama-3.1-8b-instant
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
```

The local scripts load `.env` automatically. Shell environment variables take
precedence over `.env`. Never commit the real `.env`.

### 4. Verify the database connection

```bash
.venv/bin/python hydradb_smoke.py
```

Then run the proven read path:

```bash
.venv/bin/python hydradb_agent.py \
  "Which change caused INC-1042, who owns it, and what worked previously?"
```

`hydradb_agent.py` is a Python script, so do not type
`hydradb_agent.py` by itself unless you have created a shell alias. Use
`.venv/bin/python hydradb_agent.py ...` as shown above.

`hydradb_smoke.py --ingest` remains available as a separate mutation
compatibility test. It is not part of the proven read-only demo.

### 4. Add data

Place local files in `data/files/`, or pass an absolute path. Supported
formats are:

```text
PDF, TXT, Markdown, LOG, JSON, CSV, TSV, PNG, JPG, JPEG, WEBP
```

The source file remains local. The graph stores typed metadata and compact
artifacts, not an unrestricted copy in the LLM prompt.

### 5. Ingest and query one file

For a text/table/image/PDF file:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "/absolute/path/to/file.pdf" \
  --ingest \
  --question "What are the important findings?"
```

For images, charts, and visual PDF pages, add `--vision`. This performs
one-time ingestion-time vision analysis:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "/absolute/path/to/file.pdf" \
  --vision \
  --ingest
```

Then query without sending the image again:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "data/files/file.pdf" \
  --question "What trend does the chart show?" \
  --max-context-tokens 800
```

### 6. Use the interactive RAG console

```bash
.venv/bin/python tui.py
```

The TUI is an interactive terminal program; it does not open a browser window
or a separate GUI. Start it in a terminal and wait for:

```text
pathcontext>
```

Then type a command such as:

```text
/mode live
/ask Which change caused INC-1042, who owns it, and what worked previously?
```

Use:

```text
/mode live
/ask What does the document say about the main risk?
/status
/clear
/quit
```

The TUI retrieves from HydraDB first, prints evidence and citations, then
optionally calls Groq/OpenCode. The LLM never receives unrestricted graph
access.

## Live HydraDB read demonstration

With `graph-node` running in another terminal:

```bash
cd ContextFlow
cp .env.example .env
# edit .env and set PATHCONTEXT_HYDRADB_TOKEN (+ GROQ_API_KEY if needed)
.venv/bin/python hydradb_smoke.py
```

The smoke test executes a real authenticated read, checks that JSON rows are
returned, and requires a returned `read_epoch` or `bookmark`. The graph is
prepared and provisioned before this step; the read demo does not mutate
HydraDB. If the server uses bearer authentication, set the token value to the
token itself; the client adds the required `Bearer` prefix. It also accepts a
value that already starts with `Bearer`.

The separate `hydradb_smoke.py --ingest` command remains a mutation
compatibility test for future HydraDB import/writer support. It is intentionally
not part of the proven demo path.

HydraDB reserves `id` as an integer vertex key. The ingestion adapter maps
PathContext's human-readable IDs such as `INC-1042` to stable integer `id`
values and stores the original value as `external_id`.

To prove that HydraDB itself, rather than the Python control, performs the
relationship work on the prepared graph, run the recipes directly in HydraDB:

```bash
python3 hydradb_context.py
```

The output contains the three multi-hop recipe results and the HydraDB
`read_epoch`/bookmark telemetry. These are the same change-attribution,
historical-mitigation, and runbook relationships represented by the local
compiler, but the joins happen in OpenCypher inside HydraDB.

The agent-facing live compiler converts those HydraDB rows into the same
provenance-preserving packet returned by the local compiler:

```bash
python3 hydradb_agent.py \
  "Which change caused INC-1042, who owns it, and what worked previously?"
```

The command prints both the answer and the JSON evidence packet. With the
prepared demo graph, the answer is grounded in:

```text
change: deploy-8842 -> commit-771 -> payment-client.py -> Payments-Platform
history: INC-991 -> mit-77
```

No API key is required for this deterministic answer. Groq/OpenCode can still
be enabled for optional natural-language synthesis in the TUI.

This is the intended production boundary: HydraDB performs relationship
traversal; Python performs recipe selection, evidence compression, and agent
response formatting.

## Test

```bash
python3 -m unittest -v
```

## Evaluation

Run the complete reproducible report:

```bash
export PATHCONTEXT_HYDRADB_TOKEN='local-development-token-32-bytes'
python3 run_demo.py --repetitions 20 --output results/hackathon_report.json
```

This runs the repeated offline comparison, continual-ingestion acceptance, and
live HydraDB packet flow in one command. Without the token, it still runs the
offline checks and marks live acceptance as `not_run` rather than claiming
success.

Run the repeated baseline and graph-work comparison:

```bash
python3 evaluate.py --repetitions 20 --output results.json
```

The report compares:

* `pathcontext_graph`: indexed adjacency, representing the structural graph
  execution path;
* `pathcontext_plain_store`: the same compiler and records with full edge
  scans, testing whether graph structure does real work;
* `lexical_baseline`: independent top-k lexical records with no relationship
  joins.

It reports repeated-run recall, citation accuracy, token use, latency, edge
scans, and the graph's edge-scan reduction. The baseline uses the same
questions, fixture, and budget; it is not a one-off qualitative comparison.

Run the continual-ingestion check:

```bash
python3 continual_evaluate.py
```

This explicitly distinguishes incremental graph ingestion from ML training:
the new incident chain is not visible before the batch and becomes retrievable
after the batch.

## Before/after RAG comparison

Use [compare_rag.py](/home/rutuj21/hydradb-hackathon/ContextFlow/compare_rag.py)
to compare a naive RAG-style context against PathContext retrieval using the
same file and the same question.

### What “before” means

The before system is intentionally transparent:

```text
file
  -> extract artifacts
  -> take the first N artifacts
  -> send their summaries as context
```

It does not use graph structure, artifact ranking, or a token budget beyond the
configured artifact cap. This approximates a naive file-level RAG pipeline.

### What “after” means

The after system is:

```text
file
  -> Document/Artifact graph in HydraDB
  -> graph traversal
  -> lexical relevance ranking
  -> max artifact limit
  -> token budget
  -> cited EvidencePacket
```

Run the deterministic retrieval comparison first:

```bash
.venv/bin/python compare_rag.py \
  --file "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --ingest \
  --question "What does the document say about concealing intentions?" \
  --naive-artifacts 20 \
  --max-context-tokens 800 \
  --output results/rag_comparison.json
```

Run the real LLM comparison when `GROQ_API_KEY` is configured:

```bash
.venv/bin/python compare_rag.py \
  --file "data/files/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --question "What does the document say about concealing intentions?" \
  --max-context-tokens 800 \
  --llm \
  --output results/rag_comparison_llm.json
```

Use `--ingest` the first time for a file. Reuse the second command for later
questions after the graph has been populated.

### Metrics in the comparison report

The JSON report includes:

| Metric | Meaning |
|---|---|
| `input_tokens_estimate` | Provider-independent estimate from the context text |
| `context_chars` | Raw context size sent toward synthesis |
| `facts` | Number of selected evidence items |
| `citations` | Evidence items with source and path metadata |
| `answerability` | Whether the bounded retriever found a strong match |
| `candidate_artifacts` | All artifacts returned from HydraDB |
| `selected_artifacts` | Artifacts actually passed forward |
| `retrieval_latency_ms` | Retrieval time for each approach |
| `llm.input_tokens` | Provider-reported prompt tokens when available |
| `llm.output_tokens` | Provider-reported completion tokens when available |
| `llm.total_tokens` | Provider-reported total, or fallback estimate |
| `delta.context_token_reduction` | Fractional context reduction after graph retrieval |
| `delta.llm_total_token_reduction` | Fractional total LLM-token reduction |

Interpret results carefully:

* token reduction alone is not success if answer quality declines;
* compare citations and answerability with the same questions;
* include questions that should be unsupported;
* repeat across multiple files and questions;
* inspect the actual cited artifact text, not only the generated prose.

For a credible demo, create a small question set with expected source pages or
artifact locators and run the same set through both systems. Report mean, p50,
and p95 latency plus average token reduction and citation accuracy. The
incident evaluator already follows this repeated-measurement pattern; the PDF
benchmark should adopt the same discipline.

## Agent tool

`pathcontext.agent.retrieve_structured_context` is the integration boundary:

```python
from ingest import load_fixture
from pathcontext.agent import retrieve_structured_context
from pathcontext.context_compiler import ContextCompiler

compiler = ContextCompiler(load_fixture("fixtures/incidents.json"))
packet = retrieve_structured_context(
    compiler,
    question="Which change caused INC-1042 and who owns it?",
    context_budget_tokens=800,
)
```

The response includes `context`, source-backed `facts`, contradictions,
uncertainty, qualitative answerability, and bounded retrieval statistics.

## Interactive TUI and LLM synthesis

Start the Claude-Code-inspired terminal console with a PathContext palette:

```bash
export PATHCONTEXT_HYDRADB_TOKEN='local-development-token-32-bytes'
python3 tui.py
```

Commands:

```text
/ask Which change caused INC-1042, who owns it, and what worked previously?
/query MATCH (n:Incident) RETURN n.external_id AS id
/mode local
/mode live
/help
/quit
```

The TUI always retrieves structured evidence first. It never gives the LLM raw
graph access or asks it to invent Cypher. For optional answer synthesis, set a
Groq key:

```bash
export GROQ_API_KEY='...'
export GROQ_MODEL='llama-3.1-8b-instant'
```

Groq is attempted first. If it is unavailable or fails, set up a local
OpenCode CLI fallback:

```bash
export OPENCODE_COMMAND='opencode run'
```

Without either provider, the TUI still works as a deterministic evidence
console. API keys are read only from environment variables and are never
written to the report or graph. The CLI tools automatically load
[.env](/home/rutuj21/hydradb-hackathon/ContextFlow/.env) from [ContextFlow/](/home/rutuj21/hydradb-hackathon/ContextFlow) at startup.

## PDF files as graph-backed evidence

Put source PDFs in `data/files/`. The pipeline also accepts a source path and
copies it into that directory. The supplied book is intentionally treated as a
local source artifact; the application stores metadata and extracted chunks,
not a replacement copy in the LLM provider.

The PDF flow is:

1. `copy_pdf()` copies the source into `data/files/`.
2. `pdfinfo` determines the page count.
3. `pdftotext` extracts each page separately so page citations are retained.
4. Each page is split into bounded text chunks.
5. Deterministic integer IDs are generated for the document, pages, and chunks.
6. HydraDB receives idempotent `MERGE`/`SET` statements.
7. Retrieval traverses `Document -> Page -> Chunk`.
8. The packet keeps `Document`, `Page`, and `Chunk` in every fact path.
9. Only the selected evidence packet is sent to Groq.

The graph currently looks like:

```text
Document
  └── HAS_PAGE -> Page(page_number)
                    └── HAS_CHUNK -> Chunk(chunk_number, text)
                                         └── NEXT_CHUNK -> Chunk
```

This is graph-backed document retrieval, not merely a file read: HydraDB
stores and traverses the document structure, while Python ranks the returned
bounded candidates and formats citations.

Install Poppler once if `pdfinfo` or `pdftotext` is unavailable:

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils
```

`pypdf` is listed in `requirements.txt` as a Python fallback for text
extraction when Poppler is unavailable. Poppler remains recommended because it
preserves layout more reliably and also provides `pdftoppm` for optional visual
page rendering. HydraDB itself is a separate Rust service and is not installed
through this Python requirements file.

Ingest the supplied book and query its graph-backed chunks:

```bash
.venv/bin/python pdf_pipeline.py \
  --pdf "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --ingest

.venv/bin/python pdf_pipeline.py \
  --pdf "data/files/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --question "What is the central warning of the law about never outshining the master?"
```

The first command must be run with a valid `PATHCONTEXT_HYDRADB_TOKEN` in
`.env`. The second command traverses the document/page/chunk graph, then sends
only the top cited chunks to Groq when `GROQ_API_KEY` is configured. A question
with no lexical match is marked `insufficient` rather than presented as a
confident answer.

You can run ingestion and answering in one invocation:

```bash
.venv/bin/python pdf_pipeline.py \
  --pdf "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --ingest \
  --question "What does the book say about concealing intentions?"
```

Expected output has these high-level fields:

```text
status: ingested
file: data/files/THE 48 LAWS OF POWER - Robert Greene.pdf
pages: <number>
packet:
  answerability: supported|insufficient
  facts:
    source: hydradb:pdf
    path: Document -> Page -> Chunk
  retrieval_stats:
    backend: hydradb_http
answer:
  provider: groq
  text: ...
```

The exact answer and page count depend on the PDF extraction result and the
configured model. Do not evaluate the LLM by prose alone: verify that its
claims are supported by the returned chunk text and that the cited page is
actually relevant.

### PDF troubleshooting

If `pdfinfo` or `pdftotext` is missing:

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils
```

If the PDF is scanned and extraction returns empty pages, add an OCR stage
before ingestion. The current pipeline deliberately fails clearly rather than
silently claiming that an image-only PDF was indexed.

If HydraDB returns `401 Unauthorized`, check:

```bash
grep -E '^(PATHCONTEXT_HYDRADB_URL|PATHCONTEXT_GRAPH_ID|PATHCONTEXT_CELL_ID|PATHCONTEXT_HYDRADB_TOKEN)=' .env
```

The token value should be the token itself. The client adds `Bearer ` unless
the value already starts with `Bearer`. Never paste the real token into the
README, source code, fixtures, terminal transcript, or generated report.

If HydraDB is healthy but the query has no rows, verify that ingestion completed
first and that the source filename is unchanged. The retrieval query matches
the `Document.external_id` to the copied filename.

### PDF quality limitations and next improvements

The current implementation is intentionally transparent and hackathon-sized:

* ranking is lexical, not embedding-based;
* headings and chapters are not yet modeled as graph nodes;
* page headers and footers are not yet removed;
* scanned PDFs need OCR;
* the ingestion path issues multiple HTTP statements rather than using a
  server-side batch endpoint;
* arbitrary PDF evaluation needs a labeled question/page benchmark.

These are known limitations, not hidden behavior. The next quality milestone
should add heading/chapter extraction, hybrid lexical+semantic ranking, page
citation evaluation, and a negative-question test set that measures whether
unsupported questions remain `insufficient`.

## Multimodal files and token-efficient retrieval

Use [multimodal_pipeline.py](/home/rutuj21/hydradb-hackathon/ContextFlow/multimodal_pipeline.py)
for PDFs, plain text, Markdown, JSON, CSV/TSV tables, and image files:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --ingest \
  --question "What does this document say about concealing intentions?"

# Optional: render PDF pages and create one compact vision summary per page.
# This is an ingestion-time cost; later questions reuse the summaries.
.venv/bin/python multimodal_pipeline.py \
  --file "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --vision \
  --ingest

.venv/bin/python multimodal_pipeline.py \
  --file data/files/metrics.csv \
  --ingest \
  --question "Which column describes the largest value?"
```

The multimodal graph stores:

```text
Document -[:HAS_ARTIFACT]-> Artifact
```

Each artifact has a type such as `pdf_text`, `text`, `table`, or `image`, a
stable locator, compact summary, and source metadata. The raw file remains in
`data/files/`; it is not placed into the LLM prompt.

### Images, charts, and tables

For image files or rendered charts, enable one-time vision summarization during
ingestion:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file data/files/architecture.png \
  --vision \
  --ingest
```

When `GROQ_API_KEY` is configured, the image is sent once to the configured
vision model (`GROQ_VISION_MODEL`, or the default in `llm.py`). The resulting
description is stored as the artifact summary. Later questions use that
summary and do not resend the image. If vision is unavailable, the artifact is
still indexed with its MIME type and a clear uncertainty message.

For PDF pages, `--vision` uses Poppler's `pdftoppm` to render each page
temporarily, sends the rendered page once for a compact visual description,
and removes the temporary image after ingestion. Install `poppler-utils` for
`pdfinfo`, `pdftotext`, and `pdftoppm`.

CSV and TSV files are summarized using:

* row and column counts;
* column names;
* a small sample;
* the source locator;
* compact metadata.

This prevents a full table from consuming the LLM context window. For exact
numeric analysis, add a typed aggregation artifact rather than asking the LLM
to infer arithmetic from sampled rows.

### Token budget behavior

Retrieval selects at most four artifacts and defaults to a 1,200-token context
budget:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file data/files/report.pdf \
  --question "What changed in the chart?" \
  --max-context-tokens 600
```

The response reports `candidate_artifacts`, `selected_artifacts`,
`input_tokens`, and `token_budget`. The LLM sees only:

```text
question
  + selected compact summaries
  + Document -> Artifact -> Locator citations
```

It does not see the complete PDF, complete CSV, or all images. This is the
intended token-saving behavior: ingest and summarize once, then reuse compact
evidence across questions.

### Honest limitations

The current multimodal layer is deliberately lightweight:

* PDF layout understanding is still primarily text extraction;
* embedded PDF images are not automatically rendered and vision-indexed;
* table summaries do not replace exact database aggregation;
* image understanding depends on a configured vision-capable provider;
* semantic embeddings are not yet required, so ranking remains lexical over
  stored summaries;
* unsupported or weakly matched questions remain `insufficient`.

The next improvement should render PDF pages containing visual content,
extract headings and tables into typed nodes, and evaluate citation accuracy
with a labeled multimodal question set.
