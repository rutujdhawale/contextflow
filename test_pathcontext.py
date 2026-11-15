import json
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluate import _quality
from ingest import ingest_fixture, load_fixture
from multimodal_pipeline import Artifact, statements
from pathcontext.agent import retrieve_structured_context
from pathcontext.context_compiler import ContextCompiler
from pathcontext.entity_resolution import resolve_entity_states
from pathcontext.graph import GraphStore
from pathcontext.hydradb_client import HydraDBClient
from pathcontext.hydradb_retriever import HydraDBContextCompiler
from pathcontext.llm import GroqProvider, LLMAnswer, LLMError, OpenCodeProvider, synthesize
from pathcontext.plain_store import PlainStore
from pathcontext.schema import Entity


FIXTURE = Path(__file__).parent / "fixtures" / "incidents.json"


class ContextCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = ContextCompiler(load_fixture(FIXTURE))

    def test_compiles_connected_change_owner_and_history(self) -> None:
        packet = self.compiler.compile(
            "Which change caused INC-1042, who owns it, and what worked previously?"
        )
        self.assertEqual(packet.answerability, "supported")
        self.assertGreaterEqual(len(packet.facts), 3)
        self.assertTrue(any("deploy-8842" in fact.text for fact in packet.facts))
        self.assertTrue(any("Payments-Platform" in fact.text for fact in packet.facts))
        self.assertTrue(any("INC-991" in fact.text for fact in packet.facts))
        for fact in packet.facts:
            self.assertTrue(fact.source)
            self.assertTrue(fact.path)

    def test_budget_is_enforced(self) -> None:
        packet = self.compiler.compile("What happened in INC-1042?", context_budget_tokens=5)
        self.assertLessEqual(packet.retrieval_stats["input_tokens"], 5)

    def test_tool_returns_json_serializable_shape(self) -> None:
        result = retrieve_structured_context(
            self.compiler, question="What happened in INC-1042?"
        )
        json.dumps(result)
        self.assertIn("retrieval_stats", result)

    def test_missing_seed_is_explicit(self) -> None:
        packet = self.compiler.compile("What happened in INC-9999?")
        self.assertEqual(packet.answerability, "insufficient")
        self.assertTrue(packet.uncertainty)

    def test_entity_resolution_reports_ambiguity(self) -> None:
        graph = GraphStore(
            entities=[
                Entity("checkout-api", "Service", {"aliases": ["checkout"]}),
                Entity("checkout-worker", "Service", {"aliases": ["checkout"]}),
            ],
            relationships=[],
        )
        resolved, states = resolve_entity_states("Investigate checkout", graph)
        self.assertEqual(resolved, [])
        self.assertEqual(states[0]["state"], "ambiguous")

    def test_required_evidence_is_tracked(self) -> None:
        packet = self.compiler.compile(
            "Which change caused INC-1042, who owns it, and what worked previously?"
        )
        self.assertEqual(
            packet.required_evidence, ("change", "owner", "history")
        )
        self.assertEqual(packet.missing_evidence, ())
        self.assertEqual(packet.answerability, "supported")

    def test_indexed_graph_does_less_structural_work_than_plain_store(self) -> None:
        graph = load_fixture(FIXTURE)
        indexed = ContextCompiler(graph).compile("What happened in INC-1042?")
        plain = ContextCompiler(
            PlainStore(list(graph.entities.values()), graph.relationships)
        ).compile("What happened in INC-1042?")
        self.assertEqual(
            _quality(indexed, {"Deployment:deploy-8842"})["relevant_fact_recall"],
            _quality(plain, {"Deployment:deploy-8842"})["relevant_fact_recall"],
        )
        self.assertLess(
            indexed.retrieval_stats["edge_scans"],
            plain.retrieval_stats["edge_scans"],
        )

    def test_hydradb_client_uses_bearer_auth(self) -> None:
        client = HydraDBClient(token="local-development-token-32-bytes")
        request = client._request("MATCH (n:Incident) RETURN n.id AS id")
        self.assertEqual(
            request.headers["Authorization"],
            "Bearer local-development-token-32-bytes",
        )

    def test_hydradb_ingest_uses_unwind_batches(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.queries = []

            def query(self, query, parameters=None):
                self.queries.append((query, parameters))
                return {"rows": [], "read_epoch": 1}

        client = FakeClient()
        executed = ingest_fixture(client, FIXTURE)
        self.assertGreater(executed, 0)
        edge_queries = [
            query for query, _ in client.queries if "UNWIND $rows" in query
        ]
        self.assertTrue(edge_queries)
        self.assertTrue(any("CREATE (a {id: row.src})" in query for query in edge_queries))
        vertex_queries = [
            query for query, _ in client.queries if "MERGE (n {id: row.vertex})" in query
        ]
        self.assertTrue(vertex_queries)
        self.assertTrue(all("n +=" not in query for query in vertex_queries))
        self.assertTrue(any("n.occurred_at = row.occurred_at" in query for query in vertex_queries))

    def test_hydradb_rows_compile_to_evidence_packet(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.queries = []

            def query(self, query):
                self.queries.append(query)
                return {
                    "columns": ["incident", "deployment"],
                    "rows": [[
                        {"type": "string", "value": "INC-1042"},
                        {"type": "string", "value": "deploy-8842"},
                    ]],
                    "read_epoch": 12,
                    "bookmark": "bookmark",
                }

            def telemetry(self):
                return {"backend": "hydradb_http", "query_count": len(self.queries)}

        packet = HydraDBContextCompiler(FakeClient()).compile(
            "Which change caused INC-1042?"
        )
        self.assertEqual(packet.answerability, "supported")
        self.assertEqual(packet.facts[0].source, "hydradb:change")
        self.assertIn("deploy-8842", packet.context)

    def test_hydradb_packet_marks_mixed_epochs_non_atomic(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.queries = []

            def query(self, query):
                self.queries.append(query)
                epoch = len(self.queries)
                return {
                    "columns": ["incident", "deployment"],
                    "rows": [[
                        {"type": "string", "value": "INC-1042"},
                        {"type": "string", "value": "deploy-8842"},
                    ]],
                    "read_epoch": epoch,
                }

            def telemetry(self):
                return {"backend": "hydradb_http", "query_count": len(self.queries)}

        packet = HydraDBContextCompiler(FakeClient()).compile(
            "What change caused INC-1042 and what worked previously?"
        )
        self.assertEqual(packet.answerability, "mixed")
        self.assertEqual(packet.retrieval_stats["snapshot_consistency"], "non_atomic")
        self.assertTrue(any("non-atomic" in item for item in packet.uncertainty))

    def test_hydradb_recipe_is_not_hardcoded_to_one_incident(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.query_text = ""

            def query(self, query):
                self.query_text = query
                return {"columns": [], "rows": [], "read_epoch": 1}

            def telemetry(self):
                return {"backend": "hydradb_http", "query_count": 1}

        client = FakeClient()
        packet = HydraDBContextCompiler(client).compile("What caused INC-2048?")
        self.assertEqual(packet.answerability, "insufficient")
        self.assertIn("INC-2048", client.query_text)

    def test_hydradb_runbook_question_can_start_from_service(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.query_text = ""

            def query(self, query):
                self.query_text = query
                return {
                    "columns": ["service", "runbook"],
                    "rows": [["checkout-api", "runbook-checkout"]],
                    "read_epoch": 1,
                }

            def telemetry(self):
                return {"backend": "hydradb_http", "query_count": 1}

        client = FakeClient()
        packet = HydraDBContextCompiler(client).compile(
            "What runbook should be used for checkout-api?"
        )
        self.assertEqual(packet.answerability, "supported")
        self.assertIn("checkout-api", client.query_text)
        self.assertIn("runbook-checkout", packet.context)

    def test_hydradb_runbook_intent_handles_implicit_wording(self) -> None:
        class FakeClient:
            def query(self, query):
                return {
                    "columns": ["service", "runbook"],
                    "rows": [["checkout-api", "runbook-checkout"]],
                    "read_epoch": 1,
                }

            def telemetry(self):
                return {"backend": "hydradb_http", "query_count": 1}

        packet = HydraDBContextCompiler(FakeClient()).compile(
            "What should used for checkout-api?"
        )
        self.assertEqual(packet.answerability, "supported")
        self.assertIn("runbook-checkout", packet.context)
        self.assertEqual(packet.facts[0].source, "hydradb:runbook")

    def test_groq_request_uses_bearer_auth_and_parses_answer(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {"choices": [{"message": {"content": "deploy-8842 [hydradb:change]"}}]}
                ).encode()

        with patch("pathcontext.llm.urlopen", return_value=FakeResponse()) as urlopen:
            answer = GroqProvider("groq-test-key").answer(
                "What changed?", self.compiler.compile("INC-1042")
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer groq-test-key")
        self.assertEqual(answer, LLMAnswer("groq", "deploy-8842 [hydradb:change]"))

    def test_multimodal_statements_preserve_artifact_kind_and_locator(self) -> None:
        generated = statements(
            Path("diagram.png"),
            [
                Artifact(
                    kind="image",
                    source="diagram.png",
                    locator="image",
                    text='{"mime_type":"image/png"}',
                    summary="A line chart rises from Q1 to Q4.",
                    raw_bytes=128,
                )
            ],
        )
        self.assertTrue(any("a.kind = 'image'" in statement for statement in generated))
        self.assertTrue(any("a.locator = 'image'" in statement for statement in generated))
        self.assertTrue(any("HAS_ARTIFACT" in statement for statement in generated))

    def test_groq_failure_falls_back_to_opencode(self) -> None:
        with patch.object(
            GroqProvider, "answer", side_effect=LLMError("temporary provider failure")
        ), patch.object(
            OpenCodeProvider, "answer", return_value=LLMAnswer("opencode", "fallback")
        ) as fallback:
            answer = synthesize(
                "What changed?",
                self.compiler.compile("INC-1042"),
                groq_api_key="groq-test-key",
            )
        fallback.assert_called_once()
        self.assertEqual(answer, LLMAnswer("opencode", "fallback"))

    def test_opencode_empty_output_is_rejected(self) -> None:
        class Result:
            returncode = 0
            stdout = " "
            stderr = ""

        with patch("pathcontext.llm.subprocess.run", return_value=Result()):
            with self.assertRaises(LLMError):
                OpenCodeProvider("echo").answer(
                    "question", self.compiler.compile("INC-1042")
                )


if __name__ == "__main__":
    unittest.main()
