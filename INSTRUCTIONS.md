# PathContext comparison instructions

This document is the reproducible runbook for comparing:

1. **Normal RAG**: a non-graph baseline that extracts file artifacts and sends
   a bounded set of ordinary text chunks/summaries to the LLM.
2. **PathContext + HydraDB**: the graph-backed system that stores
   `Document -> Artifact` relationships in HydraDB, retrieves relevant
   artifacts, enforces a token budget, and sends only cited evidence to the
   LLM.

The purpose is to measure whether the graph-backed flow reduces context and
LLM token usage **without reducing answer quality or citation quality**.

Token reduction by itself is not a success criterion. A valid comparison must
measure:

- input/context tokens;
- output tokens;
- total tokens;
- latency;
- number of retrieved artifacts;
- number of selected artifacts;
- citation coverage;
- answerability;
- unsupported claims or missing evidence;
- answer quality across repeated questions.

---

## 1. Repository layout

Run all application commands from:

```text
/home/rutuj21/hydradb-hackathon/ContextFlow
```

The important directories are:

```text
ContextFlow/
├── pathcontext/             # Reusable Python retrieval and LLM package
├── data/files/              # Local PDFs, images, text, and tables
├── fixtures/                # Deterministic incident graph data
├── results/                 # Generated JSON comparison reports
├── multimodal_pipeline.py   # PDF/text/CSV/image ingestion
├── compare_rag.py           # Normal versus HydraDB comparison
├── hydradb_smoke.py         # Authenticated HydraDB connectivity check
├── tui.py                   # Interactive terminal interface
├── evaluate.py              # Repeated incident graph evaluation
└── test_pathcontext.py      # Regression tests
```

The separate repository:

```text
/home/rutuj21/hydradb-hackathon/hydradb
```

is the HydraDB database engine. It must be running before live graph
ingestion/retrieval commands are used.

---

## 2. Create the environment

Install `uv` if it is not already available, then create the isolated
environment:

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

The Python requirements currently include `pypdf`, which provides a fallback
PDF text extractor. HydraDB is a separate Rust service and Poppler is an
operating-system dependency, so neither belongs in `requirements.txt`.

Verify that commands use the virtual environment:

```bash
.venv/bin/python --version
.venv/bin/python -c "import sys; print(sys.executable)"
```

Do not use a mixture of system Python and `.venv/bin/python` in one experiment.
That can produce misleading dependency and timing differences.

---

## 3. Configure HydraDB and LLM providers

Create local configuration:

```bash
cp .env.example .env
```

Edit `.env`:

```env
PATHCONTEXT_HYDRADB_URL=http://127.0.0.1:8443
PATHCONTEXT_GRAPH_ID=default
PATHCONTEXT_CELL_ID=cell-0
PATHCONTEXT_HYDRADB_TOKEN=your-hydradb-token

GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.1-8b-instant
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct

OPENCODE_COMMAND=opencode run
```

The application loads `.env` automatically. Existing shell variables take
precedence over values in `.env`.

Never commit or print:

- `GROQ_API_KEY`;
- `PATHCONTEXT_HYDRADB_TOKEN`;
- complete private documents;
- private answer reports.

---

## 4. Start and verify HydraDB

In a separate terminal, start HydraDB from its own repository:

```bash
cd /home/rutuj21/hydradb-hackathon/hydradb
```

Use the normal HydraDB start command documented by that repository.

For ContextFlow ingestion, the node must be built and started with the
DataFusion mutation engine. From the application directory:

```bash
bash start_hydradb_write_node.sh
```

This launcher builds the DataFusion node and installs the pinned LAGraph
static dependency automatically when it is missing. This is not optional for
new writes. The default legacy server may answer read queries while returning
HTTP 500 for mutation execution.

Check health:

```bash
curl http://127.0.0.1:8443/healthz
```

Expected:

```json
{"status":"ok"}
```

Then run the authenticated application smoke test:

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow
.venv/bin/python hydradb_smoke.py
```

For the incident fixture:

```bash
.venv/bin/python hydradb_smoke.py --ingest
```

The smoke test is required before a graph comparison. It verifies an actual
query, not just that TCP port `8443` is open.

The fixture writer uses HydraDB's currently supported mutation shape. It
matches existing nodes by `external_id`, creates missing endpoints only as
part of an edge-attached `CREATE`, then uses one-hop relationship `MERGE`.
Standalone node `CREATE`/`MERGE` statements are deliberately avoided because
the current query engine rejects or internally fails on those forms.

---

## 5. Prepare the data

Supported input types:

```text
PDF, TXT, MD, LOG, JSON, CSV, TSV, PNG, JPG, JPEG, WEBP
```

You can keep a source file outside the repository and pass its absolute path:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --ingest
```

