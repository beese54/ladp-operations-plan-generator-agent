from functools import lru_cache
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from config.settings import get_settings

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_SOP = "sop_documents"
COLLECTION_HISTORICAL = "historical_plans"


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=get_settings().chroma_persist_dir)


@lru_cache(maxsize=1)
def _get_embedding_function() -> SentenceTransformerEmbeddingFunction:
    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def get_or_create_collection(name: str) -> chromadb.Collection:
    return get_chroma_client().get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_function(),
    )


def prewarm_collections() -> None:
    """Load both collections into memory at startup."""
    get_or_create_collection(COLLECTION_SOP)
    get_or_create_collection(COLLECTION_HISTORICAL)
