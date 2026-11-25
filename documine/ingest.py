"""Owner: P1. Turns an uploaded file into stored documents and searchable chunks.

Flow: size check -> (ZIP: read members safely in memory) -> parse + clean + chunk -> secret scan
-> sha256 duplicate check -> upload original to Storage -> insert document and chunks.
Everything before the duplicate check is pure Python, so tests run without network.
"""

import ast
import hashlib
import io
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath

import docx
from docx.table import Table
from pypdf import PdfReader

from documine import db, embeddings

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000                    # entries in one archive, including skipped ones
MAX_ZIP_FILES = 200                       # files ingested from one archive
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024   # uncompressed bytes read from one archive
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

CONTENT_TYPES = {
    "txt": "text/plain",
    "md": "text/markdown",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "py": "text/x-python",
    "js": "text/javascript",
    "java": "text/x-java-source",
}
TEXT_TYPES = {"txt", "md", "py", "js", "java"}
CODE_TYPES = {"py", "js", "java"}

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "site-packages",
    "__MACOSX", ".idea", ".vscode", ".tox", ".mypy_cache", ".pytest_cache",
}
KEY_FILE_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc", "credentials.json"}
KEY_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk")

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                    # AWS access key
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),                # Google API key
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),                # OpenAI-style secret key
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),            # GitHub token
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),          # Slack token
    re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{10,}"),         # Supabase secret key
    re.compile(r"\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}"),  # JWT
    # password = "hunter2hunter", "api_key": "..."  (a quoted literal value)
    re.compile(r"(?i)(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token)[\"']?\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
    # DB_PASSWORD=abc12345  (.env style line)
    re.compile(r"(?im)^\s*(export\s+)?[A-Z0-9_]*(PASSWORD|SECRET|API_KEY|TOKEN)[A-Z0-9_]*\s*=\s*[^\s\"'#]{8,}\s*$"),
]
# Only for prose: in code, "password: str" or "password = request.form[...]" is normal.
PROSE_SECRET_PATTERN = re.compile(r"(?i)\b(password|passwd|pwd|api[ _-]?key|secret key|token)\s*[:=]\s*\S{6,}")
PLACEHOLDER_WORDS = ("your", "example", "changeme", "placeholder", "xxxx", "<", "dummy")


class SkipFile(Exception):
    """Raised when a file cannot or should not be ingested. The message goes into 'skipped'."""


# ---------- public entry point ----------

