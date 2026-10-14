"""Smoke-test the configured Qdrant and Lyzr services without touching app data."""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DOTENV_VALUES = dotenv_values(ENV_FILE)
load_dotenv(ENV_FILE)

QDRANT_TEST_COLLECTION = "recallflow_integration_test_4d"
LYZR_DEFAULT_BASE_URL = "https://agent-prod.studio.lyzr.ai/v3"


def _print_result(service: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    print(f"{status} {service}: {detail}")


def _sanitize(message: str) -> str:
    """Remove configured credentials and URL query/user-info before displaying errors."""
    for settings in (DOTENV_VALUES, os.environ):
        for name, value in settings.items():
            if value and any(
                marker in name.upper()
                for marker in (
                    "KEY",
                    "TOKEN",
                    "SECRET",
                    "PASSWORD",
                    "CREDENTIAL",
                    "URL",
                    "ENDPOINT",
                    "AGENT_ID",
                )
            ):
                message = message.replace(value, "[redacted]")

    message = re.sub(
        r"(?i)(https?://)[^/@\s]+@",
        r"\1[redacted]@",
        message,
    )
    message = re.sub(
        r"(?i)([?&](?:api[_-]?key|token|secret|password|signature)=)[^&#\s]+",
        r"\1[redacted]",
        message,
    )
    message = re.sub(
        r"(?i)((?:authorization|x-api-key)\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1[redacted]",
        message,
    )
    message = re.sub(r"\s+", " ", message).strip()
    return message[:240] if message else "No further error details."


def _qdrant_setting(name: str) -> str:
    """Prefer this project's .env over stale inherited Qdrant settings."""
    file_value = DOTENV_VALUES.get(name)
    if file_value and file_value.strip():
        return file_value.strip()
    return os.getenv(name, "").strip()


def _qdrant_exception_detail(error: Exception) -> str:
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return f"HTTP {status_code}; {_sanitize(str(error))}"
    return f"{type(error).__name__}; {_sanitize(str(error))}"


def _close_qdrant_client(client: Any) -> None:
    try:
        client.close()
    except Exception as exc:
        print(f"WARN Qdrant client cleanup: {_qdrant_exception_detail(exc)}")


def _get_vector_sizes(collection_info: Any) -> list[int]:
    vectors = collection_info.config.params.vectors
    if isinstance(vectors, dict):
        return [
            vector.size
            for vector in vectors.values()
            if getattr(vector, "size", None) is not None
        ]
    size = getattr(vectors, "size", None)
    return [size] if size is not None else []


def test_qdrant() -> bool:
    url = _qdrant_setting("QDRANT_URL")
    api_key = _qdrant_setting("QDRANT_API_KEY")
    if not url:
        _print_result("Qdrant connectivity/authentication", False, "QDRANT_URL is not set.")
        _print_result("Qdrant 4-D collection round-trip", False, "Skipped because Qdrant is not configured.")
        return False

    try:
        from qdrant_client import QdrantClient, models
    except ImportError:
        _print_result(
            "Qdrant connectivity/authentication",
            False,
            "qdrant-client is not installed; install the project requirements.",
        )
        _print_result(
            "Qdrant 4-D collection round-trip",
            False,
            "Skipped because qdrant-client is unavailable.",
        )
        return False

    client = None
    try:
        client = QdrantClient(url=url, api_key=api_key or None, timeout=10)
        client.get_collections()
    except Exception as exc:
        _print_result(
            "Qdrant connectivity/authentication",
            False,
            _qdrant_exception_detail(exc),
        )
        _print_result(
            "Qdrant 4-D collection round-trip",
            False,
            "Skipped because the connectivity/authentication check failed.",
        )
        if client is not None:
            _close_qdrant_client(client)
        return False

    _print_result("Qdrant connectivity/authentication", True, "Connection and collection listing succeeded.")

    try:
        if not client.collection_exists(QDRANT_TEST_COLLECTION):
            client.create_collection(
                collection_name=QDRANT_TEST_COLLECTION,
                vectors_config=models.VectorParams(
                    size=4,
                    distance=models.Distance.COSINE,
                ),
            )

        collection_info = client.get_collection(QDRANT_TEST_COLLECTION)
        vector_sizes = _get_vector_sizes(collection_info)
        if 4 not in vector_sizes:
            raise ValueError(
                "The existing integration-test collection does not have a 4-dimensional vector."
            )

        point_id = str(uuid.uuid4())
        payload = {"purpose": "integration-test", "test_id": point_id}
        client.upsert(
            collection_name=QDRANT_TEST_COLLECTION,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=[0.1, 0.2, 0.3, 0.4],
                    payload=payload,
                )
            ],
            wait=True,
        )
        points = client.retrieve(
            collection_name=QDRANT_TEST_COLLECTION,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if len(points) != 1 or points[0].payload != payload:
            raise ValueError("Retrieved point payload did not match the inserted payload.")
    except Exception as exc:
        _print_result(
            "Qdrant 4-D collection round-trip",
            False,
            _qdrant_exception_detail(exc),
        )
        _close_qdrant_client(client)
        return False

    _close_qdrant_client(client)
    _print_result(
        "Qdrant 4-D collection round-trip",
        True,
        "Test point inserted and retrieved with its payload verified.",
    )
    return True


def test_lyzr() -> bool:
    api_key = os.getenv("LYZR_API_KEY", "").strip()
    agent_id = os.getenv("LYZR_AGENT_ID", "").strip()
    if not api_key or not agent_id:
        missing = [
            name
            for name, value in (
                ("LYZR_API_KEY", api_key),
                ("LYZR_AGENT_ID", agent_id),
            )
            if not value
        ]
        _print_result("Lyzr Chat API", False, f"Missing required setting(s): {', '.join(missing)}.")
        return False

    try:
        import requests
    except ImportError:
        _print_result("Lyzr Chat API", False, "requests is not installed; install the project requirements.")
        return False

    base_url = os.getenv("LYZR_BASE_URL", LYZR_DEFAULT_BASE_URL).strip().rstrip("/")
    endpoint = f"{base_url}/inference/chat/"
    body = {
        "user_id": os.getenv("LYZR_USER_ID", "recallflow-integration-test").strip(),
        "agent_id": agent_id,
        "session_id": f"recallflow-integration-test-{uuid.uuid4()}",
        "message": "Reply with a short greeting.",
    }

    try:
        response = requests.post(
            endpoint,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
    except requests.Timeout:
        _print_result("Lyzr Chat API", False, "Request timed out after 30 seconds.")
        return False
    except requests.RequestException as exc:
        _print_result("Lyzr Chat API", False, f"{type(exc).__name__}; {_sanitize(str(exc))}")
        return False

    if not response.ok:
        _print_result("Lyzr Chat API", False, f"HTTP {response.status_code}; request was rejected.")
        return False

    try:
        result = response.json()
    except ValueError:
        _print_result("Lyzr Chat API", False, "HTTP success returned a non-JSON response.")
        return False

    answer = result.get("response") if isinstance(result, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        _print_result("Lyzr Chat API", False, "Response did not contain a non-empty 'response' field.")
        return False

    _print_result("Lyzr Chat API", True, "Chat request succeeded and returned a non-empty response.")
    return True


def main() -> int:
    qdrant_passed = test_qdrant()
    lyzr_passed = test_lyzr()
    return 0 if qdrant_passed and lyzr_passed else 1


if __name__ == "__main__":
    sys.exit(main())