The file is copied into:

```text
ContextFlow/data/files/
```

Large/private PDFs are ignored by git. Do not commit copyrighted or private
source files.

For PDF text extraction, install Poppler:

```bash
sudo apt-get install poppler-utils
```

For optional image/chart/page analysis:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "/absolute/path/to/file.pdf" \
  --vision \
  --ingest
```

`--vision` performs an ingestion-time vision call and stores a compact
description. Later retrieval reuses that description instead of resending the
image.

---

## 6. Definitions of the two systems

### 6.1 Normal RAG baseline

The normal baseline in `compare_rag.py` is intentionally simple and
transparent:

```text
file
  -> extract artifacts
  -> select the first N artifacts
  -> concatenate their summaries
  -> send the context to the LLM
```

It does not use:

- HydraDB;
- graph relationships;
- graph traversal;
- source-aware relationship paths;
- graph-based evidence ranking.

This is a non-graph control, not a claim that every production vector RAG
system behaves identically.

### 6.2 PathContext + HydraDB

The graph-backed flow is:

```text
file
  -> Document node
  -> Artifact nodes
  -> Document -[:HAS_ARTIFACT]-> Artifact
  -> HydraDB traversal
  -> relevance ranking
  -> artifact limit and token budget
  -> cited EvidencePacket
  -> LLM synthesis
```

The LLM receives only the selected evidence packet. It does not receive raw
database access and does not generate unrestricted Cypher.

---

## 7. Run the comparison without an LLM

This isolates retrieval and context-size effects from model variability.

For the supplied PDF:

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow

.venv/bin/python compare_rag.py \
  --file "/home/rutuj21/Downloads/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --ingest \
  --question "What does the document say about concealing intentions?" \
  --naive-artifacts 20 \
  --max-context-tokens 800 \
  --output results/normal-vs-hydradb.json
```

Use `--ingest` the first time a file is added to HydraDB. Once the graph is
populated, omit `--ingest` for additional questions.

This command compares:

```text
normal file-context baseline
versus
HydraDB Document -> Artifact retrieval
```

The report is written to:

```text
results/normal-vs-hydradb.json
```

---

## 8. Run the comparison with the real LLM

Run the same question through both systems:

```bash
.venv/bin/python compare_rag.py \
  --file "data/files/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --question "What does the document say about concealing intentions?" \
  --max-context-tokens 800 \
  --llm \
  --output results/normal-vs-hydradb-llm.json
```

Both systems use the same:

- source file;
- question;
- provider;
- model;
- answer-generation code;
- output measurement format.

The only intended difference is the retrieved context.

If `GROQ_API_KEY` is unavailable, the command may use the configured OpenCode
fallback. Record which provider was actually used in the report before
comparing results.

---

## 9. Metrics and their meaning

The generated JSON includes `before_naive_rag`,
`after_pathcontext_hydradb`, and `delta`.

### Retrieval metrics

| Metric | Meaning |
|---|---|
| `candidate_artifacts` | Artifacts available after retrieval |
| `selected_artifacts` | Artifacts passed into the evidence context |
| `facts` | Number of evidence facts |
| `citations` | Facts that have a source and path |
| `answerability` | Whether the system found a strong match |
| `retrieval_latency_ms` | Time spent constructing the packet |
| `context_chars` | Character size of the context |
| `input_tokens_estimate` | Approximate context token count |

### LLM metrics

When the provider reports usage:

| Metric | Meaning |
|---|---|
| `llm.input_tokens` | Prompt tokens sent to the provider |
| `llm.output_tokens` | Generated answer tokens |
| `llm.total_tokens` | Input plus output tokens |
| `llm.provider` | Actual provider used |

Provider usage is preferred over estimates. The report still includes a
provider-independent estimate for comparisons when usage metadata is absent.

### Delta metrics

| Metric | Interpretation |
|---|---|
| `context_token_reduction` | Fraction of context tokens removed by graph retrieval |
| `context_char_reduction` | Fraction of context characters removed |
| `llm_total_token_reduction` | Fraction of total LLM tokens removed |
| `selected_artifact_delta` | Difference in selected artifact count |

Positive reduction means the graph-backed context is smaller.

---

## 10. How to interpret the result

A successful result should look like:

```text
HydraDB:
- fewer selected artifacts;
- fewer context/input tokens;
- equal or better answer quality;
- complete source paths;
- fewer unsupported claims;
- stable retrieval latency;
- repeatable results over multiple questions.
```

Do not claim success if:

- tokens decrease but the answer loses required facts;
- citations point to irrelevant pages/artifacts;
- the LLM invents relationships;
- only one favorable question was tested;
- the graph result is not actually read from HydraDB;
- a failed provider call is silently counted as a valid answer.

