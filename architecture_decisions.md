# PathContext architecture decisions

This document is the explanation to use during the demo. It describes what
the system does, why each boundary exists, which alternatives were rejected,
and what is verified versus still dependent on HydraDB capabilities.

## 1. The one-sentence design

PathContext is a **structural context compiler**:

```text
question
  -> resolve the entity and evidence intent
  -> choose a bounded traversal recipe
  -> retrieve connected facts from HydraDB
  -> select the minimum evidence packet
  -> return citations, uncertainty, and metrics
  -> optionally ask an LLM to explain only that packet
```

The LLM is not allowed to discover joins, invent graph queries, or decide that
two unrelated records refer to the same entity. Those are deterministic
application and database responsibilities.

## 2. Repository and responsibility split

```text
hydradb/
  Rust graph database, storage, HTTP API, query execution, indexes

ContextFlow/
  PathContext product, recipes, ingestion, evaluation, CLI/TUI, LLM boundary

ContextFlow/pathcontext/
  reusable Python implementation
```

The dependency direction is intentionally one-way:

```text
entrypoints -> pathcontext -> HydraDB HTTP API -> HydraDB server
```

### HydraDB owns

- durable vertices and relationships;
- graph identity and storage;
- relationship traversal;
- read epochs/bookmarks;
- graph indexes and adjacency structures;
- mutation execution.

### PathContext owns

- question intent and required evidence categories;
- entity resolution and ambiguity handling;
- bounded recipe selection;
- evidence ranking and token budgets;
- citation paths and uncertainty;
- graph-vs-plain-store evaluation;
- document-to-graph mapping;
- optional LLM synthesis.

### The LLM owns

- natural-language explanation of an already selected `EvidencePacket`;
- no arbitrary Cypher generation;
- no hidden retrieval;
- no unsupported claims when the packet says evidence is missing.

This split prevents the most dangerous failure mode: a fluent answer that
cannot be traced to a connected source path.

## 3. Why a graph is used

The demo question is:

> Which change caused `INC-1042`, who owns it, and what worked previously?

The answer is not one document. It is a connected chain:

```text
Incident
  -> affected Service
  -> Deployment
  -> Commit
  -> File
  -> Team

Incident
  -> affected Service
  <- previous Incident
  -> Mitigation
```

A plain lexical store can find records containing `INC-1042`, `checkout-api`,
or `mitigation`, but it does not prove that the selected records are connected
through the intended relationship types. The graph makes the join explicit.

The graph is not valuable merely because the data is drawn as nodes and
edges. It is valuable when the answer requires a multi-hop, typed relationship
that a ranked list cannot establish.

## 4. Why not only use a vector database?

Vector retrieval remains useful for finding candidate text, especially for
unstructured PDFs and arbitrary files. It is not sufficient as the primary
mechanism for this demo because:

| Requirement | Lexical/vector list | PathContext |
|---|---|---|
| Find similar text | Strong | Optional input |
| Prove a multi-hop relationship | Weak | Explicit recipe |
| Keep entities aligned | Probabilistic | IDs, aliases, states |
| Detect missing evidence | Usually implicit | Required/covered/missing |
| Cite a connected path | Difficult | Fact path is first-class |
| Bound context by evidence need | Top-k heuristic | Token budget + scoring |
| Explain contradictions | Often left to LLM | Explicit uncertainty |

The project therefore uses a hybrid direction for future documents:

```text
file/PDF -> extracted artifacts and chunks -> entity/relationship graph
                                      \-> optional lexical/vector candidates
```

Similarity can propose candidates; structure decides whether they belong in
the answer.

## 5. Why not let the LLM generate Cypher?

Unrestricted text-to-Cypher was rejected because it creates four problems:

1. query shape and cost become unpredictable;
2. unsupported HydraDB syntax fails at runtime;
3. the model can silently change the intended relationship semantics;
4. security and authorization boundaries become harder to audit.

PathContext uses explicit recipes in
[`hydradb_retriever.py`](/home/rutuj21/hydradb-hackathon/ContextFlow/pathcontext/hydradb_retriever.py).
The question selects from a small known recipe set. The query strings are
bounded, reviewable, and adapted to HydraDB's supported Cypher subset.

## 6. Entity resolution is explicit

Resolution has three possible outcomes:

```text
resolved    one entity is identified
ambiguous   multiple candidates match; do not guess
unresolved  no candidate matches
```

Aliases and names are useful input, but an alias collision must not be turned
into a confident answer. An unresolved or ambiguous entity produces
uncertainty in the evidence packet instead of a fabricated path.

## 7. Evidence requirements and answerability

PathContext derives evidence requirements from the question:

- every incident investigation requires `change`;
- “owner”, “owns”, or “team” adds `owner`;
- “previous”, “worked”, “history”, or “mitigation” adds `history`;
- “runbook” adds `runbook`.

The packet records:

```json
{
  "required_evidence": ["change", "owner", "history"],
  "covered_evidence": ["change", "history"],
  "missing_evidence": ["owner"],
  "answerability": "mixed"
}
```

This is deliberately conservative. A partial answer may still be useful, but
it must not be labelled `supported` when a requested evidence category is
absent.

## 8. Snapshot consistency

HydraDB recipe calls are separate HTTP requests. PathContext records the epoch
or bookmark returned by each response:

```text
same epoch     -> atomic for the observed reads
different epoch -> non_atomic and answerability becomes mixed
```

This is safer than pretending several requests were one transaction. A future
HydraDB causal-bookmark API can be wired into the same boundary; until that
request contract is verified, the packet reports the limitation explicitly.

## 9. Why the local graph and plain store both exist

