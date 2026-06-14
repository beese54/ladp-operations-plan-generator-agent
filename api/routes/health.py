from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from schemas.api_models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    results = {}

    # Neo4j
    try:
        from db.neo4j_client import verify_connectivity
        results["neo4j"] = "OK" if verify_connectivity() else "ERROR"
    except Exception as e:
        results["neo4j"] = f"ERROR: {e}"

    # ChromaDB
    try:
        from db.chroma_client import get_or_create_collection, COLLECTION_SOP
        col = get_or_create_collection(COLLECTION_SOP)
        col.count()
        results["chromadb"] = "OK"
    except Exception as e:
        results["chromadb"] = f"ERROR: {e}"

    # SQLite
    try:
        from db.sqlite_client import get_sqlite_connection
        with get_sqlite_connection() as conn:
            conn.execute("SELECT 1")
        results["sqlite"] = "OK"
    except Exception as e:
        results["sqlite"] = f"ERROR: {e}"

    # Azure OpenAI
    try:
        from config.settings import get_azure_openai_client
        client = get_azure_openai_client()
        client.models.list()
        results["azure_openai"] = "OK"
    except Exception as e:
        results["azure_openai"] = f"ERROR: {e}"

    overall = "OK" if all(v == "OK" for v in results.values()) else "DEGRADED"
    status_code = 200 if overall == "OK" else 503

    body = HealthResponse(
        status=overall,
        neo4j=results["neo4j"],
        chromadb=results["chromadb"],
        sqlite=results["sqlite"],
        azure_openai=results["azure_openai"],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return JSONResponse(content=body.model_dump(), status_code=status_code)
