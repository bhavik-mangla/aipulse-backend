"""
Qdrant vector store operations.
Manages the govnotify_chunks collection for hybrid search
(dense + sparse vectors with metadata payload indexes).
"""
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    SparseVectorParams,
    VectorParams,
)

from govnotify.config import get_settings

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "govnotify_chunks"

# Payload fields that need indexes for efficient filtered search
PAYLOAD_INDEXES = [
    ("categories", PayloadSchemaType.KEYWORD),
    ("regions", PayloadSchemaType.KEYWORD),
    ("departments", PayloadSchemaType.KEYWORD),
    ("source_id", PayloadSchemaType.KEYWORD),
    ("language", PayloadSchemaType.KEYWORD),
    ("ingested_at", PayloadSchemaType.DATETIME),
    ("document_id", PayloadSchemaType.KEYWORD),
]


def get_qdrant_client(
    port: int | None = None, host: str | None = None
) -> QdrantClient:
    """Create a Qdrant client from settings or explicit params."""
    settings = get_settings()
    return QdrantClient(
        host=host or settings.qdrant_host,
        port=port or settings.qdrant_port,
    )


def create_collection(client: QdrantClient, collection_name: str | None = None) -> None:
    """
    Create the govnotify_chunks collection with dense + sparse vectors.
    Idempotent - skips if collection already exists.
    Creates payload indexes BEFORE data insertion (Qdrant best practice).
    """
    name = collection_name or COLLECTION_NAME
    if client.collection_exists(name):
        logger.info("qdrant_collection_exists", collection=name)
        return

    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": VectorParams(
                size=1024,  # BGE-M3 dimension
                distance=Distance.COSINE,
                on_disk=False,  # Keep in RAM for speed
            )
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),  # BM25/SPLADE sparse vectors
        },
    )

    logger.info("qdrant_collection_created", collection=name)

    # Create payload indexes for efficient filtered search
    for field_name, schema_type in PAYLOAD_INDEXES:
        client.create_payload_index(
            collection_name=name,
            field_name=field_name,
            field_schema=schema_type,
        )
        logger.info(
            "qdrant_payload_index_created",
            collection=name,
            field=field_name,
            schema_type=str(schema_type),
        )


def delete_collection(client: QdrantClient, collection_name: str | None = None) -> None:
    """Delete a collection (for testing/reset)."""
    name = collection_name or COLLECTION_NAME
    if client.collection_exists(name):
        client.delete_collection(name)
        logger.info("qdrant_collection_deleted", collection=name)


def health_check(client: QdrantClient) -> bool:
    """Check if Qdrant is reachable and responsive."""
    try:
        client.get_collections()
        return True
    except Exception:
        return False
