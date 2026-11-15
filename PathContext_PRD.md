# PathContext

## The Structural Context Compiler for AI Agents

**Document type:** Product Requirements Document  
**Status:** Hackathon-ready product definition  
**Primary technology:** Python + self-hosted HydraDB  
**Initial demonstration domain:** Incident investigation  
**Core category:** Context infrastructure for AI agents

---

## 1. Executive Summary

PathContext is a graph-native context layer for AI agents.

It helps agents answer relationship-heavy questions by traversing structured
relationships before retrieving text. Instead of repeatedly searching for
similar chunks and passing a large amount of context to an LLM, PathContext
constructs the smallest connected evidence structure capable of answering the
question.

The central product idea is:

> **Similarity finds candidates. Structure determines relevance.**

PathContext uses HydraDB as the structural memory engine and Python as the
context compiler. The LLM is used primarily to interpret and communicate
evidence, not to discover relationships, join records, filter time ranges, or
search a large document collection.

The first demonstration uses production incident data:

```text
Incident
  -> Alert
  -> Service
  -> Deployment
  -> Commit
  -> File
  -> Owning team
  -> Runbook
  -> Historical mitigation
```

Incident response is the first vertical because it makes the value visible.
The underlying product is domain-neutral and can later support customer
operations, dependency analysis, compliance investigations, support workflows,
and enterprise knowledge agents.

---

## 2. Problem Statement

### 2.1 The current agent failure mode

Most AI agents use a retrieval pipeline similar to:

```text
Question
  -> embed question
  -> retrieve top-k chunks
  -> send chunks to LLM
  -> ask LLM to connect them
```

This works reasonably well for direct questions about one document. It becomes
unreliable when the answer depends on relationships between multiple records.

Examples:

- Which deployment affected the service owned by this team?
- Which customer is connected to this contract and open escalation?
- Which component depends on the vulnerable library?
- Which previous incident affected the same service and had a successful fix?
- Which records describe the same entity across different systems?

The vector store returns individually plausible chunks. It does not inherently
prove that those chunks refer to the same entity, time period, environment, or
causal chain.

### 2.2 The real cost

The problem is not only answer quality. It is also context inefficiency.

Agents waste tokens on:

- duplicate descriptions;
- unrelated but semantically similar documents;
- repeated entity names;
- irrelevant historical records;
- prose that does not establish a relationship;
- information the model must manually join.

More retrieved text does not necessarily create more useful context. It often
increases ambiguity and gives the model more opportunities to infer unsupported
relationships.

### 2.3 The first-principles observation

An agent does not fundamentally need more documents. It needs:

1. the correct entities;
2. the relationships between those entities;
3. the smallest set of facts required to answer;
4. provenance for every important claim;
5. an explicit indication when the evidence is incomplete or contradictory.

This means the context layer should perform most of the information work before
the LLM is called.

---

## 3. Product Thesis

> **PathContext is a context compiler that turns questions into minimal,
> evidence-backed relationship structures.**

Traditional RAG treats context as a ranked list:

```text
chunk 1
chunk 2
chunk 3
chunk 4
```

PathContext treats context as a connected evidence packet:

```text
entity
  -> relationship
  -> related entity
  -> relationship
  -> supporting fact
```

The product should not be positioned as “another GraphRAG implementation.”
Its differentiated primitive is the **minimum evidence subgraph**.

---

## 4. Product Concept

### 4.1 Product name

**PathContext**

### 4.2 One-line description

> A structural context compiler that lets AI agents traverse relationships and
> receive only the connected evidence required to reason.

### 4.3 Product category

Context infrastructure for AI agents.

### 4.4 What PathContext is not

PathContext is not:

- a generic chatbot;
- a replacement for an incident-management system;
- a general-purpose document search product;
- an autonomous remediation agent;
- a vector database;
- an unrestricted natural-language-to-Cypher generator;
- a system that claims graph retrieval is always better than vector search.

It is a context and evidence layer between agents and structured data.