def ingest_file(filename: str, data: bytes) -> dict:
    """Return {document_ids: list[str], chunk_count: int, skipped: list[str]}."""
    result = {"document_ids": [], "chunk_count": 0, "skipped": []}
    if len(data) > MAX_FILE_BYTES:
        result["skipped"].append(f"{filename}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        return result
    if file_extension(filename) == "zip":
        files, skipped = read_zip(filename, data)
        result["skipped"].extend(skipped)
        for member_name, member_data in files:
            _ingest_one(f"{filename}/{member_name}", member_data, result)
    else:
        _ingest_one(filename, data, result)
    return result


def _ingest_one(filename: str, data: bytes, result: dict) -> None:
    try:
        chunks = parse_file(filename, data)
    except SkipFile as e:
        result["skipped"].append(f"{filename}: {e}")
        return

    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.find_document_by_sha256(sha256)
    if existing:
        result["document_ids"].append(existing["id"])
        result["skipped"].append(f"{filename}: already uploaded as {existing['filename']}, reusing it")
        return

    ext = file_extension(filename)
    storage_path = f"{sha256}/{_storage_name(filename)}"
    db.upload_file(storage_path, data, CONTENT_TYPES.get(ext, "application/octet-stream"))
    document_id = db.insert_document(filename, ext, storage_path, sha256)
    result["chunk_count"] += db.insert_chunks(document_id, chunks)
    result["document_ids"].append(document_id)
    try:
        embeddings.backfill_embeddings(document_id)
    except Exception as e:
        result["skipped"].append(f"{filename}: stored, but embeddings failed ({e}). Keyword search still works; "
                                 f"run python scripts/backfill_embeddings.py later.")


# ---------- parsing ----------

def parse_file(filename: str, data: bytes) -> list[dict]:
    """Parse, clean and chunk one file. Returns [{location, content}] or raises SkipFile."""
    ext = file_extension(filename)
    if ext == "pdf":
        chunks = parse_pdf(data)
    elif ext == "docx":
        chunks = parse_docx(data)
    elif ext in TEXT_TYPES:
        text = clean_text(decode_text(data), code=ext in CODE_TYPES)
        units = python_units(text) if ext == "py" else line_units(text)
        chunks = [{"location": _location(s, e), "content": c} for s, e, c in pack_units(units)]
    else:
        raise SkipFile(f"unsupported file type '.{ext}'" if ext else "file has no extension")

    if not chunks:
        raise SkipFile("no text found")
    if contains_secret("\n".join(c["content"] for c in chunks), prose=ext not in CODE_TYPES):
        raise SkipFile("looks like it contains a password or API key, not stored")
    return chunks


def parse_pdf(data: bytes) -> list[dict]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise SkipFile("PDF is password-protected")
        pages = [page.extract_text() or "" for page in reader.pages]
    except SkipFile:
        raise
    except Exception as e:
        raise SkipFile(f"could not read PDF ({e})") from e

    chunks = []
    for number, text in enumerate(pages, 1):
        text = clean_text(text, collapse_blank_lines=True)
        for _, _, content in pack_units(line_units(text)):
            chunks.append({"location": f"page {number}", "content": content})
    if not chunks:
        raise SkipFile("scanned PDF with no selectable text (needs OCR)")
    return chunks


def parse_docx(data: bytes) -> list[dict]:
    """Paragraphs and tables in document order. A table counts as one paragraph in locations."""
    try:
        document = docx.Document(io.BytesIO(data))
        blocks = [_table_text(item) if isinstance(item, Table) else item.text
                  for item in document.iter_inner_content()]
    except Exception as e:
        raise SkipFile(f"could not read DOCX ({e})") from e

    units = []
    for number, text in enumerate(blocks, 1):
        text = clean_text(text, collapse_blank_lines=True).strip()
        if text:
            units.append((number, number, text))
    return [{"location": _location(s, e, "paragraph"), "content": c} for s, e, c in pack_units(units)]


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if not cells or cells[-1] != text:  # merged cells repeat their text
                cells.append(text)
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def decode_text(data: bytes) -> str:
    if b"\x00" in data[:8192]:
        raise SkipFile("looks like a binary file")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


def clean_text(text: str, code: bool = False, collapse_blank_lines: bool = False) -> str:
    """Normalise text. Keeps the number of lines unless collapse_blank_lines is set,
    so line-number locations still match the original file."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​﻿]", "", text)
    if not code:
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[ \t ]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    if collapse_blank_lines:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def contains_secret(text: str, prose: bool = True) -> bool:
    patterns = SECRET_PATTERNS + ([PROSE_SECRET_PATTERN] if prose else [])
    for pattern in patterns:
        for match in pattern.finditer(text):
            if not any(word in match.group(0).lower() for word in PLACEHOLDER_WORDS):
                return True
    return False


# ---------- chunking ----------
# A "unit" is (first_line, last_line, text): a paragraph, a function or class, or part of one.

def line_units(text: str) -> list[tuple[int, int, str]]:
    """Split text into paragraphs (blocks of non-blank lines) with their line numbers."""
    lines = text.split("\n")
    return _paragraphs(lines, 1, len(lines))


def python_units(text: str) -> list[tuple[int, int, str]]:
    """One unit per top-level function or class (large classes split by method).
    Falls back to paragraphs when the code does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return line_units(text)
    lines = text.split("\n")
    units = []
    _node_units(tree.body, lines, 1, len(lines), units)
    return units


def _node_units(body: list, lines: list[str], first: int, last: int, units: list) -> None:
    position = first
    for node in body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        end = node.end_lineno
        units.extend(_paragraphs(lines, position, start - 1))
        is_big_class = isinstance(node, ast.ClassDef) and len("\n".join(lines[start - 1:end])) > CHUNK_SIZE
        if is_big_class and node.body[0].lineno > start:
            body_start = node.body[0].lineno
            units.extend(_block(lines, start, body_start - 1))  # class header and decorators
            _node_units(node.body, lines, body_start, end, units)
        else:
            units.extend(_block(lines, start, end))
        position = end + 1
    units.extend(_paragraphs(lines, position, last))


def _block(lines: list[str], first: int, last: int) -> list[tuple[int, int, str]]:
    """Lines first..last as one unit, without leading and trailing blank lines."""
    while first <= last and not lines[first - 1].strip():
        first += 1
    while last >= first and not lines[last - 1].strip():
        last -= 1
    if first > last:
        return []
    return [(first, last, "\n".join(lines[first - 1:last]))]


def _paragraphs(lines: list[str], first: int, last: int) -> list[tuple[int, int, str]]:
    units = []
    start = None
    for number in range(first, last + 1):
        if lines[number - 1].strip():
            if start is None:
                start = number
        elif start is not None:
            units.extend(_block(lines, start, number - 1))
            start = None
    if start is not None:
        units.extend(_block(lines, start, last))
    return units


def pack_units(units: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Join units into chunks of about CHUNK_SIZE characters, with about CHUNK_OVERLAP characters
    repeated from the end of the previous chunk. Never splits a unit unless it is too big alone."""
    pieces = [piece for unit in units for piece in _fit(unit)]
    chunks = []
    current = []
    for piece in pieces:
        if current and len(_join(current + [piece])[2]) > CHUNK_SIZE:
            chunks.append(_join(current))
            current = _overlap_tail(current)
            if len(_join(current + [piece])[2]) > CHUNK_SIZE:
                current = []
        current.append(piece)
    if current:
        chunks.append(_join(current))
    return chunks


def _fit(unit: tuple[int, int, str]) -> list[tuple[int, int, str]]:
    """Split a unit that is bigger than CHUNK_SIZE into lines, and very long lines by words.
    pack_units then joins the lines back together up to CHUNK_SIZE."""
    start, end, text = unit
    if len(text) <= CHUNK_SIZE:
        return [unit]
    lines = text.split("\n")
    numbered = len(lines) == end - start + 1
    pieces = []
    for offset, line in enumerate(lines):
        number = start + offset if numbered else end
        if len(line) > CHUNK_SIZE:
            pieces.extend((number, number, part) for part in _split_long_line(line))
        elif line.strip():
            pieces.append((number, number, line))
    return pieces


def _split_long_line(line: str) -> list[str]:
    parts = []
    while len(line) > CHUNK_SIZE:
        cut = line.rfind(" ", 0, CHUNK_SIZE)
        if cut <= 0:
            cut = CHUNK_SIZE
        parts.append(line[:cut])
        line = line[cut:].lstrip()
    if line:
        parts.append(line)
    return parts


def _join(units: list[tuple[int, int, str]]) -> tuple[int, int, str]:
    text = units[0][2]
    for previous, unit in zip(units, units[1:]):
        if unit[0] <= previous[1]:
            separator = " "        # pieces of the same line
        elif unit[0] == previous[1] + 1:
            separator = "\n"       # next line
        else:
            separator = "\n\n"     # a gap: new paragraph
        text += separator + unit[2]
    return units[0][0], max(u[1] for u in units), text


def _overlap_tail(units: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """The last ~CHUNK_OVERLAP characters of a chunk: whole lines when possible, else words."""
    tail = []
    size = 0
    for start, end, text in reversed(units):
        lines = text.split("\n")
        numbered = len(lines) == end - start + 1
        taken = []
        for line in reversed(lines):
            if size + len(line) + 1 > CHUNK_OVERLAP:
                break
            taken.insert(0, line)
            size += len(line) + 1
        if taken:
            first = end - len(taken) + 1 if numbered else end
            tail.insert(0, (first, end, "\n".join(taken)))
        if len(taken) < len(lines):
            break
    if any(t[2].strip() for t in tail):
        return tail
    _, end, text = units[-1]
    words = text[-CHUNK_OVERLAP:]
    space = words.find(" ")
    if 0 <= space < len(words) - 1:
        words = words[space + 1:]
    return [(end, end, words)]


def _location(start: int, end: int, label: str = "line") -> str:
    return f"{label} {start}" if start == end else f"{label}s {start}-{end}"


# ---------- ZIP ----------

def read_zip(zip_name: str, data: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Read files from a ZIP in memory; nothing is extracted to disk.
    Returns ([(member_path, bytes)], skipped_messages)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError):
        return [], [f"{zip_name}: not a valid ZIP file"]
    if len(infos) > MAX_ZIP_ENTRIES:
        return [], [f"{zip_name}: too many entries ({len(infos)}, limit {MAX_ZIP_ENTRIES})"]

    files, skipped = [], []
    ignored = 0
    total = 0
    for info in infos:
        if info.is_dir():
            continue
        path = safe_member_path(info.filename)
        if path is None:
            skipped.append(f"{zip_name}/{info.filename}: unsafe path, skipped")
            continue
        reason = skip_reason(path)
        if reason == "ignored folder":
            ignored += 1
            continue
        if reason:
            skipped.append(f"{zip_name}/{path}: {reason}")
            continue
        if info.flag_bits & 0x1:
            skipped.append(f"{zip_name}/{path}: encrypted, skipped")
            continue
        if len(files) >= MAX_ZIP_FILES:
            skipped.append(f"{zip_name}: stopped after {MAX_ZIP_FILES} files (limit)")
            break
        if info.file_size > MAX_FILE_BYTES:
            skipped.append(f"{zip_name}/{path}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
            continue
        if total + info.file_size > MAX_ZIP_TOTAL_BYTES:
            skipped.append(f"{zip_name}: stopped at {path}, total uncompressed size limit reached")
            break
        limit = min(MAX_FILE_BYTES, MAX_ZIP_TOTAL_BYTES - total)
        try:
            with archive.open(info) as member:
                content = member.read(limit + 1)  # never read more than the limit
        except Exception as e:
            skipped.append(f"{zip_name}/{path}: could not read ({e})")
            continue
        if len(content) > limit:
            skipped.append(f"{zip_name}/{path}: real size is larger than the header says, skipped")
            continue
        total += len(content)
        files.append((path, content))

    if ignored:
        skipped.append(f"{zip_name}: ignored {ignored} files in .git, node_modules, virtual environments or caches")
    return files, skipped


def safe_member_path(name: str) -> str | None:
    """Return a clean relative path, or None for absolute paths, drive letters or '..'."""
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def skip_reason(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return "ignored folder"
    name = parts[-1].lower()
    if name == ".env" or name.startswith(".env."):
        return "environment file (may contain secrets), skipped"
    if name in KEY_FILE_NAMES or name.endswith(KEY_FILE_SUFFIXES):
        return "key or credentials file, skipped"
    ext = file_extension(name)
    if ext == "zip":
        return "nested ZIP files are not supported"
    if ext not in CONTENT_TYPES:
        return "unsupported or binary file, skipped"
    return None


# ---------- helpers ----------

def file_extension(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower().lstrip(".")


def _storage_name(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "file"
