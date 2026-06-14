"""
Smoke-test all four services required by the application.
Exit code 0 if all pass, 1 if any fail.
Run: python scripts/verify_connections.py
"""
import sys
import time

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(name: str, fn) -> bool:
    t0 = time.monotonic()
    try:
        result = fn()
        elapsed = (time.monotonic() - t0) * 1000
        if result:
            print(f"  [{PASS}] {name} ({elapsed:.0f}ms)")
            return True
        else:
            print(f"  [{FAIL}] {name} — returned falsy")
            return False
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  [{FAIL}] {name} ({elapsed:.0f}ms): {e}")
        return False


def test_neo4j() -> bool:
    from db.neo4j_client import verify_connectivity
    return verify_connectivity()


def test_chromadb() -> bool:
    from db.chroma_client import get_or_create_collection, COLLECTION_SOP
    col = get_or_create_collection(COLLECTION_SOP)
    _ = col.count()
    return True


def test_sqlite() -> bool:
    from db.sqlite_client import get_sqlite_connection
    with get_sqlite_connection() as conn:
        conn.execute("SELECT 1")
    return True


def test_azure_openai() -> bool:
    from config.settings import get_azure_openai_client
    client = get_azure_openai_client()
    client.models.list()
    return True


def test_together() -> bool:
    from config.settings import get_together_client, get_settings
    s = get_settings()
    if not s.together_api_key:
        print("    (TOGETHER_API_KEY not set — skipping)")
        return True
    client = get_together_client()
    # Use a minimal chat completion to verify the key works
    resp = client.chat.completions.create(
        model=s.together_model,
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=5,
    )
    return bool(resp.choices[0].message.content)


if __name__ == "__main__":
    print("\nWater Network Ops Generator — Connection Verification\n")

    results = [
        check("Neo4j Aura",  test_neo4j),
        check("ChromaDB",    test_chromadb),
        check("SQLite",       test_sqlite),
        check("Azure OpenAI", test_azure_openai),
        check("Together.ai",  test_together),
    ]

    print()
    if all(results):
        print("All checks passed.")
        sys.exit(0)
    else:
        failed = results.count(False)
        print(f"{failed} check(s) failed. Review .env and ensure services are reachable.")
        sys.exit(1)
