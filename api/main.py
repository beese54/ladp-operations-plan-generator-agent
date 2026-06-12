import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware import RequestIDMiddleware, global_exception_handler
from api.routes import health, chat, schedule, graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Water Network Ops Generator API")

    try:
        from db.neo4j_client import verify_connectivity
        if verify_connectivity():
            logger.info("Neo4j Aura: connected")
        else:
            logger.warning("Neo4j Aura: unreachable — running in degraded mode")
    except Exception as e:
        logger.warning("Neo4j Aura startup check failed: %s", e)

    try:
        from db.chroma_client import prewarm_collections
        prewarm_collections()
        logger.info("ChromaDB: collections pre-warmed")
    except Exception as e:
        logger.warning("ChromaDB pre-warm failed: %s", e)

    try:
        from db.sqlite_client import bootstrap_sqlite_schema
        bootstrap_sqlite_schema()
        logger.info("SQLite: schema bootstrapped")
    except Exception as e:
        logger.warning("SQLite bootstrap failed: %s", e)

    try:
        from evaluation.tracing import setup_mlflow_tracing
        setup_mlflow_tracing()
        logger.info("MLflow tracing: enabled")
    except Exception as e:
        logger.warning("MLflow tracing setup failed (non-fatal): %s", e)

    yield  # Application runs here

    # Shutdown
    try:
        from db.neo4j_client import close_driver
        close_driver()
        logger.info("Neo4j driver closed")
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Water Network Operations Plan Generator",
        version="1.0.0",
        description="Multi-agent system for generating water network operations plans",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(Exception, global_exception_handler)

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(chat.router,   prefix="/api/v1", tags=["chat"])
    app.include_router(schedule.router, prefix="/api/v1", tags=["schedule"])
    app.include_router(graph.router,    prefix="/api/v1", tags=["graph"])

    return app


app = create_app()
