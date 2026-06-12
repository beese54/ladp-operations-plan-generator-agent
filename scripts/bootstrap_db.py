"""
One-shot database bootstrap.
Run: python scripts/bootstrap_db.py [--skip-neo4j] [--skip-sop] [--skip-history] [--skip-sqlite]
"""
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def bootstrap_sqlite() -> bool:
    try:
        from db.sqlite_client import bootstrap_sqlite_schema
        bootstrap_sqlite_schema()
        logger.info("SQLite schema created/verified.")
        return True
    except Exception as e:
        logger.error("SQLite bootstrap failed: %s", e)
        return False


def bootstrap_neo4j() -> bool:
    """Print instructions for running the seed Cypher — auto-execution not done here to avoid accidental writes."""
    logger.info("Neo4j seed file: data/seed/neo4j_seed.cypher")
    logger.info("Run it in Neo4j Aura Browser or via cypher-shell.")
    logger.info("The seed uses MERGE so it is safe to re-run.")
    return True


def bootstrap_sop() -> bool:
    try:
        from ingestion.ingest_sop import ingest_sop_documents
        count = ingest_sop_documents()
        logger.info("SOP ingestion: %d new chunks.", count)
        return True
    except Exception as e:
        logger.error("SOP ingestion failed: %s", e)
        return False


def bootstrap_history() -> bool:
    try:
        from ingestion.ingest_historical import ingest_historical_plans
        count = ingest_historical_plans()
        logger.info("Historical ingestion: %d new chunks.", count)
        return True
    except Exception as e:
        logger.error("Historical ingestion failed: %s", e)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap all databases")
    parser.add_argument("--skip-neo4j",   action="store_true")
    parser.add_argument("--skip-sop",     action="store_true")
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--skip-sqlite",  action="store_true")
    args = parser.parse_args()

    results = {}
    if not args.skip_sqlite:
        results["sqlite"]  = bootstrap_sqlite()
    if not args.skip_neo4j:
        results["neo4j"]   = bootstrap_neo4j()
    if not args.skip_sop:
        results["sop"]     = bootstrap_sop()
    if not args.skip_history:
        results["history"] = bootstrap_history()

    failed = [k for k, v in results.items() if not v]
    if failed:
        logger.error("Failed steps: %s", failed)
        sys.exit(1)

    logger.info("Bootstrap complete.")
    sys.exit(0)
