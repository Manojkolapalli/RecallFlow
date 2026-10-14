from typing import Any

from recallflow.memory import MemoryChunk, split_text


class OmiPayloadError(ValueError):
    """An Omi webhook payload is missing required transcript data."""


def transcript_chunks(
    payload: Any,
    session_id: str = "",
) -> list[MemoryChunk]:
    if isinstance(payload, dict):
        memory_id = str(payload.get("id") or session_id or "unknown")
        source_id = f"omi:{memory_id}"
        structured = payload.get("structured")
        title = (
            structured.get("title")
            if isinstance(structured, dict)
            else None
        ) or f"Omi conversation {memory_id}"
        segments = payload.get("transcript_segments", [])
        if not isinstance(segments, list):
            raise OmiPayloadError("Omi memory payload transcript_segments must be a list.")

        chunks: list[MemoryChunk] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                raise OmiPayloadError("Each Omi transcript segment must contain text.")
            text = segment["text"].strip()
            if not text:
                continue
            start = segment.get("start", index)
            speaker = str(segment.get("speaker_name") or segment.get("speaker") or "speaker")
            text_chunks = split_text(text)
            for part, content in enumerate(text_chunks):
                suffix = f" ({part + 1})" if len(text_chunks) > 1 else ""
                chunks.append(
                    MemoryChunk(
                        source_id=source_id,
                        title=str(title),
                        reference=f"{speaker}, {start}s{suffix}",
                        text=content,
                    )
                )
        if not chunks:
            raise OmiPayloadError("Omi memory did not contain any transcript text.")
        return chunks

    if isinstance(payload, list):
        if not session_id:
            raise OmiPayloadError("Omi real-time transcript requests require session_id.")
        chunks = []
        for index, segment in enumerate(payload):
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                raise OmiPayloadError("Each Omi transcript segment must contain text.")
            text = segment["text"].strip()
            if not text:
                continue
            start = segment.get("start", index)
            end = segment.get("end", "")
            speaker = str(segment.get("speaker") or "speaker")
            interval = f"{start}-{end}s" if end != "" else f"{start}s"
            text_chunks = split_text(text)
            for part, content in enumerate(text_chunks):
                suffix = f" ({part + 1})" if len(text_chunks) > 1 else ""
                chunks.append(
                    MemoryChunk(
                        source_id=f"omi-session:{session_id}",
                        title=f"Omi session {session_id}",
                        reference=f"{speaker}, {interval}{suffix}",
                        text=content,
                    )
                )
        if not chunks:
            raise OmiPayloadError("Omi transcript request did not contain any text.")
        return chunks

    raise OmiPayloadError("Omi webhook body must be a memory object or transcript segment list.")
