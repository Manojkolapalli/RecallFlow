import hmac
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from recallflow.config import load_settings
from recallflow.memory import TranscriptMemory
from recallflow.omi import OmiPayloadError, transcript_chunks

app = FastAPI(title="RecallFlow Omi webhook")


def _authorize(token: str) -> None:
    expected = load_settings().omi_webhook_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="OMI_WEBHOOK_TOKEN is not configured on this server.",
        )
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook token.")


def _get_memory() -> TranscriptMemory:
    settings = load_settings()
    if not settings.qdrant_url:
        raise HTTPException(
            status_code=503,
            detail="Set QDRANT_URL to a reachable Qdrant server for Omi webhook ingestion.",
        )
    return TranscriptMemory(
        collection=settings.qdrant_collection,
        local_path=settings.qdrant_local_path,
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )


async def _read_payload(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from exc


async def _ingest(
    request: Request,
    token: str,
    session_id: str = "",
) -> dict[str, int]:
    _authorize(token)
    payload = await _read_payload(request)
    try:
        chunks = transcript_chunks(payload, session_id=session_id)
    except OmiPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = _get_memory().add_chunks(chunks)
    return {"stored_segments": saved}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/omi/transcript")
async def receive_realtime_transcript(
    request: Request,
    token: str = Query(default=""),
    session_id: str = Query(default=""),
) -> dict[str, int]:
    return await _ingest(request, token, session_id)


@app.post("/omi/memory")
async def receive_completed_memory(
    request: Request,
    token: str = Query(default=""),
) -> dict[str, int]:
    return await _ingest(request, token)
