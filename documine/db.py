"""The only place that talks to Supabase (PostgreSQL + Storage). Uses the secret key on the server."""

from supabase import Client, create_client

from documine import config

PAGE_SIZE = 1000  # Supabase returns at most 1000 rows per request
INSERT_BATCH = 500

_client = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.require("SUPABASE_URL"), config.require("SUPABASE_KEY"))
    return _client


# ---------- files and documents ----------

def upload_file(storage_path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to the private 'uploads' bucket. Use simple paths like '<sha256>/<filename>'."""
    get_client().storage.from_(config.STORAGE_BUCKET).upload(
        storage_path, data, {"content-type": content_type, "upsert": "true"}
    )
    return storage_path


def find_document_by_sha256(sha256: str) -> dict | None:
    """Return the existing document with this hash, or None. Use it to skip duplicate uploads."""
    rows = get_client().table("documents").select("*").eq("sha256", sha256).limit(1).execute().data
    return rows[0] if rows else None


def insert_document(filename: str, file_type: str, storage_path: str, sha256: str) -> str:
    """Insert one document row and return its id."""
    row = {"filename": filename, "file_type": file_type, "storage_path": storage_path, "sha256": sha256}
    return get_client().table("documents").insert(row).execute().data[0]["id"]


def insert_chunks(document_id: str, chunks: list[dict]) -> int:
    """Insert chunks for one document. Each chunk dict needs 'location' and 'content'. Returns count."""
    rows = [{"document_id": document_id, "location": c["location"], "content": c["content"]} for c in chunks]
    for start in range(0, len(rows), INSERT_BATCH):
        get_client().table("chunks").insert(rows[start:start + INSERT_BATCH]).execute()
    return len(rows)


def list_documents() -> list[dict]:
    return get_client().table("documents").select("*").order("uploaded_at", desc=True).execute().data


def get_chunks(document_ids: list[str]) -> list[dict]:
    """Return chunks {id, document_id, filename, location, content} in upload order."""
    if not document_ids:
        return []
    rows = []
    start = 0
    while True:
        page = (
            get_client().table("chunks")
            .select("id, document_id, location, content, documents(filename)")
            .in_("document_id", document_ids)
            .order("id")
            .range(start, start + PAGE_SIZE - 1)
            .execute().data
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return [
        {
            "id": r["id"],
            "document_id": r["document_id"],
            "filename": r["documents"]["filename"],
            "location": r["location"],
            "content": r["content"],
        }
        for r in rows
    ]


def search_chunks(query: str, k: int = 8) -> list[dict]:
    """Full-text search (any word matches). Returns chunks plus 'score', best first."""
    return get_client().rpc("search_chunks", {"q": query, "k": k}).execute().data


# ---------- generated documents ----------

def save_generated(doc_type: str, title: str, markdown: str, source_ids: list) -> str:
    row = {"doc_type": doc_type, "title": title, "markdown": markdown, "source_ids": source_ids}
    return get_client().table("generated_docs").insert(row).execute().data[0]["id"]


def list_generated() -> list[dict]:
    return get_client().table("generated_docs").select("*").order("created_at", desc=True).execute().data


def update_generated(id: str, markdown: str, status: str) -> None:
    get_client().table("generated_docs").update({"markdown": markdown, "status": status}).eq("id", id).execute()