---

## 5. Target Users

### 5.1 Primary user: AI platform engineer

Needs a reusable context interface for multiple internal agents without
rebuilding retrieval logic for every application.

### 5.2 Secondary user: SRE or platform engineer

Needs an agent that can connect incidents, alerts, deployments, code changes,
ownership, and historical mitigations.

### 5.3 Tertiary user: application developer

Needs to add a reliable context tool to an agent without exposing the agent to
the full complexity of the underlying data systems.

### 5.4 Hackathon audience

Judges should be able to understand the difference immediately:

```text
Vector system:
  Here are several related documents.

PathContext:
  Here is the shortest evidence path proving the answer.
```

---

## 6. Initial Demonstration Domain

The initial demo is incident investigation, but incident response is only the
proof environment for the broader context-layer product.

### 6.1 Example question

> Which code change likely caused this incident, which team owns it, and what
> mitigation worked for a previous incident involving the same service?

### 6.2 Required evidence path

```text
Current incident
  -> affected service
  -> recent deployment
  -> changed commit
  -> changed file
  -> owning team
```

and:

```text
Current incident
  -> affected service
  -> previous incident
  -> successful mitigation
```

### 6.3 Example answer

```text
The most likely change is deploy-8842, which affected checkout-api
18 minutes before INC-1042 and modified payment-client.py.
The file is owned by Payments Platform.

A previous incident, INC-991, affected the same service and was mitigated
by disabling retry amplification.

Evidence:
INC-1042
 -> checkout-api
 -> deploy-8842
 -> payment-client.py
 -> Payments Platform

INC-1042
 -> checkout-api
 -> INC-991
 -> disable retry amplification
```

---

## 7. First-Principles System Design

### 7.1 Separation of responsibilities

The context layer performs:

- entity resolution;
- identity matching;
- relationship traversal;
- temporal filtering;
- ownership resolution;
- candidate path generation;
- evidence ranking;
- contradiction detection;
- context compression;
- token-budget enforcement;
- provenance generation;
- answerability checks.

The LLM performs:

- natural-language interpretation of the evidence;
- explanation;
- prioritization of actions;
- communication of uncertainty.

### 7.2 Intended work split

This is not a fixed mathematical percentage, but it is a useful design target:

```text
70–90% of information work:
  deterministic context layer

10–30% of work:
  LLM synthesis and communication
```

The benchmark must validate this through measurable outcomes:

- fewer input tokens;
- higher relevant-fact recall;
- fewer unsupported claims;
- better citation accuracy;
- stable retrieval latency.

### 7.3 Why this is not just “using more tokens”

PathContext reduces the amount of information the LLM must inspect.

Instead of:

```text
12 chunks
4,000 input tokens
many repeated entities
implicit relationships
```

it aims to produce:

```text
8 connected facts
700–1,000 input tokens
explicit paths
source identifiers
contradiction notes
```

The objective is not maximum retrieval volume. It is maximum relevant fact
density per token.

---

## 8. Core Product Primitive: Minimum Evidence Subgraph

### 8.1 Definition

A minimum evidence subgraph is the smallest connected set of graph entities,
relationships, and supporting properties that satisfies the evidence
requirements of a question.

For example:

```text
Question requirements:
  identify the likely change
  identify the owner
  identify a previous mitigation
```

The system searches for the smallest subgraph containing:

```text
incident
  -> service
  -> deployment
  -> changed file
  -> owner

incident
  -> service
  -> previous incident
  -> mitigation
```

### 8.2 Why this is uncommon

Most retrieval systems rank documents independently.

PathContext ranks connected explanations.

The fundamental unit is not:

```text
document
```

or:

```text
chunk
```

It is:

```text
evidence path
```

### 8.3 Prototype implementation

The prototype does not need a sophisticated graph optimizer. It can use:

1. a small set of traversal recipes;
2. bounded breadth-first or bidirectional traversal;
3. temporal and type constraints;
4. path scoring;
5. token-budget selection.

