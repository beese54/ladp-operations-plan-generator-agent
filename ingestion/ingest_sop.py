"""
Ingest SOP documents from data/seed/sop_documents/ into ChromaDB.
Run: python -m ingestion.ingest_sop
Idempotent full re-sync: re-running replaces each document's chunks so that
edits (changed text, added or removed chunks) are reflected without duplicates.
"""
import logging
import sys
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from db.chroma_client import get_or_create_collection, COLLECTION_SOP

logger = logging.getLogger(__name__)

SOP_DIR = Path("data/seed/sop_documents")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.error("PDF read error for %s: %s", path, e)
            return ""
    if suffix == ".docx":
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.error("DOCX read error for %s: %s", path, e)
            return ""
    return path.read_text(encoding="utf-8", errors="replace")


def ingest_sop_documents(sop_dir: Path = SOP_DIR) -> int:
    if not sop_dir.exists():
        logger.warning("SOP directory not found: %s", sop_dir)
        return 0

    files = (list(sop_dir.glob("*.txt"))
             + list(sop_dir.glob("*.pdf"))
             + list(sop_dir.glob("*.docx"))
             + list(sop_dir.glob("*.md")))
    if not files:
        logger.warning("No .txt or .pdf files found in %s", sop_dir)
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    collection = get_or_create_collection(COLLECTION_SOP)

    total_inserted = 0
    for filepath in files:
        stem = filepath.stem
        raw = _read_file(filepath)
        if not raw.strip():
            logger.warning("Empty file skipped: %s", filepath)
            continue

        chunks = splitter.split_text(raw)
        ids, docs, metas = [], [], []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{stem}_chunk_{i:04d}"
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append({
                "source_file": filepath.name,
                "sop_id": stem,
                "sop_title": stem.replace("_", " ").title(),
                "chunk_index": i,
                "total_chunks": len(chunks),
                "tags": "",
            })

        # Full re-sync per file: drop any prior chunks for this document so that
        # edits (changed text or fewer chunks) are reflected, not just appended.
        # Upsert alone would leave stale chunks when the doc shrinks or a chunk's
        # text changes at an index that already exists.
        collection.delete(where={"sop_id": stem})
        if ids:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            total_inserted += len(ids)
            logger.info("  %s: %d chunks synced", filepath.name, len(ids))

    logger.info("SOP ingestion complete. Total new chunks: %d", total_inserted)
    return total_inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    count = ingest_sop_documents()
    print(f"Inserted {count} new SOP chunks.")
    sys.exit(0)
