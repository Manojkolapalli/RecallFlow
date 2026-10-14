import unittest
from pathlib import Path

from recallflow.config import Settings
from recallflow.lyzr import LyzrClient, LyzrError
from recallflow.memory import split_text
from recallflow.omi import OmiPayloadError, transcript_chunks


def test_settings() -> Settings:
    return Settings(
        lyzr_api_key="",
        lyzr_agent_id="",
        lyzr_base_url="https://example.invalid/v3",
        qdrant_url="",
        qdrant_api_key="",
        qdrant_collection="recallflow_transcripts",
        qdrant_local_path=Path(".qdrant_data"),
        omi_webhook_token="",
    )


class PipelineHelperTests(unittest.TestCase):
    def test_split_text_respects_maximum_and_preserves_words(self) -> None:
        chunks = split_text("one two three four", max_chars=8)

        self.assertEqual(chunks, ["one two", "three", "four"])
        self.assertTrue(all(len(chunk) <= 8 for chunk in chunks))

    def test_completed_omi_memory_preserves_source_references(self) -> None:
        chunks = transcript_chunks(
            {
                "id": "memory-123",
                "structured": {"title": "Planning"},
                "transcript_segments": [
                    {"text": "Choose the launch date.", "speaker_name": "Sam", "start": 12.0}
                ],
            }
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].title, "Planning")
        self.assertEqual(chunks[0].source_id, "omi:memory-123")
        self.assertEqual(chunks[0].reference, "Sam, 12.0s")

    def test_realtime_omi_requires_session_id(self) -> None:
        with self.assertRaises(OmiPayloadError):
            transcript_chunks([{"text": "Hello"}])

    def test_analysis_parser_extracts_actions_and_deadlines(self) -> None:
        analysis = LyzrClient._parse_analysis(
            """```json
            {"summary":"Plan set","decisions":["Ship in June"],
             "action_items":[{"task":"Send plan","owner":"Ari","deadline":"Friday"}]}
            ```"""
        )

        self.assertEqual(analysis.summary, "Plan set")
        self.assertEqual(analysis.decisions, ["Ship in June"])
        self.assertEqual(analysis.action_items[0].deadline, "Friday")

    def test_analysis_parser_rejects_invalid_schema(self) -> None:
        with self.assertRaises(LyzrError):
            LyzrClient._parse_analysis(
                '{"summary":"Plan set","decisions":[],"action_items":[{"task":"Send plan"}]}'
            )

    def test_local_kickoff_analysis_extracts_notes_without_inventing_details(self) -> None:
        transcript = """Alex: Welcome to the project kickoff. Our goal is to finish the first prototype by October 20.

Priya: I'll handle the frontend and prepare the initial screens by October 17.

Rahul: I'll develop the backend API and aim to finish the first version by October 18.

Alex: We'll review the prototype together on October 21 at 10 AM.

Priya: We haven't decided which deployment platform to use. We'll decide during the review.

Rahul: I'll document the API endpoints before the review.

Alex: Great. Priya owns the frontend, Rahul owns the backend, and we'll check everyone's progress during the review."""

        analysis = LyzrClient.analyze_locally(
            "Project kickoff",
            transcript,
            "source-kickoff",
        )

        self.assertEqual(analysis.analysis_mode, "local_fallback")
        self.assertIn("Local fallback analysis — not AI-generated.", analysis.summary)
        self.assertEqual(len(analysis.summary.split(". ")), 3)
        self.assertLess(len(analysis.summary), len(transcript) + 80)
        self.assertEqual(analysis.decisions, ["No confirmed decisions."])
        self.assertEqual(
            [
                (item.task, item.owner, item.deadline)
                for item in analysis.action_items
            ],
            [
                ("Handle frontend and prepare the initial screens", "Priya", "by October 17"),
                ("Develop backend API", "Rahul", "by October 18"),
                ("Document API endpoints", "Rahul", "before the review"),
            ],
        )
        self.assertEqual(
            analysis.key_dates,
            [
                "October 20 - first prototype deadline",
                "October 17 - frontend and prepare the initial screens deadline",
                "October 18 - backend API deadline",
                "October 21 at 10 AM - prototype review",
            ],
        )
        self.assertEqual(
            analysis.open_questions,
            ["Priya: We haven't decided which deployment platform to use."],
        )
        self.assertNotIn("Rahul: I'll develop", analysis.summary)
        self.assertNotIn("Priya: I'll handle", analysis.summary)
        self.assertNotIn("Alex: We'll review", analysis.summary)
        self.assertNotIn("Rahul: I'll document", analysis.summary)

    def test_local_analysis_does_not_infer_missing_decisions_or_deadlines(self) -> None:
        analysis = LyzrClient.analyze_locally(
            "Planning",
            "Jordan will investigate options. The deployment platform was not approved.",
            "source-planning",
        )

        self.assertEqual(analysis.decisions, ["No confirmed decisions."])
        self.assertEqual(analysis.action_items, [])
        self.assertEqual(
            analysis.open_questions,
            ["The deployment platform was not approved."],
        )
        self.assertTrue(
            analysis.summary.startswith("Local fallback analysis — not AI-generated.")
        )

    def test_local_analysis_recognizes_will_commitments(self) -> None:
        analysis = LyzrClient.analyze_locally(
            "API planning",
            "Rahul: I will develop the backend API by Monday.",
            "source-api-planning",
        )

        self.assertEqual(
            [
                (item.task, item.owner, item.deadline)
                for item in analysis.action_items
            ],
            [("Develop backend API", "Rahul", "by Monday")],
        )

    def test_missing_lyzr_credentials_are_explicit(self) -> None:
        client = LyzrClient(test_settings())

        with self.assertRaisesRegex(LyzrError, "LYZR_API_KEY and LYZR_AGENT_ID"):
            client._chat("hello", "test-session")


if __name__ == "__main__":
    unittest.main()
