import logging
from typing import Any, Optional
from db.chroma_client import get_or_create_collection, COLLECTION_SOP, COLLECTION_HISTORICAL

logger = logging.getLogger(__name__)


def _distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB L2 distance to a 0-1 similarity score (lower distance = higher similarity)."""
    return max(0.0, 1.0 - distance / 2.0)


def _format_results(ids, documents, metadatas, distances) -> list[dict[str, Any]]:
    results = []
    for i in range(len(ids[0])):
        results.append({
            "id": ids[0][i],
            "text": documents[0][i],
            "metadata": metadatas[0][i],
            "similarity_score": _distance_to_similarity(distances[0][i]),
        })
    return results


def search_sop_documents(
    query: str,
    n_results: int = 5,
    filter_tags: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Query the SOP documents collection for relevant principles."""
    try:
        collection = get_or_create_collection(COLLECTION_SOP)
        count = collection.count()
        if count == 0:
            logger.warning("SOP collection is empty. Ingest SOP documents first.")
            return []

        where = None
        if filter_tags:
            where = {"tags": {"$in": filter_tags}}

        result = collection.query(
            query_texts=[query],
            n_results=min(n_results, count),
            include=["documents", "metadatas", "distances"],
            where=where,
        )
        return _format_results(result["ids"], result["documents"], result["metadatas"], result["distances"])
    except Exception as e:
        logger.error("SOP search error: %s", e)
        return []


def search_historical_plans(
    query: str,
    n_results: int = 3,
    filter_metadata: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Query the historical plans collection for similar past operations."""
    try:
        collection = get_or_create_collection(COLLECTION_HISTORICAL)
        count = collection.count()
        if count == 0:
            logger.warning("Historical plans collection is empty. Ingest historical plans first.")
            return []

        result = collection.query(
            query_texts=[query],
            n_results=min(n_results, count),
            include=["documents", "metadatas", "distances"],
            where=filter_metadata,
        )
        return _format_results(result["ids"], result["documents"], result["metadatas"], result["distances"])
    except Exception as e:
        logger.error("Historical plans search error: %s", e)
        return []
