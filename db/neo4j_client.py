import logging
from functools import lru_cache
from typing import Any
from neo4j import GraphDatabase, Driver, ManagedTransaction
from config.settings import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_neo4j_driver() -> Driver:
    s = get_settings()
    return GraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_username, s.neo4j_password),
        max_connection_pool_size=10,
    )


def close_driver() -> None:
    driver = get_neo4j_driver()
    driver.close()
    get_neo4j_driver.cache_clear()


def verify_connectivity() -> bool:
    try:
        get_neo4j_driver().verify_connectivity()
        return True
    except Exception as e:
        logger.error("Neo4j connectivity check failed: %s", e)
        return False


def execute_read(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    def _run(tx: ManagedTransaction) -> list[dict[str, Any]]:
        result = tx.run(query, params or {})
        return [dict(r) for r in result]

    with get_neo4j_driver().session() as session:
        return session.execute_read(_run)


def execute_write(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    def _run(tx: ManagedTransaction) -> list[dict[str, Any]]:
        result = tx.run(query, params or {})
        return [dict(r) for r in result]

    with get_neo4j_driver().session() as session:
        return session.execute_write(_run)