This is technically feasible while preserving the deeper product concept.

---

## 9. Negative-Space Retrieval

Most retrieval systems only look for supporting evidence. PathContext should
also look for evidence that weakens a conclusion.

For every candidate explanation, run a small counter-check:

```text
Candidate cause:
  deploy-8842

Check:
  Was another deployment closer to the incident?
  Was deploy-8842 rolled back?
  Did the alert begin before the deployment?
  Did the affected service differ from the deployment target?
  Was the same error already present?
```

The result should contain:

```text
supporting evidence
+
contradicting or missing evidence
```

Example:

```text
deploy-8842 is a likely cause, but deploy-8841 was deployed four minutes
earlier and changed the same dependency. The evidence is mixed.
```

This feature provides more value than simply retrieving additional similar
documents because it improves calibration and reduces confident hallucination.

---

## 10. Context Budget as a First-Class Resource

Every request receives a context budget:

```text
Maximum context: 800 tokens
```

The context layer must select facts under that budget.

### 10.1 Fact value model

An approximate ranking function can be:

```text
fact value =
  answer relevance
  × structural confidence
  × source reliability
  ÷ token cost
```

The implementation does not need machine learning. Deterministic scoring is
preferable for the hackathon.

### 10.2 Selection order

1. Include answer-critical facts.
2. Include facts that establish the relationship chain.
3. Include contradictions that affect the conclusion.
4. Include source identifiers and timestamps.
5. Exclude decorative descriptions.
6. Stop when the budget is reached.

### 10.3 Context density

Measure:

```text
context density =
relevant answer facts / input tokens
```

This is one of the most important product metrics.

---

## 11. HydraDB Architecture

```text
Data fixtures or connectors
          |
          v
Python ingestion layer
          |
          v
Self-hosted HydraDB
          |
          v
PathContext retrieval service
  - entity resolution
  - traversal planning
  - evidence selection
  - contradiction checks
  - context compression
          |
          v
AI agent tool call
          |
          v
LLM response
```

### 11.1 HydraDB responsibilities

HydraDB provides:

- graph entity storage;
- directed relationships;
- OpenCypher queries;
- snapshot-consistent reads;
- bounded traversal;
- native path procedures;
- compiled CSC traversal indexes;
- GraphBLAS acceleration where appropriate;
- WAL overlay support for recent topology changes;
- canonical-storage fallback.

### 11.2 Python responsibilities

Python provides:

- ingestion;
- query orchestration;
- traversal recipe selection;
- evidence scoring;
- response formatting;
- agent tool integration;
- evaluation harness;
- demo interface.

### 11.3 Minimal repository layout

```text
pathcontext/
  README.md
  app.py
  hydradb_client.py
  ingest.py
  schema.py
  entity_resolution.py
  traversal_recipes.py
  evidence.py
  context_compiler.py
  agent.py
  vector_baseline.py
  evaluate.py
  fixtures/
    incidents.json
    services.json
    deployments.json
    commits.json
    runbooks.json
  results/
```

---

## 12. Data Model

### 12.1 Generic entity

```text
Entity {
  id,
  type,
  properties,
  source,
  created_at,
  valid_from,
  valid_to
}
```

### 12.2 Generic relationship

```text
Relationship {
  source_id,
  type,
  target_id,
  properties,
  source,
  created_at,
  valid_from,
  valid_to
}
```

### 12.3 Incident demonstration labels

```text
Incident
Alert
Service
Deployment
Commit
File
Team
Runbook
Mitigation
Environment
```

### 12.4 Incident demonstration relationships

```text
Incident -[:TRIGGERED]-> Alert
Incident -[:AFFECTS]-> Service
Alert -[:AFFECTS]-> Service
Service -[:DEPLOYED_AS]-> Deployment
Deployment -[:CONTAINS]-> Commit
Commit -[:TOUCHED]-> File
File -[:OWNED_BY]-> Team
Service -[:HAS_RUNBOOK]-> Runbook
Incident -[:RESOLVED_BY]-> Mitigation
Incident -[:SIMILAR_TO]-> Incident
Deployment -[:DEPLOYED_TO]-> Environment
```

