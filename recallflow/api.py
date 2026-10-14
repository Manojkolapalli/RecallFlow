from dataclasses import asdict
from functools import lru_cache
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from qdrant_client.http.exceptions import ApiException

from recallflow.config import load_settings
from recallflow.lyzr import LyzrClient, LyzrError
from recallflow.memory import TranscriptMemory


class TranscriptRequest(BaseModel):
    transcript: str
    title: str = "Untitled meeting"


class QuestionRequest(BaseModel):
    question: str


settings = load_settings()
lyzr = LyzrClient(settings)
app = FastAPI(title="RecallFlow API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@lru_cache
def get_memory() -> TranscriptMemory:
    return TranscriptMemory(
        collection=settings.qdrant_collection,
        local_path=settings.qdrant_local_path,
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/transcripts")
def create_transcript(request: TranscriptRequest) -> dict[str, object]:
    transcript = request.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="Transcript text must not be empty.")

    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Transcript title must not be empty.")
    source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{title}|{transcript}"))
    try:
        chunk_count = get_memory().ingest(title, transcript, source_id)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Qdrant embedding support is unavailable; install project requirements.",
        ) from exc
    except (ApiException, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Qdrant is unavailable or failed to store the transcript.",
        ) from exc

    if not lyzr.configured:
        analysis = lyzr.analyze_locally(title, transcript, source_id)
    else:
        try:
            analysis = lyzr.analyze(title, transcript, source_id)
        except LyzrError as exc:
            if not exc.availability_failure:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Transcript was stored in Qdrant, but Lyzr analysis failed "
                        f"({exc.diagnostic})."
                    ),
                ) from exc
            analysis = lyzr.analyze_locally(title, transcript, source_id)

    return {
        "source_id": source_id,
        "stored_chunks": chunk_count,
        "analysis": asdict(analysis),
    }


@app.post("/api/questions")
def ask_question(request: QuestionRequest) -> dict[str, object]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question must not be empty.")

    try:
        sources = get_memory().search(question)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Qdrant embedding support is unavailable; install project requirements.",
        ) from exc
    except (ApiException, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Qdrant is unavailable or failed to search transcript memory.",
        ) from exc

    if not sources:
        raise HTTPException(
            status_code=404,
            detail="No matching transcript context was found.",
        )
    if not lyzr.configured:
        answer = lyzr.answer_locally(question, sources)
    else:
        try:
            answer = lyzr.answer(question, sources)
        except LyzrError as exc:
            if not exc.availability_failure:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Transcript context was retrieved, but Lyzr could not answer "
                        f"the question ({exc.diagnostic})."
                    ),
                ) from exc
            answer = lyzr.answer_locally(question, sources)

    return {
        "answer": answer,
        "sources": [asdict(source) for source in sources],
    }
