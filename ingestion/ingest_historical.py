"""
Ingest historical operations plans from data/seed/historical_plans/ into ChromaDB.
Run: python -m ingestion.ingest_historical
Idempotent: re-running will upsert without creating duplicates.

Expected filename convention (optional, used for metadata):
  OPS-2025-001_pipe_151_SUCCESS.txt
  └── plan_id=OPS-2025-001, pipe_id=pipe_151, outcome=SUCCESS
Any filename works; metadata fields default to empty if not parseable.
"""
import logging
import re
import sys
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from db.chroma_client import get_or_create_collection, COLLECTION_HISTORICAL

logger = logging.getLogger(__name__)

HIST_DIR = Path("data/seed/historical_plans")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

_FILENAME_PATTERN = re.compile(
    r"^(?P<plan_id>OPS-[\w-]+)_pipe_(?P<pipe_id>\w+)_(?P<outcome>SUCCESS|PARTIAL|FAILED)",
    re.IGNORECASE,
)


def _parse_filename_metadata(stem: str) -> dict:
    m = _FILENAME_PATTERN.match(stem)
    if m:
        return {
            "plan_id": m.group("plan_id"),
            "pipe_id": m.group("pipe_id"),
            "outcome": m.group("outcome").upper(),
        }
    return {"plan_id": stem, "pipe_id": "", "outcome": ""}


def _read_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.error("PDF read error for %s: %s", path, e)
            return ""
    return path.read_text(encoding="utf-8", errors="replace")


def ingest_historical_plans(hist_dir: Path = HIST_DIR) -> int:
    if not hist_dir.exists():
        logger.warning("Historical plans directory not found: %s", hist_dir)
        return 0

    files = list(hist_dir.glob("*.txt")) + list(hist_dir.glob("*.pdf"))
    if not files:
        logger.warning("No .txt or .pdf files found in %s", hist_dir)
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    collection = get_or_create_collection(COLLECTION_HISTORICAL)
    existing_ids: set[str] = set(collection.get()["ids"])

    total_inserted = 0
    for filepath in files:
        stem = filepath.stem
        raw = _read_file(filepath)
        if not raw.strip():
            logger.warning("Empty file skipped: %s", filepath)
            continue

        meta_base = _parse_filename_metadata(stem)
        chunks = splitter.split_text(raw)
        ids, docs, metas = [], [], []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{stem}_chunk_{i:04d}"
            if chunk_id in existing_ids:
                continue
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append({
                "source_file": filepath.name,
                "plan_id": meta_base["plan_id"],
                "pipe_id": meta_base["pipe_id"],
                "outcome": meta_base["outcome"],
                "plan_title": stem.replace("_", " ").title(),
                "chunk_index": i,
                "total_chunks": len(chunks),
            })

        if ids:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            total_inserted += len(ids)
            logger.info("  %s: %d chunks inserted", filepath.name, len(ids))
        else:
            logger.info("  %s: all chunks already present", filepath.name)

    logger.info("Historical ingestion complete. Total new chunks: %d", total_inserted)
    return total_inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    count = ingest_historical_plans()
    print(f"Inserted {count} new historical plan chunks.")
    sys.exit(0)
