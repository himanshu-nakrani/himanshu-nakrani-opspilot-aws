"""Retrieve past merged solutions from a Bedrock Knowledge Base."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_MAX_QUERY = 500
_NO_KB = "Knowledge base is not configured."


def retrieve_knowledge(
    query: str,
    *,
    client: Any = None,
    knowledge_base_id: str = "",
    limit: int = 5,
) -> Dict[str, Any]:
    """Return passage text for the RCA agent. Passages are background, not evidence."""
    text = " ".join(str(query or "").split())[:_MAX_QUERY]
    if not text:
        return {"passages": [], "error": "A search query is required."}
    if not knowledge_base_id:
        return {"passages": [], "error": _NO_KB}
    if client is None:
        import boto3

        client = boto3.client("bedrock-agent-runtime")
    try:
        response = client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": text},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": max(1, min(limit, 8))}},
        )
    except Exception as exc:
        logger.warning("Knowledge base retrieve failed: %s", exc)
        return {"passages": [], "error": "The knowledge base could not be searched."}
    passages = []
    for item in response.get("retrievalResults") or []:
        content = (item.get("content") or {}).get("text") or ""
        if not content:
            continue
        location = item.get("location") or {}
        source = (location.get("s3Location") or {}).get("uri") or ""
        passages.append({"text": content, "score": item.get("score"), "source": source})
    return {"passages": passages, "error": None}
