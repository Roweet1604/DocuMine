"""End-to-end smoke test against the REAL Supabase and Gemini services.

Flow: upload sample_data -> generate Meeting Minutes -> edit, approve and download -> ask three
questions -> review possible issues. Prints PASS / FAIL / SKIP per stage.
Run:  python tests/smoke_test.py      (needs .env and sql/schema.sql applied)
Note: it writes real rows (sample documents are reused if already uploaded; one generated doc is added).
"""

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ["kestrel_team_chat.txt", "kestrel_design_notes.md", "kestrel_incident_INC-007.docx", "kestrel_service.zip"]
QUESTIONS = [
    "Which database did the team decide to use for the sensor readings?",
    "What was the root cause of incident INC-007?",
    "After how many minutes without data is a sensor considered stale?",
]


class Stage:
    results = []

    def __init__(self, name: str, needs: list[str] | None = None):
        self.name, self.needs = name, needs or []

    def run(self, action):
        failed = [n for n in self.needs if dict(Stage.results).get(n) != "PASS"]
        if failed:
            return self._report("SKIP", f"needs {', '.join(failed)}")
        try:
            detail = action()
            return self._report("PASS", detail)
        except Exception as e:
            return self._report("FAIL", f"{type(e).__name__}: {e}")

    def _report(self, status: str, detail) -> None:
        Stage.results.append((self.name, status))
        print(f"{status:4}  {self.name}" + (f"\n      {detail}" if detail else ""), flush=True)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    from documine import answer, config, db, generate, ingest, suggest
    from ui.export import markdown_to_docx
    import docx

    state = {}

    def settings():
        for name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
            config.require(name)
        db.list_documents()
        return "settings present, database reachable"

    def upload():
        ids, chunks, notes = {}, 0, []
        for name in SAMPLES:
            result = ingest.ingest_file(name, (ROOT / "sample_data" / name).read_bytes())
            check(result["document_ids"], f"{name}: nothing stored, skipped: {result['skipped']}")
            problems = [s for s in result["skipped"] if "already uploaded" not in s]
            check(not problems, f"{name}: {problems}")
            ids[name] = result["document_ids"]
            chunks += result["chunk_count"]
            notes += result["skipped"]
        state["ids"] = ids
        reused = len(notes)
        return f"{sum(map(len, ids.values()))} documents ({reused} reused), {chunks} new chunks"

    def embedded():
        all_ids = [i for ids in state["ids"].values() for i in ids]
        missing = (db.get_client().table("chunks").select("id", count="exact")
                   .in_("document_id", all_ids).is_("embedding", "null").execute().count)
        check(missing == 0, f"{missing} chunks have no embedding; run python scripts/backfill_embeddings.py")
        return "every sample chunk has an embedding"

    def minutes():
        result = generate.generate_document("Meeting Minutes", state["ids"]["kestrel_team_chat.txt"])
        md = result["markdown"]
        for heading in ("Discussion Summary", "Decisions", "Action Items"):
            check(f"## {heading}" in md, f"missing section {heading}")
        check(result["sources"], "no sources cited")
        check("Please check" not in md, "validation still found problems after the retry")
        state["generated"] = result
        return f"'{result['title']}', {len(result['sources'])} sources cited"

    def edit_and_download():
        generated = state["generated"]
        edited = generated["markdown"] + "\n_Reviewed in smoke test._\n"
        db.update_generated(generated["id"], edited, "approved")
        row = next(d for d in db.list_generated() if d["id"] == generated["id"])
        check(row["status"] == "approved" and "Reviewed in smoke test" in row["markdown"], "edit not saved")
        document = docx.Document(io.BytesIO(markdown_to_docx(edited)))
        check(any(p.style.name.startswith("Heading") for p in document.paragraphs), "docx has no headings")
        check(document.tables, "docx has no action-item table")
        return "saved as approved; .md and .docx exports OK"

    def ask():
        lines = []
        for question in QUESTIONS:
            result = answer.answer_question(question)
            check(result["answer"] != answer.NOT_FOUND, f"not found: {question}")
            check(result["sources"], f"no sources cited: {question}")
            first_line = result["answer"].splitlines()[0][:110]
            lines.append(f"{question} -> {first_line} ({', '.join(s['filename'] for s in result['sources'])})")
        return "\n      ".join(lines)

    def review():
        ids = state["ids"]["kestrel_team_chat.txt"] + state["ids"]["kestrel_design_notes.md"]
        issues = suggest.find_issues(ids)
        check(issues, "no possible issues found")
        retention = any("30" in i["description"] and "90" in i["description"] for i in issues)
        return (f"{len(issues)} possible issues; planted 30 vs 90 day retention conflict "
                f"{'found' if retention else 'NOT found'}")

    Stage("settings").run(settings)
    Stage("upload sample_data", ["settings"]).run(upload)
    Stage("embeddings stored", ["upload sample_data"]).run(embedded)
    Stage("generate Meeting Minutes", ["upload sample_data"]).run(minutes)
    Stage("edit, approve and download", ["generate Meeting Minutes"]).run(edit_and_download)
    Stage("ask three questions", ["upload sample_data"]).run(ask)
    Stage("review possible issues", ["upload sample_data"]).run(review)

    statuses = [status for _, status in Stage.results]
    print(f"\n{statuses.count('PASS')} passed, {statuses.count('FAIL')} failed, {statuses.count('SKIP')} skipped")
    return 0 if statuses.count("PASS") == len(statuses) else 1


if __name__ == "__main__":
    sys.exit(main())