The local evaluator contains two controls:

```text
GraphStore  indexed outgoing/incoming adjacency
PlainStore  intentionally unindexed relationship scans
```

Both receive the same records, questions, recipes, and context budget. The
only intended difference is the access structure. This answers the question:

> Is the graph doing real work, or is the result just a lucky one-off?

The evaluator measures repeated runs of:

- relevant fact recall;
- citation accuracy;
- unsupported claim rate;
- input tokens;
- latency;
- edge scans;
- context density;
- continual-ingestion recovery.

The current fixture result demonstrates:

```text
graph recall:              1.0
graph citation accuracy:   1.0
graph unsupported claims:  0.0
plain-store recall:        1.0
edge-scan reduction:       approximately 83%
lexical recall improvement: +0.6667 absolute
```

The plain store is an important control: graph quality should not be claimed
just because the graph implementation exists. The measurable graph win here
is lower relationship scanning at equal answer quality.

## 10. Continual learning claim

This project does **not** claim that a model was retrained after every write.
The defensible claim is continual evidence ingestion and deterministic
re-indexing:

```text
before increment -> new incident is not answerable
after increment  -> new connected evidence is answerable
```

That is a real operational learning loop for the context layer. Model
fine-tuning can be added later, but it is not necessary to demonstrate that
new graph facts become available without rebuilding the application.

## 11. Documents and multimodal inputs

The document path preserves source location:

```text
Document -> Page -> Chunk
Document -> Artifact
```

Each chunk or artifact carries source metadata and a locator. Text extraction,
Markdown, logs, JSON, CSV/TSV, and common image formats are supported by the
pipeline. Optional vision summarization is kept behind the LLM adapter.

The same rule applies: the LLM may summarize an extracted artifact, but the
source file, page, chunk, or artifact locator remains the citation anchor.

## 12. HydraDB preparation and read-server boundary

The MVP uses HydraDB for the capability that is proven and valuable in the
demo:

```text
prebuilt graph image
  -> HydraDB
  -> live authenticated reads
  -> bounded multi-hop traversal
  -> evidence packet
  -> agent answer
```

Preparation is a separate offline step:

```text
fixture/PDF
  -> offline graph builder
  -> snapshots/*.snapshot.json
  -> approved HydraDB snapshot/import provisioning
  -> start read server
```

[`prepare_snapshot.py`](/home/rutuj21/hydradb-hackathon/ContextFlow/prepare_snapshot.py)
creates the deterministic manifest. It assigns stable integer IDs, preserves
human-readable `external_id` values, records labels and properties, and emits
relationship counts. It does not pretend that the live HTTP mutation endpoint
accepted a write.

The current HydraDB build can serve the prepared graph and perform
authenticated reads. Its mutation path still rejects some graph mutations,
including label updates and edge creation. Therefore:

- local/offline demo: verified;
- live HydraDB reads: verified;
- offline snapshot preparation: verified;
- live HydraDB writes: outside the MVP demo;
- no failed mutation is reported as success.

That is an intentional engineering decision. A smaller honest MVP is better
than a demo that fabricates persistence.

## 13. Demo script

From the application directory:

```bash
cd /home/rutuj21/hydradb-hackathon/ContextFlow

# Always works without live-write assumptions:
python3 run_demo.py

# Prepare the graph image before starting the server:
python3 prepare_snapshot.py

# Provision snapshots/incidents.snapshot.json, then start the read server:
bash start_hydradb_write_node.sh

# Verify the live read path:
python3 hydradb_agent.py \
  "Which change caused INC-1042, who owns it, and what worked previously?"

# Strictly require the prepared-image/read-server demo:
python3 run_demo.py --require-live
```

The default `run_demo.py` writes
[`results/hackathon_report.json`](/home/rutuj21/hydradb-hackathon/ContextFlow/results/hackathon_report.json)
and returns success when the offline/continual demo succeeds, even if the
optional live section records a HydraDB read failure. `--require-live` is for
the prepared-image/read-server acceptance check.

## 14. Cross-question: why this architecture?

**Why graph-first?** The first questions require typed multi-hop joins.

**Why explicit recipes?** They are bounded, testable, and compatible with the
actual HydraDB dialect.

**Why Python outside HydraDB?** Intent, evidence policy, and presentation
change faster than storage and traversal infrastructure.

**Why keep an LLM?** Natural-language explanation is useful after evidence has
been selected; it is not reliable as the database planner.

**Why track uncertainty?** Missing ownership or mixed epochs must be visible to
the user and downstream agent.

**Why keep a plain-store baseline?** To prove the graph contributes measurable
work instead of relying on a one-off success.

**Why separate preparation from serving?** Preparation is deterministic and
reviewable. The live capability used by the MVP is authenticated,
snapshot-scoped traversal. This keeps the demo honest while leaving mutation
and import as an explicit operational boundary.

**Why not hide HydraDB write failures?** Persistence is part of the product
contract. A successful-looking fallback would invalidate every ingestion and
evaluation claim.

**Why support documents as well as incidents?** Incidents demonstrate
relationship value; documents prove the same evidence/citation boundary can
extend beyond one fixture domain.

## 15. What “MVP working” means

The MVP is working when the following are true:

- the local demo runs end to end;
- repeated evaluation produces stable metrics;
- continual ingestion changes answerability as expected;
- live HydraDB reads return bounded facts and epochs;
- evidence gaps are surfaced rather than guessed;
- the prepared graph is served through authenticated HydraDB reads;
- the demo report distinguishes verified behavior from pending infrastructure.

The project should only claim full live ingestion after two successful writes,
readback counts, stable second-run counts, property verification, and
document-ingestion verification all pass.
