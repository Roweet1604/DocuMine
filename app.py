"""Owner: P4. Streamlit UI. Run with: streamlit run app.py"""

import logging
import re

import streamlit as st

from documine import answer, db, generate, ingest, suggest
from ui.export import markdown_to_docx

UPLOAD_TYPES = ["txt", "md", "pdf", "docx", "py", "js", "java", "zip"]

st.set_page_config(page_title="DocuMine", page_icon="📄", layout="wide")

for key, default in {
    "upload_results": [],   # [(filename, ingest result)]
    "generated": None,      # {id, title, markdown, sources, status}
    "editor": "",
    "answer": None,
    "issues": None,
}.items():
    st.session_state.setdefault(key, default)


def run(action, doing: str):
    """Run an action and show a friendly error instead of a traceback. Returns None on failure."""
    try:
        return action()
    except (ValueError, RuntimeError) as e:  # our modules raise these with user-friendly messages
        st.error(str(e))
    except Exception:
        logging.exception("Error while %s", doing)
        st.error(f"Something went wrong while {doing}. Check your connection and settings, then try again.")
    return None


@st.cache_data(ttl=30, show_spinner=False)
def load_documents() -> list[dict]:
    return db.list_documents()


def documents() -> list[dict]:
    return run(load_documents, "loading the stored files") or []


def file_picker(label: str, key: str, docs: list[dict]) -> list[str]:
    names = {d["id"]: d["filename"] for d in docs}
    if not docs:
        st.caption("No files stored yet. Add some in the Upload tab.")
    return st.multiselect(label, options=list(names), format_func=names.get, key=key,
                          placeholder="Choose one or more files")


def show_sources(sources: list[dict]) -> None:
    for i, source in enumerate(sources, 1):
        number = source.get("number", i)
        with st.expander(f"[{number}] {source['filename']} · {source['location']}"):
            st.code(source["content"], language=None, wrap_lines=True)


