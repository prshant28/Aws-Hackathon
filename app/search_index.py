"""Optional OpenSearch index for Recall X247.

Firestore remains the source of truth.  When OPENSEARCH_URL is configured,
captured memories are mirrored into an OpenSearch index and recall tries that
index before using the existing Firestore search cascade.  Every OpenSearch
operation is best-effort so a search cluster outage never blocks capture or
recall.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from app.config import settings
from app.user_context import get_uid, belongs_to_current_user

logger = logging.getLogger("recall-x247.search")

_client: Any = None
_client_error: Optional[str] = None
_index_ready = False


def is_configured() -> bool:
    return bool((settings.OPENSEARCH_URL or "").strip())


def _serialise_date(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _memory_document(memory: dict) -> dict:
    return {
        "user_id": memory.get("user_id") or memory.get("userId") or get_uid(),
        "title": memory.get("title", ""),
        "summary": memory.get("summary", ""),
        "executive_summary": memory.get("executive_summary", ""),
        "key_points": memory.get("key_points") or [],
        "action_items": memory.get("action_items") or [],
        "glossary": memory.get("glossary") or [],
        "study_questions": memory.get("study_questions") or [],
        "tags": memory.get("tags") or [],
        "domain": memory.get("domain", "Other"),
        "source_type": memory.get("source_type", "note"),
        "source_url": memory.get("source_url", ""),
        "created_at": _serialise_date(memory.get("created_at")),
    }


def _build_client() -> Any:
    global _client_error
    if not is_configured():
        return None
    if _client is not None:
        return _client

    try:
        from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

        parsed = urlparse(settings.OPENSEARCH_URL)
        if not parsed.hostname:
            raise ValueError("OPENSEARCH_URL must include a hostname")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        auth: Any = None

        if settings.OPENSEARCH_AWS_AUTH:
            import boto3

            credentials = boto3.Session().get_credentials()
            if credentials is None:
                raise RuntimeError("AWS credentials were not found for OpenSearch IAM auth")
            auth = AWSV4SignerAuth(
                credentials,
                settings.AWS_REGION,
                settings.OPENSEARCH_AWS_SERVICE,
            )
        elif settings.OPENSEARCH_USERNAME:
            auth = (
                settings.OPENSEARCH_USERNAME,
                settings.OPENSEARCH_PASSWORD or "",
            )

        client = OpenSearch(
            hosts=[{"host": parsed.hostname, "port": port}],
            http_auth=auth,
            use_ssl=parsed.scheme == "https",
            verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
            connection_class=RequestsHttpConnection,
            timeout=settings.OPENSEARCH_TIMEOUT,
            max_retries=1,
            retry_on_timeout=True,
        )
        _client_error = None
        globals()["_client"] = client
        return client
    except Exception as exc:
        _client_error = str(exc)
        logger.warning("OpenSearch client unavailable: %s", exc)
        return None


def _index_body() -> dict:
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "user_id": {"type": "keyword"},
                "title": {"type": "text"},
                "summary": {"type": "text"},
                "executive_summary": {"type": "text"},
                "key_points": {"type": "text"},
                "action_items": {"type": "text"},
                "glossary": {"type": "text"},
                "study_questions": {"type": "text"},
                "tags": {"type": "keyword"},
                "domain": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "source_url": {"type": "keyword", "index": False},
                "created_at": {"type": "date"},
            }
        },
    }


def _ensure_index_sync(client: Any) -> None:
    global _index_ready
    if _index_ready:
        return
    if not client.indices.exists(index=settings.OPENSEARCH_INDEX):
        client.indices.create(index=settings.OPENSEARCH_INDEX, body=_index_body())
    _index_ready = True


async def index_memory(memory: dict) -> bool:
    """Mirror one memory into OpenSearch without affecting the request."""
    client = _build_client()
    memory_id = memory.get("id")
    if client is None or not memory_id:
        return False
    try:
        await asyncio.to_thread(_ensure_index_sync, client)
        await asyncio.to_thread(
            client.index,
            index=settings.OPENSEARCH_INDEX,
            id=str(memory_id),
            body=_memory_document(memory),
            refresh=False,
        )
        return True
    except Exception as exc:
        logger.warning("OpenSearch index write skipped: %s", exc)
        return False


async def delete_memory(memory_id: str) -> bool:
    client = _build_client()
    if client is None:
        return False
    try:
        await asyncio.to_thread(
            client.delete,
            index=settings.OPENSEARCH_INDEX,
            id=memory_id,
            ignore=[404],
            refresh=False,
        )
        return True
    except Exception as exc:
        logger.warning("OpenSearch delete skipped: %s", exc)
        return False


async def search_memories(
    query: str,
    *,
    user_id: str = "",
    source_type: str = "",
    limit: int = 10,
) -> Optional[list[dict]]:
    """Search the configured OpenSearch index.

    None means OpenSearch is disabled or unavailable, which tells the caller
    to continue with the existing Firestore search path.  An empty list is a
    successful search with no matching documents.
    """
    client = _build_client()
    if client is None or not query.strip():
        return None
    try:
        await asyncio.to_thread(_ensure_index_sync, client)
        filters: list[dict] = [
            {"term": {"user_id": user_id or get_uid()}},
        ]
        if source_type:
            filters.append({"term": {"source_type": source_type}})
        body = {
            "size": max(1, min(int(limit or 10), 40)),
            "_source": True,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": [
                                    "title^4",
                                    "summary^3",
                                    "executive_summary^2",
                                    "key_points^2",
                                    "action_items",
                                    "glossary",
                                    "study_questions",
                                    "tags^2",
                                    "domain",
                                ],
                                "operator": "and",
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "sort": [
                {"_score": {"order": "desc"}},
                {"created_at": {"order": "desc", "unmapped_type": "date"}},
            ],
        }
        response = await asyncio.to_thread(
            client.search,
            index=settings.OPENSEARCH_INDEX,
            body=body,
        )
        results: list[dict] = []
        for hit in (response.get("hits", {}).get("hits", []) or []):
            source = hit.get("_source") or {}
            source["id"] = hit.get("_id")
            results.append(source)
        return results
    except Exception as exc:
        logger.warning("OpenSearch query failed; using Firestore fallback: %s", exc)
        return None


def status() -> dict:
    return {
        "provider": "OpenSearch",
        "configured": is_configured(),
        "index": settings.OPENSEARCH_INDEX if is_configured() else None,
        "aws_iam_auth": bool(settings.OPENSEARCH_AWS_AUTH) if is_configured() else False,
        "last_error": _client_error,
    }


async def reindex_current_user() -> dict:
    """Rebuild the current user's search documents from Firestore."""
    client = _build_client()
    if client is None:
        return {"ok": False, "indexed": 0, "reason": "OpenSearch is not configured"}

    from app.db import get_db

    db = await get_db()
    uid = get_uid()
    snapshot = await db.collection("memories").get()
    indexed = 0
    for doc in snapshot:
        memory = doc.to_dict() or {}
        if not belongs_to_current_user(memory):
            continue
        memory["id"] = doc.id
        if await index_memory(memory):
            indexed += 1
    return {"ok": True, "indexed": indexed, "user_id": uid}