### 12.5 Data-quality principle

Correct relationships are more valuable than large text fields.

A short deployment record with correct service, commit, file, owner, and
timestamp relationships is more useful than a long deployment description with
no reliable links.

---

## 13. Traversal Recipes

The first version should use explicit, tested recipes rather than unrestricted
LLM-generated graph queries.

### 13.1 Change attribution

```text
Incident
  -> AFFECTS
Service
  -> DEPLOYED_AS
Deployment
  -> CONTAINS
Commit
  -> TOUCHED
File
```

Constraints:

- deployment occurred before the incident;
- deployment is within a configurable time window;
- deployment targeted the affected service;
- environment matches where available.

### 13.2 Ownership resolution

```text
Incident
  -> AFFECTS
Service
  -> DEPLOYED_AS
Deployment
  -> CONTAINS
Commit
  -> TOUCHED
File
  -> OWNED_BY
Team
```

### 13.3 Historical precedent

```text
Incident
  -> AFFECTS
Service
<- AFFECTS
PreviousIncident
  -> RESOLVED_BY
Mitigation
```

Constraints:

- previous incident must predate the current incident;
- service must match;
- alert or failure category should match when available;
- mitigation must have a successful outcome.

### 13.4 Runbook resolution

```text
Incident
  -> AFFECTS
Service
  -> HAS_RUNBOOK
Runbook
```

### 13.5 Dependency analysis

This recipe demonstrates domain portability:

```text
Vulnerability
  -> AFFECTS
Library
  <- DEPENDS_ON
Service
  -> OWNED_BY
Team
```

---

## 14. Retrieval Pipeline

```text
Question
  |
  v
Extract known entities and constraints
  |
  v
Classify relationship intent
  |
  v
Select traversal recipe
  |
  v
Pin HydraDB snapshot
  |
  v
Traverse bounded graph paths
  |
  v
Apply temporal, type, and status filters
  |
  v
Generate candidate evidence paths
  |
  v
Search for negative or contradictory evidence
  |
  v
Rank and select minimum evidence subgraph
  |
  v
Hydrate only selected text properties
  |
  v
Compress into evidence packet
  |
  v
Return to agent
```

### 14.1 Entity resolution

The first version can use:

- exact IDs;
- case-normalized names;
- aliases;
- service metadata;
- simple keyword matching;
- optional vector search for unresolved names.

Do not make the entire product dependent on embeddings.

### 14.2 Candidate path scoring

Candidate paths can be ranked using:

```text
score =
  exact_entity_match
  + relationship_type_match
  + temporal_consistency
  + source_reliability
  + independent_source_support
  - hop_count_penalty
  - contradiction_penalty
  - stale_record_penalty
```

### 14.3 Answerability classification

Return one of:

```text
strong
supported
mixed
insufficient
contradictory
```

Do not expose an arbitrary percentage unless it has been calibrated against a
test set.

---

## 15. Agent Interface

### 15.1 Tool definition

```json
{
  "name": "retrieve_structured_context",
  "description": "Retrieve the smallest connected evidence graph relevant to a question.",
  "parameters": {
    "question": "string",
    "seed_entities": [
      {
        "type": "string",
        "id": "string"
      }
    ],
    "context_budget_tokens": "integer"
  }
}
```

### 15.2 Tool response

```json
{
  "context": "Compact evidence summary.",
  "facts": [
    {
      "text": "deploy-8842 affected checkout-api before INC-1042",
      "source": "deployment:deploy-8842",
      "path": [
        "incident:INC-1042",
        "service:checkout-api",
        "deployment:deploy-8842"
      ],
      "confidence": "supported"
    }
  ],
  "contradictions": [],
  "uncertainty": [],
  "retrieval_stats": {
    "nodes_traversed": 17,
    "edges_traversed": 22,
    "input_tokens": 820,
    "latency_ms": 180,
    "read_epoch": 1842
  }
}
```

