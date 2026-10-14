from dataclasses import dataclass
from pathlib import Path
import uuid

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models


MAX_CHUNK_CHARS = 1800
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_SIZE = 384


@dataclass(frozen=True)
class MemoryChunk:
    source_id: str
    title: str
    reference: str
    text: str


@dataclass(frozen=True)
class RetrievedChunk:
    title: str
    reference: str
    text: str
    score: float
    source_id: str = ""


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    normalized = " ".join(text.split())
    chunks: list[str] = []
    start = 0

    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        start = end
        while start < len(normalized) and normalized[start].isspace():
            start += 1

    return [chunk for chunk in chunks if chunk]


class TranscriptMemory:
    def __init__(
        self,
        collection: str,
        local_path: Path,
        url: str = "",
        api_key: str = "",
    ) -> None:
        if url:
            self.client = QdrantClient(url=url, api_key=api_key or None)
        else:
            self.client = QdrantClient(path=str(local_path))
        self.collection = collection
        self._embedder: TextEmbedding | None = None

    def _get_embedder(self) -> TextEmbedding:
        if self._embedder is None:
            self._embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
        return self._embedder

    def _ensure_collection(self) -> None:
        if not self.client.collection_exists(collection_name=self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            return

        collection = self.client.get_collection(collection_name=self.collection)
        vectors = collection.config.params.vectors
        if isinstance(vectors, dict) or getattr(vectors, "size", None) != EMBEDDING_SIZE:
            raise RuntimeError(
                "Qdrant collection vector configuration is incompatible with RecallFlow."
            )

    def ingest(self, title: str, transcript: str, source_id: str) -> int:
        chunks = [
            MemoryChunk(
                source_id=source_id,
                title=title,
                reference=f"chunk {index + 1}",
                text=text,
            )
            for index, text in enumerate(split_text(transcript))
        ]
        self.add_chunks(chunks)
        return len(chunks)

    def add_chunks(self, chunks: list[MemoryChunk]) -> int:
        if not chunks:
            return 0

        ids = [
            str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{chunk.source_id}|{chunk.reference}|{chunk.text}",
                )
            )
            for chunk in chunks
        ]
        self._ensure_collection()
        vectors = self._get_embedder().embed([chunk.text for chunk in chunks])
        points = [
            models.PointStruct(
                id=point_id,
                vector=vector.tolist(),
                payload={
                    "source_id": chunk.source_id,
                    "title": chunk.title,
                    "reference": chunk.reference,
                    "document": chunk.text,
                },
            )
            for point_id, chunk, vector in zip(ids, chunks, vectors)
        ]
        self.client.upsert(
            collection_name=self.collection,
            points=points,
            wait=True,
        )
        return len(chunks)

    def search(self, query: str, limit: int = 5) -> list[RetrievedChunk]:
        if not self.client.collection_exists(collection_name=self.collection):
            return []
        self._ensure_collection()
        query_embeddings = iter(self._get_embedder().query_embed(query))
        try:
            query_vector = next(query_embeddings)
        except StopIteration as exc:
            raise RuntimeError("FastEmbed did not produce a query embedding.") from exc
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector.tolist(),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        matches: list[RetrievedChunk] = []
        for point in response.points:
            payload = point.payload or {}
            matches.append(
                RetrievedChunk(
                    title=str(payload.get("title", "Untitled transcript")),
                    reference=str(payload.get("reference", "transcript")),
                    text=str(payload.get("document", payload.get("text", ""))),
                    score=float(point.score or 0),
                    source_id=str(payload.get("source_id", "")),
                )
            )
        return matches
