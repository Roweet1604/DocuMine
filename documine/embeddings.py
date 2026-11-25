"""Owner: P3 (retrieval). Gemini embeddings for vector search: gemini-embedding-001, 768 dims, cosine.

Chunks are embedded with task type RETRIEVAL_DOCUMENT, questions with RETRIEVAL_QUERY.
Rate limits and temporary errors are retried with backoff, like llm.py.
"""

import time

import httpx
from google.genai import errors, types

from documine import db, llm

MODEL = "gemini-embedding-001"
DIMENSIONS = 768
BATCH_SIZE = 50
MAX_ATTEMPTS = 6
FIRST_DELAY_SECONDS = 5
MAX_DELAY_SECONDS = 60
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    """Embed texts in one request. task_type is RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY."""
    if not texts:
        return []
    config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSIONS)
    delay = FIRST_DELAY_SECONDS
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = llm._get_client().models.embed_content(model=MODEL, contents=texts, config=config)
            vectors = [e.values for e in result.embeddings]
            if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
                raise llm.LLMError("Gemini returned embeddings of the wrong size.")
            return vectors
        except errors.APIError as e:
            if e.code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS:
                raise llm.LLMError(_explain(e)) from e
        except httpx.TransportError as e:
            if attempt == MAX_ATTEMPTS:
                raise llm.LLMError("Could not reach Gemini. Check your internet connection.") from e
        time.sleep(delay)
        delay = min(delay * 2, MAX_DELAY_SECONDS)


def embed_query(text: str) -> list[float]:
    return embed_texts([text], "RETRIEVAL_QUERY")[0]


def document_text(filename: str, location: str, content: str) -> str:
    """What gets embedded for a chunk: the file name helps questions like 'how does auth.py work'."""
    return f"{filename} ({location})\n{content}"


def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def backfill_embeddings(document_id: str | None = None, batch_size: int = BATCH_SIZE, on_progress=None) -> int:
    """Embed every chunk that has no embedding yet (only one document's chunks if document_id is given).
    Works in batches; returns the number of chunks embedded."""
    done = 0
    while True:
        query = (db.get_client().table("chunks")
                 .select("id, location, content, documents(filename)")
                 .is_("embedding", "null").order("id").limit(batch_size))
        if document_id:
            query = query.eq("document_id", document_id)
        rows = query.execute().data
        if not rows:
            return done
        texts = [document_text(r["documents"]["filename"], r["location"], r["content"]) for r in rows]
        vectors = embed_texts(texts, "RETRIEVAL_DOCUMENT")
        items = [{"id": r["id"], "embedding": to_pgvector(v)} for r, v in zip(rows, vectors)]
        updated = db.get_client().rpc("set_chunk_embeddings", {"items": items}).execute().data
        if not updated:
            raise RuntimeError("Embeddings could not be saved. Did you run the vector part of sql/schema.sql?")
        done += len(rows)
        if on_progress:
            on_progress(done)


def _explain(error: errors.APIError) -> str:
    if error.code == 404:
        return f"Embedding model '{MODEL}' was not found for this API key."
    return llm._explain(error)
