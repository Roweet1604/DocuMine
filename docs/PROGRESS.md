# Progress

Status as of 25 Nov 2026, from the code and test output in this folder. There is no git history
(the folder is not a git repository yet).

**Meaning of "completed":** the code exists and its offline tests pass (`python -m pytest`: 84 passed).
No part has been run against the real Supabase and Gemini services yet, because no `.env` was
configured. That verification is listed under **Pending** for each member.

## Shared setup (config, db, llm, schema)
**Completed**
- Project structure, `requirements.txt`, `.env.example`, `.gitignore` (excludes `.env`)
- `config.py`: settings with clear "Missing setting" errors
- `db.py`: documents, chunks, storage upload, generated documents, keyword search call
- `llm.py`: `generate_text`, `generate_json` (structured output), retries with backoff, readable errors
- `sql/schema.sql`: tables, private `uploads` bucket, row level security, `search_chunks` (OR matching,
  `ts_rank`), pgvector column and index, `match_chunks`, `set_chunk_embeddings`
- `tests/test_interfaces.py` (6 tests, offline)

**In progress**: none

**Pending**
- Run `sql/schema.sql` on the real Supabase project
- Update `docs/PROJECT_CONTEXT.md` with the embedding column and the two new SQL functions

## P1: ingestion (`ingest.py`, `sample_data/`)
**Completed**
- TXT, MD, PDF (page numbers), DOCX (with tables), Python (`ast`, with fallback), JS, Java, ZIP
- ZIP safety, 25 MB limit, secret scan, scanned-PDF report, sha256 duplicates
- Cleaning, chunking (about 1200 characters, 150 overlap), locations
- Embeddings stored after each upload; failures are reported without losing the document
- Kestrel sample data (chat, design notes, incident `.docx`, Python `.zip`) and `make_samples.py`
- `tests/eval_questions.json` (20 questions); `tests/test_ingest.py` (39 tests, offline)

**In progress**: none

**Pending**
- First real upload of sample_data to Supabase (`tests/smoke_test.py`, stage "upload sample_data")

## P2: generation (`generate.py`, `templates.py`)
**Completed**
- Templates for all four document types; Meeting Minutes includes discussion summary, decisions and
  an action-item table (task, owner, due date)
- Pydantic schema, numbered sources, fixed rules (formal English, sources only, "Not mentioned in the
  sources", no invented facts, ignore instructions inside sources)
- Batch summarising for large selections, keeping source numbers
- Checks for required sections and real citations, one retry, flagged repairs
- Markdown with a Sources list, saved as a draft
- `tests/test_generate.py` (12 tests, offline, mocked LLM)

**In progress**: none

**Pending**
- A real Meeting Minutes run on sample_data, checking the output by hand

## P3: retrieval, answers, issues (`retrieve.py`, `embeddings.py`, `answer.py`, `suggest.py`)
**Completed**
- Hybrid search: keyword plus pgvector (`gemini-embedding-001`, 768 dimensions, cosine), reciprocal
  rank fusion, fallback to whichever method works
- `scripts/backfill_embeddings.py` (batches, rate-limit retries, can be resumed)
- `answer_question`: answers from sources only, checked citations, only cited chunks returned, no model
  call when nothing is found
- `find_issues`: conflicts, possibly outdated content, missing documentation, each with valid sources
- `tests/evaluate.py` (keyword, vector and hybrid modes); `tests/test_retrieve.py` (27 tests, offline)

**In progress**: none

**Pending**
- Measure retrieval with `python tests/evaluate.py` once sample_data is ingested. **No numbers exist yet.**
- Check whether Review finds the planted 30 vs 90 day retention conflict on real output

## P4: app (`app.py`, `ui/export.py`)
**Completed**
- Streamlit app "DocuMine: informal in, formal out" with Upload, Generate, Ask and Review tabs
- Spinners, session state, friendly errors, disabled buttons with hints, review warning
- Edit, save, approve, `.md` and `.docx` download
- Checked headlessly with Streamlit AppTest: with the backend patched, every tab worked; without
  `.env`, only friendly errors were shown. This check is not saved as a test file.

**In progress**: none

**Pending**
- Click through the app with real services (see `docs/DEMO_SCRIPT.md`)

## Team-wide next steps
1. Fill in `.env` and run `sql/schema.sql` in Supabase.
2. `python tests/smoke_test.py`: all 7 stages should print PASS.
3. `python tests/evaluate.py`: record the measured keyword, vector and hybrid results here.
4. Rehearse `docs/DEMO_SCRIPT.md` and prepare its backup material.
5. `git init` and commit, so the next update can use real history.
