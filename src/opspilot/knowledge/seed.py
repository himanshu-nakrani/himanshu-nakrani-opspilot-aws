"""Sample knowledge loaded into the one knowledge base on deploy.

Every document is rendered from corpus.json. Service, trigger, host, region,
and the operator note are chosen at random so each deploy varies the text
without a second catalog.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from opspilot.knowledge.ingest import data_source_id

CORPUS_PATH = Path(__file__).with_name("corpus.json")


def load_corpus() -> Dict[str, Any]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _one(value: Any, rng: random.Random) -> str:
    if isinstance(value, list):
        return str(rng.choice(value))
    return str(value)


def _request_id(rng: random.Random) -> str:
    alphabet = "0123456789abcdef"
    return "".join(rng.choice(alphabet) for _ in range(12))


def _key(entry_id: str, index: int) -> str:
    if index == 0:
        return f"seed/{entry_id}.md"
    return f"seed/{entry_id}-{index + 1}.md"


def _render(entry: Dict[str, Any], pool: Dict[str, List[str]], rng: random.Random, index: int) -> Dict[str, str]:
    lines = [
        f"# {entry['title']}",
        "",
        f"- Kind: {entry['kind']}",
        f"- Service: {_one(entry['service'], rng)}",
        f"- Classification: {entry['classification']}",
    ]
    if entry.get("trigger"):
        lines.append(f"- Trigger: {_one(entry['trigger'], rng)}")
    lines.extend(
        [
            f"- Region: {rng.choice(pool['regions'])}",
            f"- Host: {rng.choice(pool['hosts'])}",
            f"- Request: {_request_id(rng)}",
            f"- Shift: {rng.choice(pool['shifts'])}",
            "",
            "## What happened",
            _one(entry["happened"], rng),
        ]
    )
    if entry.get("detail"):
        lines.extend(["", _one(entry["detail"], rng)])
    lines.extend(
        [
            "",
            "## What fixed it",
            _one(entry["fix"], rng),
            "",
            "## Note",
            rng.choice(pool["notes"]),
            "",
        ]
    )
    return {"key": _key(str(entry["id"]), index), "body": "\n".join(lines)}


def documents_from_corpus(
    rng: Optional[random.Random] = None,
    corpus: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Build the upload set by randomizing every catalog entry."""
    rng = rng or random.Random()
    corpus = corpus if corpus is not None else load_corpus()
    copies = int(corpus.get("copies") or 1)
    documents: List[Dict[str, str]] = []
    for entry in corpus["entries"]:
        for index in range(copies):
            documents.append(_render(entry, corpus["random"], rng, index))
    return documents


def seed_knowledge_base(
    *,
    s3_client: Any,
    agent_client: Any = None,
    bucket: str,
    knowledge_base_id: str = "",
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Upload randomized sample documents and sync the one knowledge base when its id is set."""
    uploaded: List[str] = []
    for doc in documents_from_corpus(rng):
        s3_client.put_object(
            Bucket=bucket,
            Key=doc["key"],
            Body=doc["body"].encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
            ServerSideEncryption="AES256",
        )
        uploaded.append(doc["key"])
    if not knowledge_base_id:
        return {"uploaded": uploaded, "job_id": None}
    source_id = data_source_id(agent_client, knowledge_base_id)
    response = agent_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=source_id,
    )
    job_id = str((response.get("ingestionJob") or {}).get("ingestionJobId") or "") or None
    return {"uploaded": uploaded, "job_id": job_id}