The graph-backed system must preserve quality while reducing unnecessary
context, not merely produce shorter prompts.

---

## 11. Recommended repeated benchmark

Use at least 20 questions for a credible comparison:

```text
5 direct factual questions
5 multi-step or relationship questions
5 chart/table/image questions
5 unsupported or out-of-scope questions
```

Example questions for the supplied book:

```text
What does the document say about concealing intentions?
What is the warning about never outshining the master?
What does the document say about gaining attention?
What does the document say about using absence?
What evidence supports the answer?
What does this document say about a topic that is not present?
```

Run one report per question:

```bash
mkdir -p results/benchmark

.venv/bin/python compare_rag.py \
  --file "data/files/THE 48 LAWS OF POWER - Robert Greene.pdf" \
  --question "What is the warning about never outshining the master?" \
  --max-context-tokens 800 \
  --llm \
  --output results/benchmark/outshining-master.json
```

For every report, manually or programmatically inspect:

1. whether the answer addresses the question;
2. whether every major claim appears in selected evidence;
3. whether the cited page/artifact is relevant;
4. whether the unsupported question is marked insufficient;
5. whether the normal baseline saw substantially more context;
6. whether both systems used the same provider/model.

Aggregate across questions:

```text
mean input tokens
p50 input tokens
p95 input tokens
mean output tokens
mean total tokens
mean latency
citation accuracy
answerability rate
unsupported-claim rate
context-token reduction
```

The incident evaluator in `evaluate.py` already demonstrates repeated
mean/p50/p95 reporting. The same statistical discipline should be applied to
document and multimodal benchmarks.

---

## 12. Token-budget experiments

Repeat the graph-backed system with multiple budgets:

```bash
for budget in 400 800 1200; do
  .venv/bin/python compare_rag.py \
    --file "data/files/THE 48 LAWS OF POWER - Robert Greene.pdf" \
    --question "What does the document say about concealing intentions?" \
    --max-context-tokens "$budget" \
    --llm \
    --output "results/budget-${budget}.json"
done
```

This tests the quality/cost curve:

```text
small budget  -> lowest cost, possible missing evidence
medium budget -> expected demo setting
large budget  -> more evidence, higher cost
```

Choose the smallest budget that preserves answer quality and citation
correctness.

---

## 13. Failure handling

### HydraDB returns 401

Check the token:

```bash
grep -E '^(PATHCONTEXT_HYDRADB_URL|PATHCONTEXT_GRAPH_ID|PATHCONTEXT_CELL_ID|PATHCONTEXT_HYDRADB_TOKEN)=' .env
```

The token should be the raw token. The client adds `Bearer ` automatically.
Do not paste the token into the command line or source code.

### HydraDB is healthy but retrieval returns no artifacts

Run ingestion:

```bash
.venv/bin/python multimodal_pipeline.py \
  --file "/absolute/path/to/file" \
  --ingest
```

Then rerun comparison without changing the filename.

### PDF extraction fails

Install Poppler:

```bash
sudo apt-get install poppler-utils
```

Scanned/image-only PDFs require OCR or `--vision`. Empty text extraction must
not be treated as successful semantic retrieval.

### Groq usage fields are missing

The provider may not return usage metadata for a response or fallback provider.
Use `input_tokens_estimate` and record that the number is estimated. Do not
compare an exact provider count against an estimate without labeling the
difference.

### Vision analysis fails

The file remains ingestible as an image artifact with uncertainty. Check:

- `GROQ_API_KEY`;
- `GROQ_VISION_MODEL`;
- image MIME type;
- image size;
- provider model availability.

---

## 14. Final acceptance checklist

Before presenting the demo, confirm:

```text
[ ] HydraDB health endpoint returns status ok
[ ] hydradb_smoke.py succeeds with authentication
[ ] data file is ingested into HydraDB
[ ] normal baseline report exists
[ ] HydraDB graph report exists
[ ] same question was used for both systems
[ ] same LLM/provider was used for both systems
[ ] prompt/input/output/total token fields are recorded
[ ] latency is recorded
[ ] citations are present and relevant
[ ] unsupported question is tested
[ ] repeated questions are used
[ ] results are saved under results/
[ ] no API key appears in source, reports, or terminal output
[ ] no copyrighted/private source file is committed
```

The conclusion should state both quality and efficiency:

```text
Compared with normal file-level RAG, PathContext + HydraDB used X% fewer
context tokens, preserved Y% citation accuracy, achieved Z% answerability,
and reduced/increased latency by N ms over M repeated questions.
```

If quality decreases, reduce the claim and improve retrieval before presenting
token savings as a product benefit.
