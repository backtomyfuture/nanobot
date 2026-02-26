"""Qdrant vector search tool for historical email retrieval and ingestion."""

import hashlib
import json
import uuid
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


def _lazy_qdrant():
    """Lazy import qdrant_client to avoid hard dependency."""
    try:
        from qdrant_client import QdrantClient, models
        return QdrantClient, models
    except ImportError:
        return None, None


def _lazy_openai():
    """Lazy import openai for embedding API calls."""
    try:
        from openai import OpenAI
        return OpenAI
    except ImportError:
        return None


class _EmbeddingHelper:
    """Shared embedding client for qdrant tools."""

    def __init__(self, api_key: str, base_url: str, model: str):
        openai_cls = _lazy_openai()
        if openai_cls is None:
            raise ImportError("openai package not installed")
        self._client = openai_cls(base_url=base_url, api_key=api_key or "ollama", timeout=10.0)
        self._model = model

    def embed(self, text: str) -> list[float]:
        try:
            resp = self._client.embeddings.create(input=text, model=self._model)
            return resp.data[0].embedding
        except Exception as e:
            logger.error("Embedding failed: {}", e)
            return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = self._client.embeddings.create(input=texts, model=self._model)
            return [d.embedding for d in resp.data]
        except Exception as e:
            logger.error("Batch embedding failed: {}", e)
            return []


class QdrantSearchTool(Tool):
    """Search historical emails in Qdrant by semantic similarity and/or thread."""

    name = "qdrant_search"
    description = (
        "Search historical emails in the Qdrant vector database. "
        "Supports semantic search by query text and thread-based search by conversation ID. "
        "Use this to find relevant context before drafting a reply."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query text (subject + body excerpt for best results)",
            },
            "sender": {
                "type": "string",
                "description": "Filter by sender email (optional)",
            },
            "thread_id": {
                "type": "string",
                "description": "Conversation/thread ID for same-thread search (optional)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 5)",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    }

    def __init__(self, qdrant_url: str, collection: str, embedder: _EmbeddingHelper):
        self._qdrant_url = qdrant_url
        self._collection = collection
        self._embedder = embedder
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            qdrant_cls, _ = _lazy_qdrant()
            if qdrant_cls is None:
                raise ImportError("qdrant-client package not installed")
            self._client = qdrant_cls(url=self._qdrant_url)
        return self._client

    async def execute(
        self, query: str, sender: str = "", thread_id: str = "",
        limit: int = 5, **kwargs: Any,
    ) -> str:
        _, qdrant_models = _lazy_qdrant()
        if qdrant_models is None:
            return "Error: qdrant-client package not installed. Run: pip install qdrant-client"

        results: list[dict] = []

        try:
            client = self._get_client()

            if thread_id:
                thread_filter = qdrant_models.Filter(must=[
                    qdrant_models.FieldCondition(
                        key="thread_id",
                        match=qdrant_models.MatchValue(value=thread_id),
                    )
                ])
                points, _ = client.scroll(
                    collection_name=self._collection,
                    scroll_filter=thread_filter,
                    limit=min(limit, 10),
                    with_payload=True,
                )
                results.extend(self._format_points(points))

            remaining = max(0, limit - len(results))
            if remaining > 0 and query:
                vector = self._embedder.embed(query)
                if vector:
                    search_filter = None
                    if sender:
                        search_filter = qdrant_models.Filter(must=[
                            qdrant_models.FieldCondition(
                                key="sender",
                                match=qdrant_models.MatchValue(value=sender),
                            )
                        ])
                    search_result = client.query_points(
                        collection_name=self._collection,
                        query=vector,
                        query_filter=search_filter,
                        limit=remaining,
                        with_payload=True,
                    )
                    seen = {r.get("id") for r in results}
                    for hit in search_result.points:
                        if hit.payload.get("id") not in seen:
                            results.append(self._format_payload(hit.payload))

        except Exception as e:
            logger.error("Qdrant search error: {}", e)
            return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)

        return json.dumps({"count": len(results), "results": results}, ensure_ascii=False)

    @staticmethod
    def _format_points(points) -> list[dict]:
        return [QdrantSearchTool._format_payload(p.payload) for p in points if p.payload]

    @staticmethod
    def _format_payload(payload: dict) -> dict:
        return {
            "id": payload.get("id", ""),
            "subject": payload.get("subject", ""),
            "sender": payload.get("sender", ""),
            "body": (payload.get("body", "") or payload.get("chunk_text", ""))[:500],
            "received_at": payload.get("received_at", ""),
            "thread_id": payload.get("thread_id", ""),
        }


class QdrantIngestTool(Tool):
    """Ingest an email into the Qdrant vector store for future retrieval."""

    name = "qdrant_ingest"
    description = (
        "Index an email into the Qdrant vector database for future RAG retrieval. "
        "Use this after processing an Exchange email to build the knowledge base."
    )
    parameters = {
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "Email ID"},
            "subject": {"type": "string", "description": "Email subject"},
            "sender": {"type": "string", "description": "Sender address"},
            "body": {"type": "string", "description": "Email body text"},
            "thread_id": {"type": "string", "description": "Thread/conversation ID (optional)"},
            "received_at": {"type": "string", "description": "Received timestamp (optional)"},
        },
        "required": ["email_id", "subject", "body"],
    }

    def __init__(self, qdrant_url: str, collection: str, embedder: _EmbeddingHelper):
        self._qdrant_url = qdrant_url
        self._collection = collection
        self._embedder = embedder
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            qdrant_cls, _ = _lazy_qdrant()
            if qdrant_cls is None:
                raise ImportError("qdrant-client package not installed")
            self._client = qdrant_cls(url=self._qdrant_url)
        return self._client

    async def execute(
        self, email_id: str, subject: str, body: str,
        sender: str = "", thread_id: str = "", received_at: str = "",
        **kwargs: Any,
    ) -> str:
        _, qdrant_models = _lazy_qdrant()
        if qdrant_models is None:
            return "Error: qdrant-client package not installed"

        full_text = f"Subject: {subject}\n\n{body}"
        chunks = _split_text(full_text, chunk_size=1000, overlap=100)
        if not chunks:
            return "Error: empty content, nothing to ingest"

        embeddings = self._embedder.embed_batch(chunks)
        if not embeddings:
            return "Error: embedding generation failed"

        try:
            client = self._get_client()
            try:
                client.get_collection(self._collection)
            except Exception:
                dim = len(embeddings[0])
                client.create_collection(
                    collection_name=self._collection,
                    vectors_config=qdrant_models.VectorParams(
                        size=dim, distance=qdrant_models.Distance.COSINE
                    ),
                )
                logger.info("Created Qdrant collection '{}' (dim={})", self._collection, dim)

            points = []
            for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
                chunk_id = hashlib.md5(f"{email_id}_{i}_{chunk[:20]}".encode()).hexdigest()
                point_id = str(uuid.UUID(chunk_id))
                points.append(qdrant_models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "id": email_id,
                        "subject": subject,
                        "sender": sender,
                        "body": body[:5000],
                        "chunk_text": chunk,
                        "chunk_index": i,
                        "thread_id": thread_id,
                        "received_at": received_at,
                    },
                ))

            client.upsert(collection_name=self._collection, points=points, wait=False)
            return json.dumps({
                "ok": True, "email_id": email_id, "chunks": len(points),
            })
        except Exception as e:
            logger.error("Qdrant ingest failed for {}: {}", email_id, e)
            return f"Error: {e}"


def _split_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Simple text chunker (avoids langchain dependency)."""
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