def safe_filename(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "document"


# ---------- page ----------

st.title("DocuMine: informal in, formal out")
st.caption("Turn chats, notes, code and records into formal technical documents, with sources.")
st.warning("AI drafts need human review. Do not upload confidential data.", icon="⚠️")

stored_docs = documents()  # loaded once per run, shared by all tabs
upload_tab, generate_tab, ask_tab, review_tab = st.tabs(["Upload", "Generate", "Ask", "Review"])

# ---------- Upload ----------

with upload_tab:
    files = st.file_uploader("Add project files", type=UPLOAD_TYPES, accept_multiple_files=True,
                             help="Text, Markdown, PDF, Word, Python, JavaScript, Java or a ZIP of a project. Max 25 MB each.")
    if st.button("Process files", type="primary", disabled=not files):
        results = []
        with st.spinner("Reading, cleaning and indexing files..."):
            for f in files:
                result = run(lambda: ingest.ingest_file(f.name, f.getvalue()), f"processing {f.name}")
                if result is not None:
                    results.append((f.name, result))
        st.session_state.upload_results = results
        load_documents.clear()
        stored_docs = documents()
    if not files:
        st.caption("Choose files above to enable processing.")

    for name, result in st.session_state.upload_results:
        stored = len(result["document_ids"])
        if stored:
            st.success(f"**{name}**: {stored} document(s), {result['chunk_count']} new chunks")
        else:
            st.info(f"**{name}**: nothing new stored")
        if result["skipped"]:
            with st.expander(f"Skipped or reused items ({len(result['skipped'])})"):
                for reason in result["skipped"]:
                    st.write(f"- {reason}")

    st.subheader("Stored files")
    if stored_docs:
        st.dataframe([{"File": d["filename"], "Type": d["file_type"], "Uploaded": d["uploaded_at"][:16].replace("T", " ")}
                      for d in stored_docs], hide_index=True, width="stretch")
    else:
        st.caption("Nothing stored yet.")

# ---------- Generate ----------

with generate_tab:
    left, right = st.columns([1, 2])
    with left:
        doc_type = st.selectbox("Document type", generate.DOC_TYPES)
        selected = file_picker("Source files", "generate_files", stored_docs)
        if st.button("Generate", type="primary", disabled=not selected, width="stretch"):
            with st.spinner(f"Writing {doc_type}... this can take a minute."):
                result = run(lambda: generate.generate_document(doc_type, selected), "generating the document")
            if result:
                st.session_state.generated = {**result, "status": "draft"}
                st.session_state.editor = result["markdown"]
        if not selected:
            st.caption("Select at least one file to generate.")

    current = st.session_state.generated
    with right:
        if not current:
            st.info("Pick a document type and files, then click Generate. No prompt writing needed.")
        else:
            st.markdown(f"**{current['title']}** · status: `{current['status']}`")
            edit_tab, preview_tab = st.tabs(["Edit", "Preview"])
            with edit_tab:
                st.text_area("Markdown", key="editor", height=500, label_visibility="collapsed")
            with preview_tab:
                st.markdown(st.session_state.editor)

            text = st.session_state.editor
            save_col, approve_col, md_col, docx_col = st.columns(4)
            if save_col.button("Save", disabled=not text.strip(), width="stretch"):
                if run(lambda: db.update_generated(current["id"], text, "draft") or True, "saving"):
                    current.update(markdown=text, status="draft")
                    st.toast("Saved as draft")
            if approve_col.button("Approve", type="primary", disabled=not text.strip(), width="stretch"):
                if run(lambda: db.update_generated(current["id"], text, "approved") or True, "approving"):
                    current.update(markdown=text, status="approved")
                    st.toast("Approved")
            name = safe_filename(current["title"])
            md_col.download_button("Download .md", text, file_name=f"{name}.md", mime="text/markdown",
                                   width="stretch")
            docx_col.download_button(
                "Download .docx", markdown_to_docx(text), file_name=f"{name}.docx", width="stretch",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

            st.subheader("Sources")
            show_sources(current["sources"])

# ---------- Ask ----------

with ask_tab:
    question = st.text_input("Ask a question about the project files",
                             placeholder="e.g. How long are raw sensor readings kept?")
    if st.button("Ask", type="primary", disabled=not question.strip()):
        with st.spinner("Searching the project files..."):
            st.session_state.answer = run(lambda: answer.answer_question(question), "answering")
    if not question.strip():
        st.caption("Type a question to enable the Ask button.")

    if st.session_state.answer:
        st.markdown(st.session_state.answer["answer"])
        if st.session_state.answer["sources"]:
            st.subheader("Sources")
            show_sources(st.session_state.answer["sources"])

# ---------- Review ----------

with review_tab:
    st.subheader("Possible issues for human review")
    st.caption("Conflicting statements, possibly outdated content and missing documentation. "
               "These are suggestions: check each one against its sources.")
    review_files = file_picker("Files to check", "review_files", stored_docs)
    if st.button("Find possible issues", type="primary", disabled=not review_files):
        with st.spinner("Checking the files..."):
            st.session_state.issues = run(lambda: suggest.find_issues(review_files), "checking for issues")
    if not review_files:
        st.caption("Select files to enable the check.")

    if st.session_state.issues is not None:
        if not st.session_state.issues:
            st.success("No possible issues found in the selected files.")
        for issue in st.session_state.issues:
            st.markdown(f"**{issue['type']}**: {issue['description']}")
            show_sources(issue["sources"])

    st.subheader("Saved documents")
    saved = run(db.list_generated, "loading saved documents") or []
    if saved:
        st.dataframe([{"Title": d["title"], "Type": d["doc_type"], "Status": d["status"],
                       "Created": d["created_at"][:16].replace("T", " ")} for d in saved],
                     hide_index=True, width="stretch")
    else:
        st.caption("No saved documents yet.")
