"""Payloads for an Amazon Bedrock managed knowledge base and its S3 connector.

The vector store stays inside Bedrock. Callers pass these documents to
``create_knowledge_base`` and ``create_data_source``; this module does not
provision AWS resources by itself.
"""

from __future__ import annotations

from typing import Any, Dict


def managed_kb_configuration() -> Dict[str, Any]:
    """Managed knowledge base: Bedrock owns embeddings and the vector store."""
    return {
        "type": "MANAGED",
        "managedKnowledgeBaseConfiguration": {"embeddingModelType": "MANAGED"},
    }


def s3_connector_configuration(bucket: str, account_id: str) -> Dict[str, Any]:
    """Managed S3 connector. This is not the customer-managed ``s3Configuration`` shape."""
    return {
        "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR",
        "managedKnowledgeBaseConnectorConfiguration": {
            "connectorParameters": {
                "type": "S3",
                "version": "1",
                "connectionConfiguration": {
                    "bucketName": bucket,
                    "bucketOwnerAccountId": account_id,
                },
            }
        },
    }