### 15.3 Agent system instruction

```text
Use retrieve_structured_context for relationship-based questions.

Only state facts supported by returned evidence.
Use source identifiers when making important claims.
Distinguish strong, mixed, and insufficient evidence.
Do not invent a relationship that is not present in the evidence paths.
```

---

## 16. Optional Vector Integration

Vector search can still be useful, but it should be downstream of structure.

### Incorrect architecture

```text
Question
  -> vector search across all documents
  -> retrieve top-k
  -> ask LLM to infer relationships
```

### PathContext architecture

```text
Question
  -> graph traversal
  -> structurally valid candidate entities
  -> vector or keyword ranking within candidates
  -> evidence packet
```

Example:

1. Traverse to previous incidents affecting the same service.
2. Filter to incidents in the same failure category.
3. Use text similarity to rank summaries.
4. Return only mitigations attached to those incidents.

This gives vector search a narrower and more meaningful search space.

---

## 17. Evaluation Strategy

The evaluation must prove that PathContext earns its place over a traditional
vector store.

### 17.1 Systems compared

#### Vector-only baseline

```text
Question
  -> embed question
  -> retrieve top-k chunks
  -> send chunks to LLM
  -> generate answer
```

#### PathContext

```text
Question
  -> resolve entities
  -> traverse HydraDB
  -> select minimum evidence subgraph
  -> hydrate supporting text
  -> send compact evidence to LLM
  -> generate answer
```

### 17.2 Fairness rules

Both systems must use:

- the same corpus;
- the same questions;
- the same LLM;
- the same answer format;
- the same maximum context-token budget;
- the same hardware;
- the same warm/cold cache condition where possible.

### 17.3 Evaluation categories

1. Direct entity lookup.
2. Two-hop relationship reasoning.
3. Multi-hop change attribution.
4. Ownership resolution.
5. Historical mitigation discovery.
6. Contradictory evidence.
7. Missing evidence and negative cases.

### 17.4 Metrics

| Metric | Definition |
|---|---|
| Answer quality | Blind score from 1–5 |
| Relevant-fact recall | Gold evidence facts present in retrieved context |
| Citation accuracy | Source IDs actually support the claims |
| Input tokens | Tokens sent to the LLM |
| Retrieval latency | Context construction time |
| End-to-end latency | Retrieval plus generation |
| Unsupported claims | Claims without supporting facts |
| Context density | Relevant facts per 1,000 input tokens |
| Contradiction detection | Conflicts surfaced rather than hidden |

### 17.5 Success criteria

The prototype succeeds if it demonstrates:

- higher multi-hop relevant-fact recall than vector-only retrieval;
- fewer unsupported claims;
- equal or lower input-token usage;
- explicit inspectable evidence paths;
- predictable bounded latency;
- useful answers when evidence is incomplete.

The system does not need to win every direct lookup. It must win on questions
where relationships are the actual information need.

---

## 18. Demo Dataset

Use a small deterministic dataset so the benchmark is reproducible.

Suggested fixture:

```text
20 incidents
15 services
30 deployments
50 commits and files
10 teams
10 runbooks
20 historical mitigations
30 alerts
5 environments
```

The fixture should include:

- realistic timestamps;
- multiple deployments close together;
- ownership relationships;
- repeated services across incidents;
- one or two contradictory records;
- several unrelated but semantically similar documents;
- at least one question with insufficient evidence.

The dataset should be designed to expose the weakness of vector-only retrieval
without artificially degrading the baseline.

---

## 19. Demonstration Flow

### Step 1: Load the graph

The Python ingestion script writes nodes and relationships to self-hosted
HydraDB.

### Step 2: Ask a relationship-heavy question

```text
Which change caused INC-1042, who owns it, and what worked previously?
```

