from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from recallflow.lyzr import ActionItem, LyzrError, MeetingAnalysis
from recallflow.memory import RetrievedChunk


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeStreamlit(ModuleType):
    def __init__(self, submitted_form: str, title: str = "Product review") -> None:
        super().__init__("streamlit")
        self.submitted_form = submitted_form
        self.title_value = title
        self.session_state: dict[str, object] = {}
        self.messages: list[str] = []
        self.current_form = ""

    def set_page_config(self, **kwargs: object) -> None:
        pass

    def cache_resource(self, function):
        return function

    @contextmanager
    def form(self, name: str):
        self.current_form = name
        yield

    def text_input(self, label: str, **kwargs: object) -> str:
        return {
            "Meeting or lecture title": self.title_value,
            "Question": "What is the codename?",
        }[label]

    def text_area(self, label: str, **kwargs: object) -> str:
        return "The prototype codename is ORCHID-7419."

    def form_submit_button(self, label: str) -> bool:
        submitted = {
            "transcript_form": "Save and analyze",
            "question_form": "Ask",
        }[self.current_form]
        return label == submitted and label == self.submitted_form

    def spinner(self, label: str):
        return _NullContext()

    def __getattr__(self, name: str):
        if name in {
            "title", "caption", "info", "warning", "success", "error",
            "subheader", "markdown", "write",
        }:
            return lambda *args, **kwargs: self.messages.append(str(args[0]))
        if name == "divider":
            return lambda: None
        raise AttributeError(name)


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class FakeMemory:
    def __init__(self, **kwargs: object) -> None:
        self.sources = [
            RetrievedChunk(
                title="Product review",
                reference="chunk 1",
                text="The prototype codename is ORCHID-7419.",
                score=0.91,
                source_id="source-123",
            )
        ]

    def ingest(self, title: str, transcript: str, source_id: str) -> int:
        return 1

    def search(self, question: str) -> list[RetrievedChunk]:
        return self.sources


class FakeLyzr:
    def __init__(self, settings: object) -> None:
        self.configured = True

    def analyze(self, title: str, transcript: str, source_id: str) -> MeetingAnalysis:
        raise LyzrError("Could not connect to Lyzr.", availability_failure=True)

    def analyze_locally(
        self,
        title: str,
        transcript: str,
        source_id: str,
    ) -> MeetingAnalysis:
        return MeetingAnalysis(
            summary=f"Local fallback: {transcript}",
            decisions=[],
            action_items=[ActionItem("Review prototype", "Unassigned", "Not specified")],
        )

    def answer(
        self,
        question: str,
        sources: list[RetrievedChunk],
    ) -> str:
        raise LyzrError("Could not connect to Lyzr.", availability_failure=True)

    def answer_locally(
        self,
        question: str,
        sources: list[RetrievedChunk],
    ) -> str:
        return (
            "Local fallback: The excerpt records the codename "
            "ORCHID-7419 [1]."
        )


class StreamlitFallbackTests(unittest.TestCase):
    def run_app(
        self,
        submitted_form: str,
        title: str = "Product review",
    ) -> FakeStreamlit:
        fake_st = FakeStreamlit(submitted_form, title)
        settings = SimpleNamespace(
            qdrant_url="",
            qdrant_api_key="",
            qdrant_collection="test",
            qdrant_local_path=Path(".qdrant-test"),
        )
        spec = importlib.util.spec_from_file_location(
            "_recallflow_streamlit_app_test",
            PROJECT_ROOT / "app.py",
        )
        if spec is None or spec.loader is None:
            self.fail("Could not load app.py for the UI test.")
        module = importlib.util.module_from_spec(spec)
        with (
            patch.dict(sys.modules, {"streamlit": fake_st}),
            patch("recallflow.config.load_settings", return_value=settings),
            patch("recallflow.memory.TranscriptMemory", FakeMemory),
            patch("recallflow.lyzr.LyzrClient", FakeLyzr),
        ):
            spec.loader.exec_module(module)
        return fake_st

    def test_connection_failure_renders_local_analysis(self) -> None:
        ui = self.run_app("Save and analyze")
        rendered = "\n".join(ui.messages)

        self.assertIn("Local fallback analysis", rendered)
        self.assertIn("Local fallback: The prototype codename is ORCHID-7419.", rendered)
        self.assertIn("Review prototype", rendered)
        self.assertNotIn("Could not connect to Lyzr.", rendered)

    def test_transcript_form_requires_title(self) -> None:
        with patch.object(FakeMemory, "ingest") as ingest:
            ui = self.run_app("Save and analyze", title="  ")

        self.assertIn("Enter a meeting or lecture title before submitting.", ui.messages)
        ingest.assert_not_called()

    def test_storage_failure_is_reported_without_exposing_exception(self) -> None:
        with patch.object(
            FakeMemory,
            "ingest",
            side_effect=RuntimeError("private Qdrant detail"),
        ):
            ui = self.run_app("Save and analyze")

        rendered = "\n".join(ui.messages)
        self.assertIn("Qdrant is unavailable or failed to store the transcript.", rendered)
        self.assertNotIn("private Qdrant detail", rendered)
        self.assertNotIn("Meeting intelligence", rendered)

    def test_connection_failure_renders_local_answer_and_sources(self) -> None:
        ui = self.run_app("Ask")
        rendered = "\n".join(ui.messages)

        self.assertIn("Local fallback answer — not AI-generated", rendered)
        self.assertIn("ORCHID-7419 [1]", rendered)
        self.assertIn("Product review", rendered)
        self.assertIn("chunk 1", rendered)
        self.assertNotIn("Could not connect to Lyzr.", rendered)


if __name__ == "__main__":
    unittest.main()
