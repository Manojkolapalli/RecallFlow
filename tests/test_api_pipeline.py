import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
import requests
from qdrant_client import models

from recallflow import api
from recallflow.config import Settings
from recallflow.lyzr import LyzrClient, LyzrError
from recallflow.memory import EMBEDDING_SIZE, RetrievedChunk, TranscriptMemory
from scripts.test_api_e2e import safe_api_error_detail


class FakeVector(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class FakeTextEmbedding:
    instances: list["FakeTextEmbedding"] = []

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.documents: list[str] = []
        self.queries: list[str] = []
        self.instances.append(self)

    def embed(self, documents: list[str]) -> list[FakeVector]:
        self.documents.extend(documents)
        return [
            FakeVector(float(index) for index in range(EMBEDDING_SIZE))
            for _ in documents
        ]

    def query_embed(self, query: str) -> list[FakeVector]:
        self.queries.append(query)
        return [FakeVector(float(index) for index in range(EMBEDDING_SIZE))]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.points: dict[str, SimpleNamespace] = {}
        self.collection_name: str | None = None
        self.queries: list[str] = []
        self.query_vectors: list[list[float]] = []
        self.collection_dimension: int | None = None
        self.collection_distance: models.Distance | None = None

    def create_collection(
        self,
        collection_name: str,
        vectors_config: models.VectorParams,
    ) -> None:
        if self.collection_name not in (None, collection_name):
            raise AssertionError("Test attempted to write to multiple collections.")
        self.collection_name = collection_name
        self.collection_dimension = vectors_config.size
        self.collection_distance = vectors_config.distance

    def get_collection(self, collection_name: str) -> SimpleNamespace:
        if collection_name != self.collection_name:
            raise AssertionError("Test attempted to inspect an unexpected collection.")
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=SimpleNamespace(size=self.collection_dimension)
                )
            )
        )

    def upsert(
        self,
        collection_name: str,
        points: list[models.PointStruct],
        wait: bool,
    ) -> None:
        if collection_name != self.collection_name:
            raise AssertionError("Test attempted to write to an unexpected collection.")
        if not wait:
            raise AssertionError("Qdrant writes must wait for acknowledgement.")
        for point in points:
            self.points[str(point.id)] = SimpleNamespace(
                payload=point.payload,
                vector=point.vector,
                score=0.9,
            )

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name == self.collection_name and bool(self.points)

    def query_points(
        self,
        collection_name: str,
        query: list[float],
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ) -> SimpleNamespace:
        if collection_name != self.collection_name:
            raise AssertionError("Test attempted to query an unexpected collection.")
        if not with_payload or with_vectors:
            raise AssertionError("Search must return payloads without stored vectors.")
        self.queries.append("embedded-query")
        self.query_vectors.append(query)
        return SimpleNamespace(points=list(self.points.values())[:limit])


def configured_settings() -> Settings:
    return Settings(
        lyzr_api_key="test-key",
        lyzr_agent_id="test-agent",
        lyzr_base_url="https://example.invalid/v3",
        qdrant_url="",
        qdrant_api_key="",
        qdrant_collection="test-transcripts",
        qdrant_local_path=Path(".qdrant-test"),
        omi_webhook_token="",
    )


class ApiPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_qdrant = FakeQdrantClient()
        FakeTextEmbedding.instances.clear()
        self.qdrant_patch = patch(
            "recallflow.memory.QdrantClient",
            return_value=self.fake_qdrant,
        )
        self.embedding_patch = patch(
            "recallflow.memory.TextEmbedding",
            FakeTextEmbedding,
        )
        self.qdrant_patch.start()
        self.embedding_patch.start()
        self.addCleanup(self.qdrant_patch.stop)
        self.addCleanup(self.embedding_patch.stop)
        self.memory = TranscriptMemory(
            collection="test-transcripts",
            local_path=Path(".qdrant-test"),
        )
        self.lyzr = LyzrClient(configured_settings())
        self.memory_patch = patch.object(api, "get_memory", return_value=self.memory)
        self.lyzr_patch = patch.object(api, "lyzr", self.lyzr)
        self.memory_patch.start()
        self.lyzr_patch.start()
        self.addCleanup(self.memory_patch.stop)
        self.addCleanup(self.lyzr_patch.stop)

    def test_transcript_ingestion_retrieval_and_answer_use_retrieved_context(self) -> None:
        with patch.object(
            self.lyzr,
            "_chat",
            side_effect=[
                '{"summary":"Launch planned","decisions":[],"action_items":[]}',
                "The launch is planned for June [1].",
            ],
        ) as chat:
            result = api.create_transcript(
                api.TranscriptRequest(
                    title="Launch planning",
                    transcript="The team decided to launch in June.",
                )
            )
            response = api.ask_question(
                api.QuestionRequest(question="When is the launch?")
            )

        self.assertEqual(result["stored_chunks"], 1)
        self.assertEqual(
            set(result),
            {"source_id", "stored_chunks", "analysis"},
        )
        self.assertEqual(
            set(result["analysis"]),
            {
                "summary",
                "decisions",
                "action_items",
                "key_dates",
                "open_questions",
                "analysis_mode",
            },
        )
        self.assertEqual(result["analysis"]["analysis_mode"], "lyzr")
        self.assertEqual(response["answer"], "The launch is planned for June [1].")
        self.assertEqual(len(response["sources"]), 1)
        self.assertEqual(response["sources"][0]["title"], "Launch planning")
        self.assertIn(
            result["source_id"],
            {point.payload["source_id"] for point in self.fake_qdrant.points.values()},
        )
        self.assertEqual(self.fake_qdrant.queries, ["embedded-query"])
        self.assertEqual(len(self.fake_qdrant.query_vectors[0]), EMBEDDING_SIZE)
        self.assertEqual(self.fake_qdrant.collection_distance, models.Distance.COSINE)
        self.assertEqual(
            FakeTextEmbedding.instances[0].documents,
            ["The team decided to launch in June."],
        )
        self.assertEqual(
            FakeTextEmbedding.instances[0].queries,
            ["When is the launch?"],
        )
        answer_prompt = chat.call_args_list[1].args[0]
        self.assertIn("The team decided to launch in June.", answer_prompt)
        self.assertIn("When is the launch?", answer_prompt)

    def test_retrieved_chunks_preserve_source_ids_and_titles(self) -> None:
        self.memory.ingest("Planning A", "Unique note alpha.", "source-alpha")
        self.memory.ingest("Planning B", "Unique note beta.", "source-beta")

        results = self.memory.search("unique note", limit=5)

        self.assertEqual(
            {
                (result.source_id, result.title)
                for result in results
            },
            {("source-alpha", "Planning A"), ("source-beta", "Planning B")},
        )
        self.assertTrue(all(result.text for result in results))
        self.assertEqual(self.fake_qdrant.collection_dimension, EMBEDDING_SIZE)
        self.assertEqual(
            {result.reference for result in results},
            {"chunk 1"},
        )

    def test_answer_rejects_citations_outside_retrieved_sources(self) -> None:
        source = [
            RetrievedChunk(
                title="Planning A",
                reference="chunk 1",
                text="The launch is in June.",
                score=0.9,
            )
        ]
        with patch.object(
            self.lyzr,
            "_chat",
            return_value="The launch is in June [2].",
        ):
            with self.assertRaises(LyzrError):
                self.lyzr.answer("When is the launch?", source)

    def test_empty_transcript_returns_422_without_ingestion(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api.create_transcript(api.TranscriptRequest(transcript="  "))

        self.assertEqual(raised.exception.status_code, 422)
        self.assertFalse(self.fake_qdrant.points)

    def test_empty_title_returns_422_without_ingestion(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api.create_transcript(
                api.TranscriptRequest(title="  ", transcript="A valid transcript.")
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertFalse(self.fake_qdrant.points)

    def test_empty_question_returns_422_without_search(self) -> None:
        with patch.object(self.memory, "search") as search:
            with self.assertRaises(HTTPException) as raised:
                api.ask_question(api.QuestionRequest(question="  "))

        self.assertEqual(raised.exception.status_code, 422)
        search.assert_not_called()

    def test_missing_lyzr_configuration_uses_local_transcript_analysis(self) -> None:
        self.lyzr.settings = Settings(
            lyzr_api_key="",
            lyzr_agent_id="",
            lyzr_base_url="https://example.invalid/v3",
            qdrant_url="",
            qdrant_api_key="",
            qdrant_collection="test-transcripts",
            qdrant_local_path=Path(".qdrant-test"),
            omi_webhook_token="",
        )

        result = api.create_transcript(
            api.TranscriptRequest(transcript="Saved before analysis.")
        )
        self.assertIn("Local fallback", result["analysis"]["summary"])
        self.assertEqual(
            result["analysis"]["decisions"],
            ["No confirmed decisions."],
        )
        self.assertEqual(result["analysis"]["action_items"], [])
        self.assertTrue(self.fake_qdrant.points)

    def test_missing_lyzr_configuration_uses_local_answer_after_retrieval(self) -> None:
        self.memory.ingest("Planning", "The launch is in June.", "source-alpha")
        self.lyzr.settings = Settings(
            lyzr_api_key="",
            lyzr_agent_id="",
            lyzr_base_url="https://example.invalid/v3",
            qdrant_url="",
            qdrant_api_key="",
            qdrant_collection="test-transcripts",
            qdrant_local_path=Path(".qdrant-test"),
            omi_webhook_token="",
        )

        result = api.ask_question(api.QuestionRequest(question="When?"))

        self.assertIn("Local fallback", result["answer"])
        self.assertIn("The launch is in June.", result["answer"])
        self.assertIn("[1]", result["answer"])
        self.assertIn(
            "does not provide enough information to determine it",
            result["answer"],
        )
        self.assertEqual(result["sources"][0]["source_id"], "source-alpha")

    def test_lyzr_analysis_failure_returns_502_after_storage(self) -> None:
        with patch.object(
            self.lyzr,
            "analyze",
            side_effect=LyzrError(
                "upstream error body must not be returned",
                failure_type="HTTPError",
                upstream_status_code=401,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                api.create_transcript(
                    api.TranscriptRequest(transcript="Store this first.")
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.detail,
            "Transcript was stored in Qdrant, but Lyzr analysis failed "
            "(HTTPError, upstream HTTP 401).",
        )
        self.assertTrue(self.fake_qdrant.points)

    def test_lyzr_http_error_keeps_safe_upstream_status(self) -> None:
        upstream_response = requests.Response()
        upstream_response.status_code = 429
        with patch("recallflow.lyzr.requests.post", return_value=upstream_response):
            with self.assertRaises(LyzrError) as raised:
                self.lyzr._chat("test prompt", "test-session")

        self.assertEqual(raised.exception.failure_type, "HTTPError")
        self.assertEqual(raised.exception.upstream_status_code, 429)
        self.assertEqual(
            raised.exception.diagnostic,
            "HTTPError, upstream HTTP 429",
        )

    def test_lyzr_v2_chat_endpoint_and_payload(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"response": "Analysis complete."}
        ).encode()

        with patch("recallflow.lyzr.requests.post", return_value=response) as post:
            result = self.lyzr._chat("Analyze this transcript.", "analysis-source-1")

        self.assertEqual(result, "Analysis complete.")
        post.assert_called_once_with(
            "https://agent.api.lyzr.app/v2/chat/",
            headers={
                "x-api-key": "test-key",
                "Content-Type": "application/json",
            },
            json={
                "user_id": "recallflow",
                "agent_id": "test-agent",
                "session_id": "analysis-source-1",
                "message": "Analyze this transcript.",
            },
            timeout=60,
        )

    def test_e2e_script_only_displays_allowlisted_api_diagnostics(self) -> None:
        safe_response = requests.Response()
        safe_response.status_code = 502
        safe_response._content = json.dumps({
            "detail": "Transcript was stored in Qdrant, but Lyzr analysis failed "
            "(HTTPError, upstream HTTP 401)."
        }).encode()
        unsafe_response = requests.Response()
        unsafe_response.status_code = 502
        unsafe_response._content = json.dumps({
            "detail": "Request failed: secret=do-not-print and transcript content."
        }).encode()

        self.assertEqual(
            safe_api_error_detail(safe_response),
            "Transcript was stored in Qdrant, but Lyzr analysis failed "
            "(HTTPError, upstream HTTP 401).",
        )
        self.assertIsNone(safe_api_error_detail(unsafe_response))

    def test_lyzr_answer_failure_returns_502(self) -> None:
        self.memory.ingest("Planning", "The launch is in June.", "source-alpha")
        with patch.object(self.lyzr, "answer", side_effect=LyzrError("service failed")):
            with self.assertRaises(HTTPException) as raised:
                api.ask_question(api.QuestionRequest(question="When?"))

        self.assertEqual(raised.exception.status_code, 502)

    def test_missing_qdrant_embedding_support_returns_503(self) -> None:
        with patch.object(
            api,
            "get_memory",
            side_effect=ImportError("embedding backend unavailable"),
        ):
            with self.assertRaises(HTTPException) as raised:
                api.create_transcript(
                    api.TranscriptRequest(transcript="Cannot store this.")
                )

        self.assertEqual(raised.exception.status_code, 503)

    def test_qdrant_storage_service_failure_returns_503(self) -> None:
        with patch.object(api, "get_memory") as get_memory:
            get_memory.return_value.ingest.side_effect = RuntimeError("Qdrant unavailable")
            with self.assertRaises(HTTPException) as raised:
                api.create_transcript(
                    api.TranscriptRequest(transcript="Store this transcript.")
                )

        self.assertEqual(raised.exception.status_code, 503)

    def test_qdrant_search_service_failure_returns_503(self) -> None:
        with patch.object(api, "get_memory") as get_memory:
            get_memory.return_value.search.side_effect = RuntimeError("Qdrant unavailable")
            with self.assertRaises(HTTPException) as raised:
                api.ask_question(api.QuestionRequest(question="What happened?"))

        self.assertEqual(raised.exception.status_code, 503)

    def test_lyzr_timeout_is_reported_without_a_network_call(self) -> None:
        with patch(
            "recallflow.lyzr.requests.post",
            side_effect=requests.Timeout("simulated timeout"),
        ):
            with self.assertRaisesRegex(LyzrError, "60-second timeout"):
                self.lyzr._chat("test prompt", "test-session")

    def test_lyzr_connection_error_preserves_safe_cause_chain(self) -> None:
        root_cause = OSError("simulated socket failure")
        connection_error = requests.ConnectionError("simulated connection failure")
        connection_error.__cause__ = root_cause
        with patch(
            "recallflow.lyzr.requests.post",
            side_effect=connection_error,
        ):
            with self.assertRaises(LyzrError) as raised:
                self.lyzr._chat("test prompt", "test-session")

        self.assertTrue(raised.exception.availability_failure)
        self.assertIs(raised.exception.__cause__, connection_error)
        self.assertIs(connection_error.__cause__, root_cause)

    def test_connection_failure_uses_local_fallback_for_both_endpoints(self) -> None:
        transcript = "The prototype codename is ORCHID-7419."
        with patch(
            "recallflow.lyzr.requests.post",
            side_effect=requests.ConnectionError("simulated connection failure"),
        ) as post:
            result = api.create_transcript(
                api.TranscriptRequest(title="Prototype review", transcript=transcript)
            )
            question_result = api.ask_question(
                api.QuestionRequest(question="What is the prototype codename?")
            )

        self.assertIn("Local fallback", result["analysis"]["summary"])
        self.assertNotIn(transcript, result["analysis"]["summary"])
        self.assertEqual(
            result["analysis"]["decisions"],
            ["No confirmed decisions."],
        )
        self.assertEqual(result["analysis"]["action_items"], [])
        self.assertIn("Local fallback", question_result["answer"])
        self.assertIn(transcript, question_result["answer"])
        self.assertIn("[1]", question_result["answer"])
        self.assertEqual(
            question_result["sources"][0]["source_id"],
            result["source_id"],
        )
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