### Step 3: Run both systems

```text
Vector-only retrieval
PathContext retrieval
```

### Step 4: Display comparison

```text
Vector-only:
  12 chunks
  3,900 tokens
  6 relevant facts
  2 unsupported connections

PathContext:
  8 facts
  820 tokens
  8 relevant facts
  explicit evidence paths
```

The numbers above are illustrative. The demo must display measured values.

### Step 5: Show the graph path

```text
INC-1042
  -> checkout-api
  -> deploy-8842
  -> payment-client.py
  -> Payments Platform
  -> INC-991
  -> disable retry amplification
```

### Step 6: Demonstrate negative evidence

Ask a question where two deployments are plausible. Show that PathContext
returns mixed evidence rather than confidently selecting one without warning.

---

## 20. Functional Requirements

### P0: Required

- Start self-hosted HydraDB locally.
- Ingest deterministic graph fixtures.
- Query HydraDB from Python.
- Implement generic entity and relationship storage.
- Implement at least three traversal recipes.
- Return evidence paths and source identifiers.
- Enforce maximum hops and result limits.
- Expose one agent-callable context tool.
- Implement a vector-only baseline.
- Measure fact recall, tokens, latency, and unsupported claims.

### P1: Important

- Time-window filtering.
- Contradiction detection.
- Context token budget.
- Snapshot/read-epoch reporting.
- Optional vector ranking after graph filtering.
- Simple UI or CLI.
- Reproducible benchmark output.

### P2: Deferred

- Production connectors for every vendor.
- Autonomous remediation.
- Real-time streaming ingestion.
- Arbitrary graph-query generation.
- Multi-tenant permissions.
- Distributed agent coordination.
- Full graph analytics platform.

---

## 21. Non-Functional Requirements

### Correctness

Every returned claim must have at least one source and path.

### Boundedness

Every traversal must have:

- maximum hop count;
- maximum edge scans;
- maximum intermediate vertices;
- maximum result rows;
- maximum runtime;
- maximum context bytes.

### Explainability

The system must expose why each fact was selected.

### Reproducibility

The entire demo must be runnable from a clean environment with documented
commands.

### Failure behavior

When evidence is missing, the system must return an explicit insufficiency
result rather than a success-shaped empty answer.

---

## 22. Business Case

### Customer value

PathContext can help teams:

- reduce incident investigation time;
- reduce agent context costs;
- lower hallucination and unsupported-claim rates;
- preserve operational provenance;
- reuse relationships across multiple agents;
- avoid rebuilding domain-specific retrieval logic.

### Initial distribution

1. Open-source reference implementation.
2. Reproducible HydraDB demo dataset.
3. Benchmark comparing vector and structural retrieval.
4. Agent-tool SDK.
5. Connectors for GitHub, deployments, incident systems, and tickets.

### Monetization

#### Community edition

- Self-hosted HydraDB.
- Basic ingestion.
- Local agent tool.
- Benchmark and demo UI.

#### Enterprise edition

- Managed connectors.
- Access control.
- Audit logs.
- Retention policies.
- Private deployment.
- Evidence and evaluation dashboards.

#### Hosted service

A managed context layer for teams that want agent integration without operating
the graph infrastructure.

---

## 23. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Product looks like generic GraphRAG | Define and demonstrate minimum evidence subgraphs |
| Graph ingestion becomes too large | Use deterministic fixtures and a narrow schema |
| Entity resolution is unreliable | Start with explicit IDs, aliases, and simple normalization |
| LLM-generated graph queries are unpredictable | Use tested traversal recipes |
| Vector baseline is unfairly weak | Same corpus, model, questions, and token budget |
| HydraDB setup consumes the demo | Validate one local write/read path first |
| Graph retrieves too much | Enforce hop, edge, result, and token limits |
| Agent still hallucinates | Require source IDs and unsupported-claim evaluation |
| Confidence score is misleading | Use qualitative evidence states until calibrated |
| Graph does not win every question | Position product around multi-hop relationship questions |

