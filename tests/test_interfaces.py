"""Checks that every module keeps the fixed interface shapes from docs/PROJECT_CONTEXT.md.
Runs offline: the database, Gemini and embeddings are replaced with small fakes."""

import pytest

from documine import answer, db, embeddings, generate, ingest, llm, retrieve, suggest
from documine.templates import TEMPLATES

CHUNK_KEYS = {"id", "document_id", "filename", "location", "content"}
CHUNK = {"id": 1, "document_id": "d1", "filename": "notes.txt", "location": "line 1",
         "content": "We decided to use PostgreSQL."}


def fake_json(prompt, schema):
    if schema is generate.GeneratedDocument:
        return schema(title="Minutes", sections=[
            generate.Section(heading=h, content="Text [1].", source_numbers=[1])
            for h, _ in TEMPLATES["Meeting Minutes"]["sections"]])
    return suggest.Issues(issues=[suggest.Issue(type="missing", description="No owner.", source_numbers=[1])])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(db, "find_document_by_sha256", lambda sha256: None)
    monkeypatch.setattr(db, "upload_file", lambda path, data, content_type="": path)
    monkeypatch.setattr(db, "insert_document", lambda *args: "d1")
    monkeypatch.setattr(db, "insert_chunks", lambda document_id, chunks: len(chunks))
    monkeypatch.setattr(db, "get_chunks", lambda ids: [CHUNK])
    monkeypatch.setattr(db, "save_generated", lambda *args: "g1")
    monkeypatch.setattr(db, "search_chunks", lambda query, k=8: [{**CHUNK, "score": 0.5}])
    monkeypatch.setattr(embeddings, "backfill_embeddings", lambda *args, **kwargs: 0)
    monkeypatch.setattr(retrieve, "vector_search", lambda query, k: [{**CHUNK, "score": 0.9}])
    monkeypatch.setattr(llm, "generate_text", lambda prompt: "We use PostgreSQL [1].")
    monkeypatch.setattr(llm, "generate_json", fake_json)


def test_ingest_shape():
    result = ingest.ingest_file("notes.txt", b"hello")
    assert set(result) == {"document_ids", "chunk_count", "skipped"}
    assert isinstance(result["document_ids"], list)
    assert isinstance(result["chunk_count"], int)


def test_doc_types():
    assert generate.DOC_TYPES == [
        "Meeting Minutes", "Technical Design Document", "Code Documentation", "Project Report"
    ]


def test_generate_shape():
    result = generate.generate_document("Meeting Minutes", ["x"])
    assert {"id", "title", "markdown", "sources"} <= set(result)
    for chunk in result["sources"]:
        assert CHUNK_KEYS <= set(chunk)


def test_search_shape():
    for chunk in retrieve.search("database schema"):
        assert CHUNK_KEYS | {"score"} <= set(chunk)


def test_answer_shape():
    result = answer.answer_question("What did we decide?")
    assert isinstance(result["answer"], str)
    assert isinstance(result["sources"], list)


def test_suggest_shape():
    for issue in suggest.find_issues(["x"]):
        assert {"type", "description", "sources"} <= set(issue)
