# DocuMine – Project Context

**Problem Statement 40:** a GenAI app that turns technical discussions, project notes, source code and
engineering records into structured technical documents and a searchable knowledge repository.

**Our focus:** informal, mixed input becomes a formal document in one click. No prompt writing,
sources always shown, and a human reviews every document (draft -> approved).

## Stack
Python 3.11+, Streamlit, Supabase (PostgreSQL + private Storage), google-genai (`gemini-3.5-flash-lite`),
pypdf, python-docx, ast, zipfile, pydantic, python-dotenv, pytest. Search v1 = PostgreSQL full-text search.
No LangChain, no extra frameworks.

## Owners
| File | Owner |
|---|---|
| app.py | P4 |
| documine/ingest.py | P1 |
| documine/generate.py, documine/templates.py | P2 |
| documine/retrieve.py, documine/answer.py, documine/suggest.py | P3 |
| documine/config.py, db.py, llm.py, sql/schema.sql | setup (shared – ask before changing) |

## Rules
- Only `llm.py` talks to Gemini. Only `db.py` talks to Supabase.
- **Nobody changes a fixed interface without telling the whole team.**
- Run `python -m pytest` before pushing; `tests/test_interfaces.py` checks the shapes below.

## Fixed interfaces

```text
chunk = {id, document_id, filename, location, content}
        id is an int (increasing, so sorting by id keeps file order); document_id is a uuid string.

ingest.ingest_file(filename: str, data: bytes) -> {document_ids: list[str], chunk_count: int, skipped: list[str]}

db.upload_file(storage_path, data, content_type="application/octet-stream") -> storage_path
db.find_document_by_sha256(sha256) -> dict | None
db.insert_document(filename, file_type, storage_path, sha256) -> id
db.insert_chunks(document_id, chunks: list[{location, content}]) -> int
db.list_documents() -> list[dict]
db.get_chunks(document_ids: list[str]) -> list[chunk]
db.search_chunks(query, k=8) -> list[chunk plus score]
db.save_generated(doc_type, title, markdown, source_ids) -> id
db.list_generated() -> list[dict]
db.update_generated(id, markdown, status)

llm.generate_text(prompt: str) -> str
llm.generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel
        Both raise llm.LLMError with a message that is safe to show in the UI.

generate.DOC_TYPES = ["Meeting Minutes", "Technical Design Document", "Code Documentation", "Project Report"]
generate.generate_document(doc_type: str, document_ids: list[str]) -> {id, title, markdown, sources: list[chunk]}

retrieve.search(query: str, top_k: int = 8) -> list[chunk plus score]
answer.answer_question(question: str) -> {answer: str, sources: list[chunk]}
suggest.find_issues(document_ids: list[str]) -> list[{type, description, sources: list[chunk]}]
```

## Database (sql/schema.sql)
- `documents(id uuid, filename, file_type, storage_path, sha256 unique, uploaded_at)`
- `chunks(id bigint identity, document_id -> documents on delete cascade, location, content, tsv generated + GIN index)`
- `generated_docs(id uuid, doc_type, title, markdown, source_ids jsonb, status default 'draft', created_at)`
- Private storage bucket `uploads`. RLS on for all tables; the app uses the secret key.
- `search_chunks(q, k)` matches ANY query word (OR), ranks with `ts_rank`, returns nothing for empty queries.