---

## 24. Delivery Milestones

### Milestone A: Structural memory

Deliver:

- HydraDB running locally;
- graph schema;
- Python ingestion;
- representative entities and relationships;
- one successful multi-hop query.

Exit condition:

```text
The system can retrieve a correct connected path from a seed entity.
```

### Milestone B: Context compiler

Deliver:

- entity resolution;
- traversal recipes;
- path scoring;
- minimum evidence subgraph selection;
- evidence packet generation.

Exit condition:

```text
The system can answer a relationship-heavy question without sending
the full neighborhood to the LLM.
```

### Milestone C: Agent tool

Deliver:

- structured tool interface;
- context budget;
- provenance;
- uncertainty and contradiction handling;
- LLM integration.

Exit condition:

```text
The agent produces an answer whose claims can be traced to returned paths.
```

### Milestone D: Proof of differentiation

Deliver:

- vector-only baseline;
- common evaluation set;
- token, latency, recall, and quality measurements;
- side-by-side demonstration.

Exit condition:

```text
The result demonstrates measurable value over vector-only retrieval on
multi-hop questions.
```

---

## 25. Final Product Positioning

### Short pitch

> PathContext is the structural memory layer for AI agents. It traverses
> relationships first, retrieves text second, and gives agents only the
> connected evidence required to reason.

### Stronger technical statement

> PathContext compiles an agent question into a bounded minimum evidence
> subgraph, validates supporting and contradicting paths, and emits a
> provenance-preserving context packet under a strict token budget.

### Final product model

```text
Traditional RAG:
  retrieve more text
    -> spend more tokens
    -> ask the model to connect it

PathContext:
  traverse structure
    -> validate relevance
    -> check contradictions
    -> compress evidence
    -> spend tokens only on reasoning
```

The core innovation is not merely storing data in a graph. It is moving
relationship discovery, evidence selection, and context compression out of the
LLM and into a deterministic, inspectable context compiler powered by HydraDB.

### 25.1 Live integration acceptance

The implementation is considered integrated only when a running HydraDB node
passes all of the following checks:

- the HTTP query endpoint returns a successful authenticated response;
- fixture ingestion is idempotent and preserves stable external identifiers;
- change attribution, historical mitigation, and runbook recipes execute as
  OpenCypher inside HydraDB;
- each recipe returns a connected result with source identifiers;
- the response includes HydraDB `read_epoch` or `bookmark` telemetry;
- the rows are converted into the same bounded evidence-packet contract used
  by the local compiler.

HydraDB reserves integer `id` as its vertex identity. PathContext therefore
stores domain identifiers such as `INC-1042` in `external_id` and maps them to
stable integer IDs at ingestion. This preserves domain readability without
violating HydraDB's query execution contract.

The live path is deliberately separate from the in-memory control:

```text
HydraDB:
  OpenCypher traversal, snapshot/read epoch, connected rows

Python:
  recipe selection, response decoding, token-budget selection,
  provenance packet formatting
```

Raw live results and local-control results must not be mixed in one benchmark
series.

### 25.2 Hackathon readiness gate

The hackathon submission is ready when the following command completes on a
fresh local HydraDB graph:

```bash
export PATHCONTEXT_HYDRADB_TOKEN='...'
python3 run_demo.py --repetitions 20 --output results/hackathon_report.json
```

The report must contain:

- offline baseline and plain-store comparisons;
- continual-ingestion acceptance;
- live HydraDB status `passed`;
- at least one live evidence packet;
- a non-null HydraDB read epoch/bookmark;
- source-backed facts for change, ownership, and historical mitigation.

This is a hackathon-ready reference implementation, not a production service.
It deliberately does not claim arbitrary natural-language-to-Cypher generation,
multi-tenant authorization, streaming ingestion, calibrated confidence, or
LLM answer generation. Those are integration and production-hardening work
outside the demonstrated structural context primitive.

