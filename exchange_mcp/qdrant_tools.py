"""Qdrant vector search and ingestion for email RAG."""

import hashlib
import uuid
from typing import Any


def _split_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


class QdrantTools:
    """Qdrant operations for email search and ingestion."""

    def __init__(self, url: str, collection: str, embedding_api_key: str,
                 embedding_base_url: str, embedding_model: str):
        self._url = url
        self._collection = collection
        self._embedding_model = embedding_model
        self._qdrant = None
        self._openai = None

        from openai import OpenAI
        self._openai = OpenAI(
            base_url=embedding_base_url, api_key=embedding_api_key or "ollama", timeout=10.0
        )

    def _get_qdrant(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            self._qdrant = QdrantClient(url=self._url)
        return self._qdrant

    def _embed(self, text: str) -> list[float]:
        resp = self._openai.embeddings.create(input=text, model=self._embedding_model)
        return resp.data[0].embedding

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._openai.embeddings.create(input=texts, model=self._embedding_model)
        return [d.embedding for d in resp.data]

    def search(self, query: str, sender: str = "", thread_id: str = "",
               limit: int = 5) -> dict[str, Any]:
        from qdrant_client import models
        client = self._get_qdrant()
        results: list[dict] = []

        if thread_id:
            filt = models.Filter(must=[
                models.FieldCondition(key="thread_id", match=models.MatchValue(value=thread_id))
            ])
            points, _ = client.scroll(
                collection_name=self._collection, scroll_filter=filt,
                limit=min(limit, 10), with_payload=True,
            )
            results.extend(self._fmt(points))

        remaining = max(0, limit - len(results))
        if remaining > 0 and query:
            vector = self._embed(query)
            if vector:
                sf = None
                if sender:
                    sf = models.Filter(must=[
                        models.FieldCondition(key="sender", match=models.MatchValue(value=sender))
                    ])
                hits = client.query_points(
                    collection_name=self._collection, query=vector,
                    query_filter=sf, limit=remaining, with_payload=True,
                )
                seen = {r.get("id") for r in results}
                for h in hits.points:
                    if h.payload.get("id") not in seen:
                        results.append(self._fmt_one(h.payload))

        return {"count": len(results), "results": results}

    def ingest(self, email_id: str, subject: str, body: str,
               sender: str = "", thread_id: str = "", received_at: str = "") -> dict[str, Any]:
        from qdrant_client import models
        client = self._get_qdrant()

        full_text = f"Subject: {subject}\n\n{body}"
        chunks = _split_text(full_text)
        if not chunks:
            return {"ok": False, "reason": "empty content"}

        embeddings = self._embed_batch(chunks)
        if not embeddings:
            return {"ok": False, "reason": "embedding failed"}

        try:
            client.get_collection(self._collection)
        except Exception:
            dim = len(embeddings[0])
            client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )

        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            cid = hashlib.md5(f"{email_id}_{i}_{chunk[:20]}".encode()).hexdigest()
            points.append(models.PointStruct(
                id=str(uuid.UUID(cid)), vector=vector,
                payload={
                    "id": email_id, "subject": subject, "sender": sender,
                    "body": body[:5000], "chunk_text": chunk, "chunk_index": i,
                    "thread_id": thread_id, "received_at": received_at,
                },
            ))
        client.upsert(collection_name=self._collection, points=points, wait=False)
        return {"ok": True, "email_id": email_id, "chunks": len(points)}

    @staticmethod
    def _fmt(points) -> list[dict]:
        return [QdrantTools._fmt_one(p.payload) for p in points if p.payload]

    @staticmethod
    def _fmt_one(payload: dict) -> dict:
        return {
            "id": payload.get("id", ""),
            "subject": payload.get("subject", ""),
            "sender": payload.get("sender", ""),
            "body": (payload.get("body", "") or payload.get("chunk_text", ""))[:500],
            "received_at": payload.get("received_at", ""),
        }
