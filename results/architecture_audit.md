# PathContext Architecture Audit

## Executive summary

**Overall status: P0 code fixes implemented; live write verification pending**

**Final verdict: Architecture is sound but implementation is incomplete.**

The responsibility split is directionally correct: HydraDB owns durable graph
storage and traversal; PathContext owns intent/recipe selection, evidence
compression, provenance, and evaluation; the LLM is constrained to explanation
of an `EvidencePacket`. The live read boundary is verified, but live ingestion
is not. Therefore this is not yet a credible end-to-end write demo.

Top risks:

1. The writer now uses HydraDB's explicit-field `UNWIND` vertex-upsert shape and
   strict readback checks, but this environment could not complete a live write.
2. A live packet is assembled from independent HTTP queries; it now records
   all returned epochs and explicitly marks differing epochs as non-atomic.
3. Entity resolution and evidence-requirement coverage are now modeled, so
   `supported` requires the requested evidence categories.

## Responsibility matrix

| Area | HydraDB | PathContext | LLM | Verified |
|---|---|---|---|---|
| Durable graph storage | Yes | No | No | Yes by HydraDB design/source |
| Vertices and relationships | Yes | Ingestion mapping only | No | Partial: writes fail |
| OpenCypher execution | Yes | Query templates | No | Yes for live reads |
| Graph traversal | Yes | Recipe selection | No | Yes: live multi-hop response |
| Snapshot/read epoch | Yes | Must propagate/validate | No | Partial |
| CSC/GraphBLAS/WAL overlays | Yes | No | No | Declared by HydraDB source/docs |
| Intent/entity resolution | No | Yes | No | Partial |
| Evidence selection/compression | No | Yes | No | Partial/implemented budget |
| Explanation | No | Prompt boundary | Yes | Yes by provider code |

## Capability audit

| Capability | Status | Evidence | Test result | Gap |
|---|---|---|---|---|
| Entity resolution | Implemented | `pathcontext/entity_resolution.py` | Ambiguity regression test passes | Live alias catalog is data-dependent |
| Intent classification | Partially implemented | `_select_recipes()` keyword selection | Deterministic for a few phrases | No typed intent plan or rejection |
| Evidence requirements | Implemented | `schema.py`, `evidence_requirements.py` | Required/covered/missing regression test passes | Live packet verification remains |
| Recipe selection | Implemented | `traversal_recipes.py`, HydraDB recipes | Offline and live read paths exist | Add explicit constraints |
| HydraDB traversal | Implemented | `hydradb_retriever.py` | Live facts returned, epoch 20 | Add bounds/bookmark |
| Snapshot consistency | Explicit non-atomic boundary | `hydradb_retriever.py` records recipe epochs | Mixed-epoch regression test passes | Add server-side causal bookmark when supported |
| Candidate scoring | Implemented | `_score()` and fact scores | Offline ranking exists | No competing-candidate model |
| Minimum evidence subgraph | Partially implemented | `_select_facts()` budget ranking | Budget enforced locally | No requirement-covering optimizer |
| Contradictions | Partially implemented | Multiple deployment IDs only | Narrow local case | Add owner/time/rollback structures |
| Token budgeting | Implemented | `ContextCompiler._select_facts()` | Existing budget test | Add overflow telemetry |
| Provenance | Partially implemented | `Fact.source/path` | Citation paths emitted | Add source IDs/path validation/epoch |
| Answerability | Partially implemented | Local compiler states | Several local states exist | Live compiler only has limited states |
| PDF/multimodal graph | Partially implemented | `pdf_pipeline.py`, `multimodal_pipeline.py` | Extraction code exists | Live writes blocked |
| Baseline comparison | Implemented | `evaluate.py`, `compare_rag.py` | Repeated offline protocol exists | Not a vector baseline |
| LLM boundary | Implemented | `llm.py` | No arbitrary Cypher generation | Error fallback hides primary failure |

## Runtime verification

Verified:

- HydraDB health endpoint: `http://127.0.0.1:8443/healthz`
- Result: `{"status":"ok"}`
- Authenticated live reads: passed
- Live agent multi-hop recipes: passed
- Observed read epoch: `20`

Not verified:

```text
.venv/bin/python hydradb_smoke.py --ingest
```

The command failed during live ingestion with:

```text
HTTP 400 Bad Request
OpenCypher query is not supported yet:
UNWIND vertex upsert supports SET labels and properties only
```

Earlier single-edge mutation attempts returned HTTP 500 internal execution
errors. No node/edge count or idempotency claim is therefore made.

The Python unit suite was not executed in this environment because the sandbox
could not start without `slirp4netns`. VS Code diagnostics reported no errors
for the modified files.

## Redundant work audit

`pathcontext/graph.py` implements indexed Python traversal and
`pathcontext/plain_store.py` implements the intentionally unindexed control.
This is valid for offline evaluation and is not itself a live HydraDB duplicate,
but documentation must keep that boundary explicit.

`pdf_pipeline.py:pdf_statements()` and
`multimodal_pipeline.py:statements()` retain older standalone mutation
generators while newer paths use `pathcontext/hydradb_ingest.py`. They should
be removed or deprecated so an operator cannot accidentally select an
unsupported write path.

No arbitrary LLM-generated Cypher was found. No live full-graph loading or
Python relationship join exists in the HydraDB retriever.

## Missing capabilities and priorities

### P0 — required for a credible demo

1. **Live ingestion:** verify the exact HydraDB build/engine and supported
   parameter shape with a minimal node write, edge write, and readback before
   fixture/document ingestion. Acceptance requires two successful idempotent
   ingestions with stable counts.
2. **Evidence requirements:** add typed required fields and coverage tracking.
   `supported` must require all fields needed by the question.
3. **Entity resolution states:** return resolved, ambiguous, and unresolved
   entities. Names such as `checkout-api` must not be silently guessed.
4. **Snapshot boundary:** use a shared causal bookmark/read epoch or label the
   packet explicitly non-atomic.

### P1 — important follow-up

1. Add structured contradictions for competing deployments, owners, temporal
   ordering, and rollback.
2. Validate every claim’s source ID and path; include read epoch in citations.
3. Stop swallowing Groq errors in `synthesize()`; preserve provider failure
   details when fallback is used.
4. Add explicit live query limits and result bounds.
5. Remove/deprecate legacy document mutation generators.

## Baseline and graph-value assessment

The current offline evaluation is fair for its stated scope: the same fixture,
questions, and context budget are compared across indexed graph, unindexed
plain store, and lexical baseline. It is **not** a vector-store comparison.
Graph superiority for real PDF retrieval has not been demonstrated because live
document ingestion is failing and the PDF baseline is naive/lexical.

## Final verdict

**Architecture is sound but implementation is incomplete.**

The project is suitable for offline demonstration and live read-only HydraDB
retrieval. It becomes ready for the requested end-to-end demo only after the
P0 ingestion, snapshot, evidence-coverage, and entity-resolution gaps are
closed and rerun successfully.
