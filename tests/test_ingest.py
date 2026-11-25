"""Tests for documine/ingest.py. No network: the database is replaced with an in-memory fake."""

import io
import json
import zipfile
from pathlib import Path

import docx
import pytest

from documine import ingest

SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"


# ---------- helpers ----------

def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # set directly so unsafe names like "../x" are kept as-is
            archive.writestr(info, data)
    return buffer.getvalue()


def make_pdf(page_texts: list[str]) -> bytes:
    """A tiny valid PDF with one line of Helvetica text per page ('' = page with no text)."""
    count = len(page_texts)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def paragraphs(count: int, length: int = 300) -> str:
    return "\n\n".join(f"Paragraph {i}." + " word" * (length // 5) for i in range(count))


class FakeDB:
    def __init__(self):
        self.documents = {}  # sha256 -> row
        self.chunks = {}
        self.uploads = {}
        self.calls = []

    def find_document_by_sha256(self, sha256):
        return self.documents.get(sha256)

    def upload_file(self, storage_path, data, content_type="application/octet-stream"):
        self.calls.append("upload_file")
        self.uploads[storage_path] = data
        return storage_path

    def insert_document(self, filename, file_type, storage_path, sha256):
        self.calls.append("insert_document")
        document_id = f"doc-{len(self.documents) + 1}"
        self.documents[sha256] = {"id": document_id, "filename": filename, "file_type": file_type,
                                  "storage_path": storage_path}
        return document_id

    def insert_chunks(self, document_id, chunks):
        self.calls.append("insert_chunks")
        self.chunks[document_id] = chunks
        return len(chunks)


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    for name in ("find_document_by_sha256", "upload_file", "insert_document", "insert_chunks"):
        monkeypatch.setattr(ingest.db, name, getattr(fake, name))
    fake.embedded = []
    monkeypatch.setattr(ingest.embeddings, "backfill_embeddings", fake.embedded.append)
    return fake


# ---------- cleaning ----------

def test_clean_text_keeps_line_numbers_and_removes_junk():
    raw = "a\r\nb\x00c\u200b\r\n\r\n\r\n  d   e  \t\n"
    cleaned = ingest.clean_text(raw)
    assert cleaned.split("\n") == ["a", "bc", "", "", " d e", ""]


def test_clean_text_keeps_code_indentation():
    assert ingest.clean_text("def f():\n    return  1\n", code=True) == "def f():\n    return  1\n"


def test_binary_text_file_is_skipped():
    with pytest.raises(ingest.SkipFile, match="binary"):
        ingest.parse_file("data.txt", b"abc\x00\x01\x02")


def test_unsupported_type_is_skipped():
    with pytest.raises(ingest.SkipFile, match="unsupported"):
        ingest.parse_file("photo.png", b"\x89PNG")


# ---------- chunking ----------

def test_chunks_respect_size_overlap_and_paragraphs():
    text = paragraphs(20)
    chunks = ingest.parse_file("notes.txt", text.encode())
    assert len(chunks) > 3
    assert all(len(c["content"]) <= ingest.CHUNK_SIZE for c in chunks)
    # every paragraph stays whole inside some chunk
    for paragraph in text.split("\n\n"):
        assert any(paragraph in c["content"] for c in chunks)
    # consecutive chunks overlap: the next chunk starts with the end of the previous one
    for previous, current in zip(chunks, chunks[1:]):
        overlap = current["content"].split("\n")[0]
        assert previous["content"].endswith(overlap)
        assert 0 < len(overlap) <= ingest.CHUNK_OVERLAP


def test_chunk_locations_are_line_ranges():
    text = "first line\nsecond line\n\nfourth line\n"
    chunks = ingest.parse_file("notes.md", text.encode())
    assert chunks == [{"location": "lines 1-4", "content": "first line\nsecond line\n\nfourth line"}]


def test_one_very_long_line_is_split_by_words():
    text = "token " * 2000
    chunks = ingest.parse_file("log.txt", text.encode())
    assert len(chunks) > 5
    assert all(len(c["content"]) <= ingest.CHUNK_SIZE for c in chunks)
    assert all(c["location"] == "line 1" for c in chunks)


def test_python_is_split_at_function_boundaries():
    body = "    x = 1\n" * 50  # about 500 characters per function
    source = "import os\n\n\n" + "".join(f"def f{i}():\n{body}    return x\n\n\n" for i in range(4))
    chunks = ingest.parse_file("module.py", source.encode())
    lines = source.split("\n")
    for i in range(4):
        start = lines.index(f"def f{i}():") + 1
        function_text = "\n".join(lines[start - 1:start + 51])
        assert any(function_text in c["content"] for c in chunks), f"f{i} was split"
    assert chunks[0]["location"].startswith("lines 1-")


def test_python_big_class_is_split_by_method():
    methods = "".join(f"    def m{i}(self):\n" + "        y = 2\n" * 60 + "\n" for i in range(3))
    source = "class Big:\n    '''Doc.'''\n\n" + methods
    chunks = ingest.parse_file("big.py", source.encode())
    assert len(chunks) >= 3
    assert all(len(c["content"]) <= ingest.CHUNK_SIZE for c in chunks)
    for i in range(3):
        assert any(f"def m{i}(self):" in c["content"] for c in chunks)


def test_python_syntax_error_falls_back_to_line_blocks():
    source = "def broken(:\n    pass\n\nprint('still here')\n"
    chunks = ingest.parse_file("broken.py", source.encode())
    assert chunks[0]["location"] == "lines 1-4"
    assert "still here" in chunks[0]["content"]


@pytest.mark.parametrize("filename", ["app.js", "Main.java"])
def test_js_and_java_use_line_blocks(filename):
    source = ("function a() {\n  return 1;\n}\n\n" * 60).encode()
    chunks = ingest.parse_file(filename, source)
    assert len(chunks) > 1
    assert all(c["location"].startswith("lines ") for c in chunks)
    assert all(len(c["content"]) <= ingest.CHUNK_SIZE for c in chunks)


# ---------- PDF and DOCX ----------

def test_pdf_keeps_page_numbers():
    chunks = ingest.parse_file("report.pdf", make_pdf(["Hello page one", "", "Third page text"]))
    assert [c["location"] for c in chunks] == ["page 1", "page 3"]
    assert "Third page text" in chunks[1]["content"]


def test_scanned_pdf_is_reported_not_failed():
    with pytest.raises(ingest.SkipFile, match="scanned PDF"):
        ingest.parse_file("scan.pdf", make_pdf(["", ""]))


def test_broken_pdf_is_reported():
    with pytest.raises(ingest.SkipFile, match="could not read PDF"):
        ingest.parse_file("bad.pdf", b"not a pdf")


def test_docx_includes_tables_in_order():
    document = docx.Document()
    document.add_paragraph("Intro paragraph")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Owner", "Task"
    table.rows[1].cells[0].text, table.rows[1].cells[1].text = "Omar", "Fix firmware"
    document.add_paragraph("Closing paragraph")
    buffer = io.BytesIO()
    document.save(buffer)

    chunks = ingest.parse_file("notes.docx", buffer.getvalue())
    assert chunks == [{
        "location": "paragraphs 1-3",
        "content": "Intro paragraph\nOwner | Task\nOmar | Fix firmware\nClosing paragraph",
    }]


# ---------- secrets ----------

@pytest.mark.parametrize("filename, text", [
    ("settings.py", 'API_KEY = "abcd1234efgh5678"\n'),
    ("notes.txt", "db password: hunter2hunter\n"),
    ("deploy.md", "DB_PASSWORD=s3cretvalue99\n"),
    ("key.txt", "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n"),
    ("chat.txt", "use key AKIAABCDEFGHIJKLMNOP for now\n"),
])
def test_secrets_are_skipped(filename, text):
    with pytest.raises(ingest.SkipFile, match="password or API key"):
        ingest.parse_file(filename, text.encode())


@pytest.mark.parametrize("filename, text", [
    ("chat.txt", "we still need a password reset flow\n"),
    ("setup.md", "GEMINI_API_KEY=your-gemini-api-key\n"),
    ("login.py", 'password = request.form["password"]\ntoken: str = get_token()\n'),
])
def test_normal_text_is_not_flagged(filename, text):
    assert ingest.parse_file(filename, text.encode())


# ---------- ZIP safety ----------

def test_zip_skips_unsafe_and_unwanted_entries(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("read_zip must never extract to disk")
    monkeypatch.setattr(zipfile.ZipFile, "extract", fail)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", fail)

    data = make_zip({
        "src/app.py": b"print('ok')\n",
        "../evil.py": b"print('escape')\n",
        "/etc/passwd.txt": b"root\n",
        "C:/windows/x.txt": b"x\n",
        "a/../../b.py": b"x = 1\n",
        ".git/config.txt": b"[core]\n",
        "node_modules/lib/index.js": b"module.exports = 1\n",
        ".venv/lib/site.py": b"x = 1\n",
        "venv/bin/activate.py": b"x = 1\n",
        ".env": b"SECRET=1\n",
        "config/.env.local": b"SECRET=1\n",
        "keys/id_rsa": b"key\n",
        "certs/server.pem": b"key\n",
        "logo.png": b"\x89PNG\x00\x00",
        "inner.zip": b"PK\x03\x04",
    })
    files, skipped = ingest.read_zip("project.zip", data)
    assert [name for name, _ in files] == ["src/app.py"]
    text = "\n".join(skipped)
    for expected in ["../evil.py: unsafe", "/etc/passwd.txt: unsafe", "C:/windows/x.txt: unsafe",
                     "a/../../b.py: unsafe", ".env: environment file", ".env.local: environment file",
                     "id_rsa: key or credentials", "server.pem: key or credentials",
                     "logo.png: unsupported", "inner.zip: nested ZIP",
                     "ignored 4 files in .git, node_modules"]:
        assert expected in text


def test_zip_file_count_limit(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ZIP_FILES", 3)
    data = make_zip({f"f{i}.txt": b"hello" for i in range(10)})
    files, skipped = ingest.read_zip("many.zip", data)
    assert len(files) == 3
    assert any("stopped after 3 files" in s for s in skipped)


def test_zip_entry_count_limit(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ZIP_ENTRIES", 5)
    data = make_zip({f"f{i}.txt": b"hello" for i in range(10)})
    files, skipped = ingest.read_zip("many.zip", data)
    assert files == []
    assert "too many entries" in skipped[0]


def test_zip_total_uncompressed_size_limit(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ZIP_TOTAL_BYTES", 2500)
    data = make_zip({f"f{i}.txt": b"a" * 1000 for i in range(5)})  # compresses to almost nothing
    files, skipped = ingest.read_zip("bomb.zip", data)
    assert len(files) == 2
    assert any("total uncompressed size limit" in s for s in skipped)


def test_zip_member_size_limit(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FILE_BYTES", 100)
    data = make_zip({"big.txt": b"a" * 500, "small.txt": b"hi"})
    files, skipped = ingest.read_zip("x.zip", data)
    assert [name for name, _ in files] == ["small.txt"]
    assert any("big.txt: larger than" in s for s in skipped)


def test_invalid_zip_is_reported():
    files, skipped = ingest.read_zip("broken.zip", b"not a zip")
    assert files == [] and "not a valid ZIP" in skipped[0]


# ---------- ingest_file with a fake database ----------

def test_ingest_uploads_then_inserts(fake_db):
    result = ingest.ingest_file("notes.txt", b"hello team\n")
    assert result == {"document_ids": ["doc-1"], "chunk_count": 1, "skipped": []}
    assert fake_db.calls == ["upload_file", "insert_document", "insert_chunks"]
    (path,) = fake_db.uploads
    assert path.endswith("/notes.txt") and len(path.split("/")[0]) == 64  # "<sha256>/notes.txt"


def test_new_document_is_embedded(fake_db):
    ingest.ingest_file("notes.txt", b"hello team\n")
    assert fake_db.embedded == ["doc-1"]


def test_embedding_failure_keeps_the_document(fake_db, monkeypatch):
    def fail(document_id):
        raise RuntimeError("Gemini rate limit reached")
    monkeypatch.setattr(ingest.embeddings, "backfill_embeddings", fail)
    result = ingest.ingest_file("notes.txt", b"hello team\n")
    assert result["document_ids"] == ["doc-1"] and result["chunk_count"] == 1
    assert "embeddings failed (Gemini rate limit reached)" in result["skipped"][0]
    assert "backfill_embeddings.py" in result["skipped"][0]


def test_duplicate_upload_is_detected(fake_db):
    ingest.ingest_file("notes.txt", b"hello team\n")
    result = ingest.ingest_file("copy_of_notes.txt", b"hello team\n")
    assert result["document_ids"] == ["doc-1"]
    assert result["chunk_count"] == 0
    assert "already uploaded as notes.txt" in result["skipped"][0]
    assert fake_db.calls.count("upload_file") == 1


def test_file_over_size_limit_is_rejected(fake_db, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FILE_BYTES", 10)
    result = ingest.ingest_file("big.txt", b"x" * 11)
    assert result["document_ids"] == [] and "larger than" in result["skipped"][0]
    assert fake_db.calls == []


def test_secret_file_is_never_uploaded(fake_db):
    result = ingest.ingest_file("settings.py", b'API_KEY = "abcd1234efgh5678"\n')
    assert result["document_ids"] == [] and "password or API key" in result["skipped"][0]
    assert fake_db.calls == []


def test_zip_members_become_documents(fake_db):
    data = make_zip({"src/a.py": b"def a():\n    return 1\n", "README.md": b"# Readme\n", ".env": b"X=1\n"})
    result = ingest.ingest_file("proj.zip", data)
    assert len(result["document_ids"]) == 2
    filenames = sorted(d["filename"] for d in fake_db.documents.values())
    assert filenames == ["proj.zip/README.md", "proj.zip/src/a.py"]
    assert any(".env: environment file" in s for s in result["skipped"])


# ---------- sample data ----------

def test_sample_data_ingests_cleanly(fake_db):
    for path in sorted(SAMPLE_DIR.iterdir()):
        if path.is_file() and path.suffix in {".txt", ".md", ".docx", ".zip"}:
            result = ingest.ingest_file(path.name, path.read_bytes())
            assert result["skipped"] == [], result["skipped"]
            assert result["chunk_count"] > 0
    assert len(fake_db.documents) == 10  # chat, notes, incident + 7 files in the ZIP


def test_eval_questions_point_at_sample_files():
    questions = json.loads((Path(__file__).parent / "eval_questions.json").read_text(encoding="utf-8"))
    assert len(questions) == 20
    known = {p.name for p in SAMPLE_DIR.iterdir() if p.is_file()}
    with zipfile.ZipFile(SAMPLE_DIR / "kestrel_service.zip") as archive:
        known |= {f"kestrel_service.zip/{name}" for name in archive.namelist()}
    for q in questions:
        assert q["question"] and q["expected_answer"]
        assert q["expected_filename"] in known, q["expected_filename"]