### 25.3 Demonstration interface

The reference demo includes a terminal interface with a distinct PathContext
palette and a Claude-Code-inspired interaction model. It supports:

- `/ask` for evidence-backed questions;
- `/query` for explicitly inspecting HydraDB with OpenCypher;
- `/mode live|local` for switching between the live database and deterministic
  control;
- visible evidence paths, uncertainty, answerability, and retrieval telemetry.

Optional synthesis is provider-neutral. Groq's OpenAI-compatible API is
preferred when `GROQ_API_KEY` is configured; a local OpenCode CLI is the
fallback. Both receive only the bounded evidence packet. Neither provider is
allowed to discover relationships or generate unrestricted database queries.
When no provider is configured, the TUI remains fully useful as a deterministic
evidence console.

---

## 26. Measurement Contract: Proving the Graph Does Real Work

The demo must not claim that a graph is better because of a single attractive
answer. Every benchmark report must separate the following questions:

1. **Answer quality:** Does PathContext retrieve the gold evidence facts?
2. **Baseline improvement:** Does it beat a declared non-graph baseline on the
   same questions, corpus, token budget, and repeated seeds?
3. **Structural work:** Does indexed graph adjacency avoid work performed by a
   plain record store while preserving quality?
4. **Continual ingestion:** Does a newly ingested batch become retrievable
   without rebuilding application code or silently using future data?

### 26.1 Declared baseline

The initial baseline is a top-k lexical record retriever. It tokenizes the
question, ranks independent entity records by token overlap, and returns those
records without joining relationships. It is intentionally transparent and
repeatable; it is not a straw-man vector score or an LLM-generated answer.
Both systems use the same fixture, questions, maximum context budget, and
evaluation gold labels.

Required metrics:

- relevant-fact recall;
- citation accuracy (every returned fact has a supporting source and path);
- unsupported-claim rate;
- input tokens;
- retrieval latency p50 and p95.

The benchmark must report means, p50, and p95 across at least 10 repeated
question-order seeds. A result is a genuine improvement only when the
multi-hop recall delta is positive across the declared repeated run, not just
in a hand-picked output.

### 26.2 Graph-versus-plain-store control

To establish that graph structure is doing work, the same compiler and records
must also run through an unindexed plain record store. The control scans all
relationships for each lookup; the indexed graph uses adjacency maps (and, in
production, HydraDB's property and traversal indexes). The report must show:

- equal gold recall between graph and plain control;
- edge scans or equivalent database work;
- graph work reduction relative to the plain control;
- latency only as a secondary metric on small fixtures.

If the graph does not reduce structural work as the fixture grows, the product
must not claim that HydraDB is providing material value.

The local indexed store is a deterministic control for algorithmic work; it is
not a substitute for a live HydraDB measurement. A HydraDB run must additionally
record HTTP query count, read epoch/bookmark, query latency, result limits, and
whether the query used the intended indexed/traversal path. Reports must label
local-control results and live-HydraDB results separately.

### 26.3 Continual ingestion protocol

“Continual learning” means continual, versioned graph ingestion in this
prototype, not an unsupported claim that the system trains an ML model. Each
round records:

- the graph data version and ingestion batch;
- questions available before the batch;
- questions introduced after the batch;
- evidence visible at each read epoch;
- recall and citation metrics before and after ingestion.

The acceptance test adds a new incident chain after the first round. The new
chain must be absent before ingestion and fully retrievable after ingestion.
HydraDB deployments must report the read epoch/bookmark used for each round so
future data cannot leak into an earlier evaluation.

### 26.4 Scale and failure thresholds

The benchmark must include graph-size scaling, at least by adding unrelated
records and relationships. Report edge scans and p95 latency at each size.
Every query remains bounded by maximum hops, edges, paths, runtime, and context
tokens. Missing or contradictory evidence remains an explicit result.

The implementation must publish raw JSON results alongside any chart. A
successful demo without these raw measurements is not evidence of product
differentiation.
