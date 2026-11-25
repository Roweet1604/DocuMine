"""Owner: P3. Hybrid search over the knowledge repository.

Keyword search (PostgreSQL full-text) and vector search (pgvector, cosine) are combined with
reciprocal rank fusion. If one of them fails, the other one is used alone, so keyword search
keeps working without embeddings.
"""

import logging
import re

from documine import db, embeddings

CANDIDATES = 20   # results taken from each method before fusion
RRF_K = 60        # standard reciprocal rank fusion constant


def search(query: str, top_k: int = 8) -> list[dict]:
    """Return chunks {id, document_id, filename, location, content} plus 'score', best first.
    score is the fused RRF score (higher is better)."""
    if not query or not query.strip():
        return []
    query = query.strip()
    result_lists, failures = [], []
    for name, method in (("keyword", keyword_search), ("vector", vector_search)):
        try:
            result_lists.append(method(query, CANDIDATES))
        except Exception as e:
            logging.warning("%s search failed, using the other method only: %s", name, e)
            failures.append(e)
    if not result_lists:
        raise failures[0]
    return reciprocal_rank_fusion(result_lists, top_k)


def keyword_search(query: str, k: int) -> list[dict]:
    """Full-text search (any word matches), best ts_rank first."""
    rows = [_row(r) for r in db.search_chunks(query, k)]
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def vector_search(query: str, k: int) -> list[dict]:
    """Nearest chunks by cosine distance to the question's embedding."""
    vector = embeddings.embed_query(query)
    rows = db.get_client().rpc("match_chunks", {"query_embedding": embeddings.to_pgvector(vector), "k": k}).execute().data
    return [_row(r) for r in rows]


def reciprocal_rank_fusion(result_lists: list[list[dict]], top_k: int) -> list[dict]:
    """score = sum of 1 / (RRF_K + rank) over the lists a chunk appears in."""
    fused = {}
    for results in result_lists:
        for rank, row in enumerate(results, 1):
            entry = fused.setdefault(row["id"], {**row, "score": 0.0})
            entry["score"] += 1 / (RRF_K + rank)
    return sorted(fused.values(), key=lambda r: (-r["score"], r["id"]))[:top_k]


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "filename": row["filename"],
        "location": row["location"],
        "content": row["content"],
        "score": float(row["score"]),
    }


def format_sources(numbered: dict[int, dict]) -> str:
    """Numbered <source> blocks for prompts. Used by answer.py and suggest.py."""
    blocks = []
    for number, chunk in numbered.items():
        filename = _escape(chunk["filename"]).replace('"', "'")
        location = _escape(chunk["location"]).replace('"', "'")
        blocks.append(f'<source number="{number}" file="{filename}" location="{location}">\n'
                      f'{_escape(chunk["content"])}\n</source>')
    return "\n\n".join(blocks)


def _escape(text: str) -> str:
    """Stop source text from closing or faking a <source> tag."""
    return re.sub(r"<(/?\s*source)", r"&lt;\1", text, flags=re.IGNORECASE)
