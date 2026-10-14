"""Run a small end-to-end check against a running RecallFlow API."""

import argparse
import os
import re
import sys
import uuid
from typing import Any

import requests


FACT = "The prototype codename is ORCHID-7419."
REQUEST_TIMEOUT = (5, 75)


class ApiResponseError(RuntimeError):
    def __init__(self, status_code: int, detail: str | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}")


def safe_api_error_detail(response: requests.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    detail = payload.get("detail")
    if not isinstance(detail, str) or len(detail) > 240:
        return None
    if re.fullmatch(
        r"Transcript was stored in Qdrant, but Lyzr analysis failed "
        r"\([A-Za-z][A-Za-z0-9_]*, upstream HTTP "
        r"(?:[1-5][0-9]{2}|status unavailable)\)\.",
        detail,
    ):
        return detail
    if re.fullmatch(
        r"Transcript context was retrieved, but Lyzr could not answer "
        r"the question \([A-Za-z][A-Za-z0-9_]*, upstream HTTP "
        r"(?:[1-5][0-9]{2}|status unavailable)\)\.",
        detail,
    ):
        return detail
    return None


def report(stage: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    print(f"{status} {stage}: {detail}")


def post_json(base_url: str, path: str, payload: dict[str, str]) -> dict[str, Any]:
    response = requests.post(
        f"{base_url}{path}",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        raise ApiResponseError(
            response.status_code,
            safe_api_error_detail(response),
        )
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Response must be a JSON object.")
    return result


def run(base_url: str) -> int:
    nonce = uuid.uuid4().hex
    title = f"RecallFlow integration check {nonce}"
    transcript = (
        f"During the synthetic product review, the team confirmed: {FACT} "
        f"This note belongs to integration run {nonce}."
    )
    question = "What is the prototype codename?"
    expected_source_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{title}|{transcript.strip()}")
    )

    healthy = False
    health_detail = "health check failed; response details omitted."
    try:
        response = requests.get(
            f"{base_url}/health",
            timeout=REQUEST_TIMEOUT,
        )
        healthy = response.ok and response.json() == {"status": "ok"}
        if not response.ok:
            health_detail = f"API returned HTTP {response.status_code}; response body omitted."
        elif not healthy:
            health_detail = "health response was not the expected status object."
    except requests.Timeout:
        health_detail = "request timed out; response details omitted."
    except (requests.RequestException, ValueError):
        pass
    report(
        "API health",
        healthy,
        "health endpoint responded successfully." if healthy else health_detail,
    )

    transcript_success = False
    if healthy:
        try:
            transcript_result = post_json(
                base_url,
                "/api/transcripts",
                {"title": title, "transcript": transcript},
            )
            transcript_success = (
                transcript_result.get("source_id") == expected_source_id
                and isinstance(transcript_result.get("stored_chunks"), int)
                and transcript_result["stored_chunks"] > 0
                and isinstance(transcript_result.get("analysis"), dict)
            )
            report(
                "Transcript ingestion and analysis",
                transcript_success,
                "unique transcript stored and structured analysis returned."
                if transcript_success
                else "response did not include the expected unique source ID, stored chunks, and analysis.",
            )
        except ApiResponseError as exc:
            report(
                "Transcript ingestion and analysis",
                False,
                f"API returned HTTP {exc.status_code}; "
                f"{exc.detail or 'safe diagnostic unavailable.'}",
            )
        except requests.Timeout:
            report(
                "Transcript ingestion and analysis",
                False,
                "request timed out; response details omitted.",
            )
        except (requests.RequestException, ValueError):
            report(
                "Transcript ingestion and analysis",
                False,
                "request failed; response details omitted.",
            )
    else:
        report(
            "Transcript ingestion and analysis",
            False,
            "not run because the API health check failed.",
        )

    question_result: dict[str, Any] | None = None
    question_success = False
    if transcript_success:
        try:
            question_result = post_json(
                base_url,
                "/api/questions",
                {"question": question},
            )
            question_success = (
                isinstance(question_result.get("answer"), str)
                and bool(question_result["answer"].strip())
                and isinstance(question_result.get("sources"), list)
                and bool(question_result["sources"])
            )
            report(
                "Question answering and retrieval",
                question_success,
                "answer and retrieved source references returned."
                if question_success
                else "response did not include a non-empty answer and source list.",
            )
        except ApiResponseError as exc:
            report(
                "Question answering and retrieval",
                False,
                f"API returned HTTP {exc.status_code}; "
                f"{exc.detail or 'safe diagnostic unavailable.'}",
            )
        except requests.Timeout:
            report(
                "Question answering and retrieval",
                False,
                "request timed out; response details omitted.",
            )
        except (requests.RequestException, ValueError):
            report(
                "Question answering and retrieval",
                False,
                "request failed; response details omitted.",
            )
    else:
        report(
            "Question answering and retrieval",
            False,
            "not run because transcript ingestion or analysis failed.",
        )

    verification_success = False
    if question_success and question_result is not None:
        answer = question_result.get("answer")
        sources = question_result.get("sources")
        source_ids = {
            source.get("source_id") for source in sources if isinstance(source, dict)
        }
        citations = re.findall(r"\[(\d+)\]", answer)
        references_valid = all(
            isinstance(source, dict)
            and isinstance(source.get("title"), str)
            and isinstance(source.get("reference"), str)
            for source in sources
        )
        citations_valid = bool(citations) and all(
            1 <= int(citation) <= len(sources) for citation in citations
        )
        verification_success = (
            isinstance(answer, str)
            and FACT.casefold() in answer.casefold()
            and expected_source_id in source_ids
            and references_valid
            and citations_valid
        )
        report(
            "Fact and source verification",
            verification_success,
            "distinctive fact, unique source ID, and citation indices verified."
            if verification_success
            else "expected fact or unique source/citation verification failed.",
        )
    else:
        report(
            "Fact and source verification",
            False,
            "not run because question answering failed.",
        )

    return 0 if (
        healthy
        and transcript_success
        and question_success
        and verification_success
    ) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("RECALLFLOW_API_URL", "http://127.0.0.1:8000"),
        help="Base URL of a running RecallFlow API (default: %(default)s).",
    )
    args = parser.parse_args()
    return run(args.base_url.rstrip("/"))


if __name__ == "__main__":
    sys.exit(main())
