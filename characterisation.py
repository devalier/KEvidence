"""Step 0 — substance/product characterisation of feed additives (chemical MVP).

Grounding model
---------------
Every check the module performs comes from a requirement catalogue
(data/guidance/feedap_2017_5023_chemical_requirements.json) derived from
EFSA FEEDAP (2017) "Guidance on the identity, characterisation and conditions
of use of feed additives", EFSA Journal 15(10):5023. Each requirement carries a
verification level. When the guidance text itself is loaded (PDF or text file in
the guidance directory), each requirement is anchored to the passage(s) of the
guidance that support it, and requirements that cannot be anchored are flagged.

Extraction is deterministic (regex/keyword) and every extracted value carries a
citation to the submitted document and page. Nothing here decides compliance:
statuses mean "evidence located" or "not located", for verification by the
scientific officer.

Confidentiality: documents are processed in memory for a single request and are
never written to disk. Optional LLM drafting is off unless explicitly enabled
per request, because it sends extracted excerpts to an external API.
"""

from __future__ import annotations

import datetime as _dt
import io
import ipaddress
import json
import logging
import os
import re
import socket
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

GUIDANCE_DIR = Path(os.getenv("KEVIDENCE_GUIDANCE_DIR", str(Path(__file__).resolve().parent / "data" / "guidance")))
CATALOGUE_PATH = GUIDANCE_DIR / "feedap_2017_5023_chemical_requirements.json"
TEMPLATE_PATH = GUIDANCE_DIR / "characterisation_template.md"
GUIDANCE_PDF_CANDIDATES = ("efsa_2017_5023.pdf", "j.efsa.2017.5023.pdf", "5023.pdf", "guidance_5023.pdf")

logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_FILE_BYTES = int(os.getenv("KEVIDENCE_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
MAX_FILES = int(os.getenv("KEVIDENCE_MAX_FILES", "30"))
MAX_LINKED_DOCS = int(os.getenv("KEVIDENCE_MAX_LINKED_DOCS", "15"))
URL_TIMEOUT_S = 30.0
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".tsv", ".txt", ".md", ".json", ".html", ".htm")

STATUS_LABELS = {
    "gap": "Not located (data gap)",
    "partial": "Partially addressed",
    "conditional": "Applicability to confirm",
    "manual_review": "Scientific-officer review",
    "evidence_located": "Evidence located",
    "not_applicable": "Not applicable",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


# ---------------------------------------------------------------------------
# Catalogue and guidance text
# ---------------------------------------------------------------------------

def load_catalogue(path: Path = CATALOGUE_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        catalogue = json.load(f)
    ids = [r["id"] for r in catalogue["requirements"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate requirement IDs in characterisation catalogue")
    tokens = {s["token"] for s in catalogue["template_sections"]}
    for req in catalogue["requirements"]:
        for key in ("guidance_section", "guidance_page", "quote", "guidance_anchors", "requirement"):
            if not req.get(key):
                raise ValueError(f"{req['id']} is missing '{key}' (every requirement must cite the guidance)")
        if req["template_section"] not in tokens:
            raise ValueError(f"{req['id']} references unknown template section {req['template_section']}")
        for pattern in req.get("patterns", []) + [p for s in req.get("sub_items", []) for p in s["patterns"]]:
            re.compile(pattern, re.I)
    return catalogue


def _normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "–": "-", "—": "-", "’": "'", "‘": "'"}


def _fix_ligatures(text: str) -> str:
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    # The guidance PDF encodes "µ" in a symbol font that pypdf extracts as "l".
    return re.sub(r"(\d)\s?lm\b", "\\1 µm", text)


def _compact(text: str) -> tuple[str, list[int]]:
    """Lower-case, ligature-fixed text with all whitespace removed, plus a map
    from compact positions back to positions in the ligature-fixed text.
    PDF extraction inserts spurious spaces (e.g. 'speci ﬁcation'), so anchors
    are matched whitespace-insensitively."""
    chars, index = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch.lower())
            index.append(i)
    return "".join(chars), index


def load_guidance_pages(guidance_dir: Path = GUIDANCE_DIR) -> Optional[list[str]]:
    """Return the bundled guidance PDF as a list of page texts, or None if absent."""
    for name in GUIDANCE_PDF_CANDIDATES:
        pdf_path = guidance_dir / name
        if pdf_path.exists():
            doc = extract_document(pdf_path.name, pdf_path.read_bytes())
            if doc.pages and any(p.strip() for p in doc.pages):
                return doc.pages
    return None


def anchor_requirements(catalogue: dict[str, Any], pages: Optional[list[str]]) -> dict[str, dict[str, Any]]:
    """Locate each requirement's anchor phrases in the guidance text.

    Returns {requirement_id: {"status", "passages": [{"page", "anchor", "excerpt"}]}}.
    """
    result: dict[str, dict[str, Any]] = {}
    norm_pages = [_normalise_ws(_fix_ligatures(p)) for p in pages] if pages else None
    compact_pages = [_compact(p) for p in norm_pages] if norm_pages else None
    for req in catalogue["requirements"]:
        if not norm_pages:
            result[req["id"]] = {"status": "verified_primary", "passages": [],
                                 "note": f"Guidance text not loaded; catalogue quote from p.{req.get('guidance_page')} (section {req.get('guidance_section')})."}
            continue
        passages = []
        for anchor in req.get("guidance_anchors", []):
            needle, _ = _compact(_fix_ligatures(anchor))
            for page_no, (page, (compact, index)) in enumerate(zip(norm_pages, compact_pages), start=1):
                idx = compact.find(needle)
                if idx < 0:
                    continue
                start_raw = index[idx]
                end_raw = index[min(idx + len(needle), len(index)) - 1] + 1
                start = max(0, start_raw - 160)
                end = min(len(page), end_raw + 320)
                passages.append({
                    "page": page_no,
                    "anchor": anchor,
                    "excerpt": ("…" if start else "") + page[start:end] + ("…" if end < len(page) else ""),
                })
                break
        found_anchors = {p["anchor"] for p in passages}
        if passages and len(found_anchors) == len(req.get("guidance_anchors", [])):
            status = "anchored_in_guidance_text"
        else:
            status = "not_found_in_guidance_text"
        result[req["id"]] = {
            "status": status,
            "anchors_found": sorted(found_anchors),
            "anchors_missing": [a for a in req.get("guidance_anchors", []) if a not in found_anchors],
            "passages": passages[:3],
        }
    return result


def guidance_status(catalogue: Optional[dict[str, Any]] = None, guidance_dir: Path = GUIDANCE_DIR) -> dict[str, Any]:
    catalogue = catalogue or load_catalogue()
    pages = load_guidance_pages(guidance_dir)
    anchors = anchor_requirements(catalogue, pages)
    counts: dict[str, int] = {}
    for req in catalogue["requirements"]:
        key = anchors[req["id"]]["status"]
        counts[key] = counts.get(key, 0) + 1
    return {
        "guidance": catalogue["guidance"],
        "catalogue_id": catalogue["catalogue_id"],
        "catalogue_version": catalogue["catalogue_version"],
        "scope": catalogue["scope"],
        "guidance_text_loaded": bool(pages),
        "guidance_pages": len(pages) if pages else 0,
        "verification_levels": catalogue["verification_levels"],
        "verification_counts": counts,
        "template_sections": catalogue["template_sections"],
        "meta_options": catalogue.get("meta_options", {}),
        "related_guidance": catalogue.get("related_guidance", []),
        "requirements": [
            {
                "id": r["id"],
                "title": r["title"],
                "guidance_section": r["guidance_section"],
                "guidance_page": r["guidance_page"],
                "template_section": r["template_section"],
                "scope": r["scope"],
                "requirement": r["requirement"],
                "quote": r["quote"],
                "grounding": anchors[r["id"]],
            }
            for r in catalogue["requirements"]
        ],
    }


# ---------------------------------------------------------------------------
# Document ingestion
# ---------------------------------------------------------------------------

@dataclass
class Document:
    doc_id: str
    name: str
    source: str  # "upload" or URL
    pages: list[str] = field(default_factory=list)
    kind: str = "unknown"
    doc_type: str = "Unclassified"
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.pages)


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.links.append(value)
        if tag in ("p", "br", "tr", "li", "div", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _extension(name: str) -> str:
    name = (name or "").lower().split("?")[0]
    return os.path.splitext(name)[1]


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = content.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return text
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _pdf_pages(content: bytes, warnings: list[str]) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency declared in requirements.txt
        warnings.append("pypdf is not installed; PDF text could not be extracted.")
        return []
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                warnings.append("PDF is encrypted and could not be opened without a password.")
                return []
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
                warnings.append("Text extraction failed on at least one PDF page.")
        if pages and sum(len(p.strip()) for p in pages) < 40 * len(pages):
            warnings.append("Very little extractable text: the PDF is probably scanned. OCR is required before this document can be assessed.")
        return pages
    except Exception as exc:
        warnings.append(f"PDF could not be parsed ({type(exc).__name__}).")
        return []


def _docx_pages(content: bytes, warnings: list[str]) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError):
        warnings.append("DOCX could not be opened.")
        return []
    xml = re.sub(r"</w:tc>", " | ", xml)
    xml = re.sub(r"</w:p>|<w:br/>|</w:tr>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'"))
    return [text]


def _xlsx_pages(content: bytes, warnings: list[str]) -> list[str]:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        warnings.append(f"Spreadsheet could not be opened ({type(exc).__name__}).")
        return []
    pages = []
    for ws in wb.worksheets:
        lines = [f"[Sheet: {ws.title}]"]
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                lines.append(" | ".join(cells))
        pages.append("\n".join(lines))
    wb.close()
    return pages


def html_to_text(content: bytes) -> tuple[str, list[str]]:
    parser = _HTMLText()
    parser.feed(_decode(content))
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip(), parser.links


def extract_document(name: str, content: bytes, doc_id: str = "D?", source: str = "upload", content_type: str = "") -> Document:
    doc = Document(doc_id=doc_id, name=name or "unnamed", source=source)
    if len(content) > MAX_FILE_BYTES:
        doc.warnings.append(f"File exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit and was not processed.")
        return doc
    ext = _extension(name)
    ctype = (content_type or "").lower()
    if ext == ".pdf" or "pdf" in ctype or content[:5] == b"%PDF-":
        doc.kind = "pdf"
        doc.pages = _pdf_pages(content, doc.warnings)
    elif ext == ".docx" or "wordprocessingml" in ctype:
        doc.kind = "docx"
        doc.pages = _docx_pages(content, doc.warnings)
    elif ext in (".xlsx", ".xlsm") or "spreadsheetml" in ctype:
        doc.kind = "xlsx"
        doc.pages = _xlsx_pages(content, doc.warnings)
    elif ext in (".html", ".htm") or "html" in ctype:
        doc.kind = "html"
        text, _ = html_to_text(content)
        doc.pages = [text]
    elif ext in (".csv", ".tsv", ".txt", ".md", ".json") or ctype.startswith("text/") or "json" in ctype:
        doc.kind = "text"
        doc.pages = [_decode(content)]
    else:
        doc.warnings.append(
            f"Unsupported file type '{ext or ctype or 'unknown'}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    doc.pages = [p.replace("\u00a0", " ") for p in doc.pages]
    doc.doc_type = classify_document(doc)
    return doc


DOC_TYPE_RULES = [
    ("Certificate of analysis", [r"certificate\s+of\s+analysis", r"\bCoA\b", r"analytical\s+certificate"]),
    ("Product specification", [r"product\s+specification", r"specification\s+sheet", r"technical\s+data\s+sheet"]),
    ("Safety data sheet", [r"safety\s+data\s+sheet", r"\bSDS\b", r"\bMSDS\b"]),
    ("Batch analysis report", [r"batch\s+(analysis|analyses|to\s*-?\s*batch)", r"batch-to-batch"]),
    ("Impurity / contaminant report", [r"heavy\s+metals", r"dioxins?", r"mycotoxins?", r"residual\s+solvents"]),
    ("Stability study", [r"stability\s+(study|studies|test)", r"shelf[\s-]*life"]),
    ("Homogeneity study", [r"homogeneity"]),
    ("Particle size / dusting study", [r"dusting\s+potential", r"particle\s+size", r"stauber"]),
    ("Manufacturing process description", [r"manufacturing\s+process", r"flow\s*(chart|diagram)", r"production\s+process"]),
    ("Technical dossier (Section II)", [r"section\s+II", r"identity,?\s+characterisation"]),
]


def classify_document(doc: Document) -> str:
    head = " ".join(doc.pages)[:20000]
    scores = []
    for label, patterns in DOC_TYPE_RULES:
        score = sum(len(re.findall(p, head, re.I)) for p in patterns)
        if score:
            scores.append((score, label))
    if not scores:
        return "Unclassified"
    scores.sort(reverse=True)
    return scores[0][1]


# --- URL retrieval (SSRF-guarded) -------------------------------------------

def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # DNS may only be resolvable by an outbound proxy; treat literal private
        # names as unsafe and let the HTTP client report failure otherwise.
        return not (host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"))
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified):
            return False
    return True


def validate_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Only http(s) URLs are accepted: {url!r}")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if not ip.is_global:
            raise ValueError(f"URL host is not a public address: {url!r}")
    except ValueError as exc:
        if "not a public address" in str(exc):
            raise
        if not _host_is_public(parsed.hostname):
            raise ValueError(f"URL host resolves to a non-public address: {url!r}")
    return parsed.geturl()


def _fetch(url: str, client) -> tuple[bytes, str, str]:
    current = validate_url(url)
    for _ in range(4):
        with client.stream("GET", current, follow_redirects=False) as resp:
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                current = validate_url(urljoin(current, resp.headers["location"]))
                continue
            resp.raise_for_status()
            chunks, size = [], 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ValueError(f"Remote document exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB: {current}")
                chunks.append(chunk)
            return b"".join(chunks), resp.headers.get("content-type", ""), current
    raise ValueError(f"Too many redirects: {url}")


def fetch_url_documents(url: str, start_index: int, client=None) -> tuple[list[Document], list[str]]:
    """Fetch a URL. HTML pages are kept as a document and linked dossier files
    (PDF/DOCX/XLSX) are followed, up to MAX_LINKED_DOCS."""
    import httpx

    notes: list[str] = []
    own_client = client is None
    client = client or httpx.Client(timeout=URL_TIMEOUT_S, headers={"User-Agent": "KEvidence/0.1 (characterisation)"})
    docs: list[Document] = []
    try:
        content, ctype, final_url = _fetch(url, client)
        name = os.path.basename(urlparse(final_url).path) or urlparse(final_url).hostname or "url"
        doc = extract_document(name, content, f"D{start_index}", final_url, ctype)
        docs.append(doc)
        if doc.kind == "html":
            _, links = html_to_text(content)
            doc_links = []
            for link in links:
                absolute = urljoin(final_url, link)
                if _extension(absolute) in (".pdf", ".docx", ".xlsx", ".xlsm") and absolute not in doc_links:
                    doc_links.append(absolute)
            if len(doc.pages[0] if doc.pages else "") < 500 and not doc_links:
                notes.append(
                    f"{final_url} returned little text and no document links. Dossier portals rendered by "
                    "JavaScript (e.g. Open EFSA) cannot be read by URL; download the documents and upload them."
                )
            for link in doc_links[:MAX_LINKED_DOCS]:
                try:
                    c2, t2, f2 = _fetch(link, client)
                    docs.append(extract_document(os.path.basename(urlparse(f2).path), c2,
                                                 f"D{start_index + len(docs)}", f2, t2))
                except Exception as exc:
                    notes.append(f"Linked document not retrieved ({link}): {exc}")
            if len(doc_links) > MAX_LINKED_DOCS:
                notes.append(f"{len(doc_links) - MAX_LINKED_DOCS} further linked documents were not followed (limit {MAX_LINKED_DOCS}).")
    except Exception as exc:
        notes.append(f"URL not retrieved ({url}): {exc}")
    finally:
        if own_client:
            client.close()
    return docs, notes


# ---------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    doc_id: str
    page: int
    line: int
    text: str


def segment_documents(docs: list[Document]) -> list[Segment]:
    segments = []
    for doc in docs:
        for page_no, page in enumerate(doc.pages, start=1):
            for line_no, raw in enumerate(page.splitlines(), start=1):
                text = _normalise_ws(raw)
                if len(text) >= 2:
                    segments.append(Segment(doc.doc_id, page_no, line_no, text))
    return segments


def cite(seg: Segment) -> str:
    return f"{seg.doc_id} p.{seg.page}"


def cas_checksum_ok(cas: str) -> bool:
    m = re.fullmatch(r"(\d{2,7})-(\d{2})-(\d)", cas)
    if not m:
        return False
    digits = (m.group(1) + m.group(2))[::-1]
    return sum((i + 1) * int(d) for i, d in enumerate(digits)) % 10 == int(m.group(3))


def ec_checksum_ok(ec: str) -> bool:
    m = re.fullmatch(r"(\d{3})-(\d{3})-(\d)", ec)
    if not m:
        return False
    digits = m.group(1) + m.group(2)
    remainder = sum((i + 1) * int(d) for i, d in enumerate(digits)) % 11
    return remainder != 10 and remainder == int(m.group(3))


CAS_RE = re.compile(r"(?<![\d-])(\d{2,7}-\d{2}-\d)(?![\d-])")
EC_RE = re.compile(r"(?<![\d-])(\d{3}-\d{3}-\d)(?![\d-])")
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
FORMULA_TOKEN_RE = re.compile(r"\b((?:[A-Z][a-z]?\d*){2,}(?:\s*[·•.]\s*\d*\s*(?:[A-Z][a-z]?\d*)+)?)\b")
ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi".split())
MW_RE = re.compile(r"(?:molecular|molar|formula)\s+(?:weight|mass)[^0-9]{0,40}?(\d{1,4}(?:[.,]\d{1,4})?)\s*(g\s*/\s*mol|g·mol|g mol|Da|daltons?)?", re.I)
SPEC_RE = re.compile(r"(≥|>=|≤|<=|not\s+less\s+than|not\s+more\s+than|min(?:imum|\.)?|max(?:imum|\.)?)\s*(\d+(?:[.,]\d+)?)\s*(%|g/kg|mg/kg)", re.I)
BATCH_ID_RE = re.compile(r"\b(?:batch|lot)(?![a-z])\s*(?:no\.?|number|nr\.?|n°|#|id|code)?\s*[:.]?\s*([A-Z0-9][A-Z0-9\-/.]*\d[A-Z0-9\-/.]*)", re.I)
BATCH_ROW_RE = re.compile(r"^(?:batch|lot)(?:es)?\s*(?:no\.?|number|nr\.?|n°|#|id|code)?\s*[:|]\s*(.+)$", re.I)
BATCH_COUNT_RE = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:independent\s+|different\s+|consecutive\s+|production\s+|representative\s+|commercial\s+)*(?:production\s+)?(?:batches|lots)\b", re.I)


def valid_formula(token: str) -> bool:
    token = token.translate(SUBSCRIPTS)
    parts = re.findall(r"([A-Z][a-z]?)(\d*)", token)
    if not parts:
        return False
    elements = [e for e, _ in parts]
    if not all(e in ELEMENTS for e in elements):
        return False
    # Require at least one stoichiometric number, to exclude acronyms such as "HPLC".
    return any(n for _, n in parts) and len(elements) >= 2


def find_cas_numbers(segments: list[Segment]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for seg in segments:
        for m in CAS_RE.finditer(seg.text):
            cas = m.group(1)
            if EC_RE.fullmatch(cas):
                continue
            if not cas_checksum_ok(cas):
                if re.search(r"\bCAS\b", seg.text, re.I):
                    found.setdefault(f"invalid:{cas}", {"cas": cas, "valid": False, "citation": cite(seg), "context": seg.text})
                continue
            if cas not in found:
                found[cas] = {"cas": cas, "valid": True, "citation": cite(seg), "context": seg.text}
    return list(found.values())


def _value_after_label(text: str, label_re: str) -> Optional[str]:
    m = re.search(label_re + r"\s*(?:\([^)]*\))?\s*[:=–\-|]\s*(.+)", text, re.I)
    if m:
        value = m.group(1).strip(" |;")
        return value[:300] if value else None
    return None


def extract_identity(scope: list[Segment]) -> dict[str, Any]:
    """Pull identity fields from a list of segments; each value carries a citation."""
    out: dict[str, Any] = {}

    def put(key, value, seg):
        if value and key not in out:
            out[key] = {"value": value, "citation": cite(seg), "context": seg.text[:300]}

    for idx, seg in enumerate(scope):
        t = seg.text
        if re.search(r"IUPAC", t, re.I):
            put("iupac_name", _value_after_label(t, r"IUPAC(?:\s+name)?"), seg)
        if re.search(r"\bCAS\b", t, re.I):
            for m in CAS_RE.finditer(t):
                if cas_checksum_ok(m.group(1)):
                    put("cas", m.group(1), seg)
                    break
        if re.search(r"\bEC\b|EINECS", t):
            for m in EC_RE.finditer(t):
                if ec_checksum_ok(m.group(1)):
                    put("ec", m.group(1), seg)
                    break
        if re.search(r"(molecular|chemical|empirical)\s+formula", t, re.I):
            tail = re.split(r"formula", t, flags=re.I, maxsplit=1)[-1].translate(SUBSCRIPTS)
            for m in FORMULA_TOKEN_RE.finditer(tail):
                if valid_formula(m.group(1)):
                    put("molecular_formula", m.group(1).replace(" ", ""), seg)
                    break
        if re.search(r"structural\s+formula|chemical\s+structure|SMILES|InChI", t, re.I):
            value = _value_after_label(t, r"(?:structural\s+formula|chemical\s+structure|SMILES|InChI(?:Key)?)")
            put("structural_formula", value or "Structure referred to (figure/description) — verify in source", seg)
        mw = MW_RE.search(t)
        if mw:
            put("molecular_weight", f"{mw.group(1)} {mw.group(2) or 'g/mol (unit not stated)'}".strip(), seg)
        if re.search(r"synonym|other\s+names?|also\s+known\s+as", t, re.I):
            put("synonyms", _value_after_label(t, r"(?:synonyms?|other\s+names?|also\s+known\s+as)"), seg)
        if re.search(r"purity|\bassay\b|content\s+of", t, re.I):
            spec = SPEC_RE.search(t)
            if spec:
                put("purity", f"{spec.group(1)} {spec.group(2)} {spec.group(3)}", seg)
        if re.search(r"water\s+solubility|solubility\s+in\s+water|soluble\s+in\s+water", t, re.I):
            put("water_solubility", _value_after_label(t, r"(?:water\s+solubility|solubility\s+in\s+water)") or t[:200], seg)
        if re.search(r"log\s*K\s*ow|log\s*P\b|partition\s+coefficient", t, re.I):
            m = re.search(r"(?:log\s*K\s*ow|log\s*P|partition\s+coefficient)[^0-9\-−]{0,30}([\-−]?\d+(?:[.,]\d+)?)", t, re.I)
            put("log_kow", m.group(1).replace("−", "-") if m else t[:200], seg)
        if re.search(r"trade\s*name|proprietary\s+name|product\s+name", t, re.I):
            put("trade_name", _value_after_label(t, r"(?:trade\s*name|proprietary\s+name|product\s+name)"), seg)
        if re.search(r"generic\s+name|common\s+name", t, re.I):
            put("generic_name", _value_after_label(t, r"(?:generic|common)\s+name"), seg)
        if re.search(r"SMILES", t):
            m = re.search(r"SMILES[^:=|]*[:=|]\s*([A-Za-z0-9@+\-\[\]\(\)\\/=#$%.:]+)", t)
            put("smiles", m.group(1) if m else None, seg)
        if re.search(r"FLAVIS|FL[\s-]?no", t, re.I):
            m = re.search(r"\b(\d{2}\.\d{3})\b", t)
            put("flavis", m.group(1) if m else None, seg)
        if re.search(r"\bpKa\b|dissociation\s+constant", t, re.I):
            put("pka", _value_after_label(t, r"(?:pKa\w*|dissociation\s+constants?)") or t[:200], seg)
        if re.search(r"melting\s+point", t, re.I):
            put("melting_point", _value_after_label(t, r"melting\s+point") or t[:200], seg)
        if re.search(r"optical\s+rotation|specific\s+rotation", t, re.I):
            put("optical_rotation", _value_after_label(t, r"(?:specific\s+)?(?:optical\s+)?rotation") or t[:200], seg)
    return out


def detect_batches(segments: list[Segment]) -> dict[str, Any]:
    ids: dict[str, str] = {}
    stated: list[dict[str, Any]] = []
    for seg in segments:
        header = BATCH_ROW_RE.match(seg.text)
        if header:
            # Table row such as "Batch No. | 2301A | 2302B | 2303C"
            for cell in re.split(r"[|;,\t]|\s{2,}", header.group(1)):
                cell = cell.strip(" .")
                if re.fullmatch(r"[A-Z0-9][A-Z0-9\-/.]{0,24}", cell, re.I) and re.search(r"\d", cell):
                    ids.setdefault(cell.upper(), cite(seg))
        for m in BATCH_ID_RE.finditer(seg.text):
            batch_id = m.group(1).strip(".-/")
            if batch_id and batch_id.upper() not in ids and not re.fullmatch(r"(19|20)\d\d", batch_id):
                ids[batch_id.upper()] = cite(seg)
        for m in BATCH_COUNT_RE.finditer(seg.text):
            raw = m.group(1).lower()
            n = NUMBER_WORDS.get(raw, int(raw) if raw.isdigit() else 0)
            if n:
                stated.append({"count": n, "citation": cite(seg), "text": seg.text[:200]})
    max_stated = max((s["count"] for s in stated), default=0)
    return {
        "distinct_batch_ids": sorted(ids),
        "batch_id_citations": ids,
        "stated_counts": stated[:5],
        "best_estimate": max(len(ids), max_stated),
    }


# ---------------------------------------------------------------------------
# Requirement evaluation
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#+\s|\d+(\.\d+)*\.?\s+[A-Z][^:]{0,80}$)")
JUSTIFICATION_RE = re.compile(
    r"not\s+applicable|not\s+relevant|not\s+required|waiv|justif|omitted|omission|"
    r"no\s+(data|study|studies)\s+(is|are|was|were|has\s+been|have\s+been)\s+(provided|performed|conducted)",
    re.I,
)
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
MONTHS_RE = re.compile(r"\b(\d{1,2})\s*(months?|mo\.?)\b|\b(\d{1,3})\s*weeks?\b", re.I)
HOURS_RE = re.compile(r"\b(\d{1,3})\s*(h|hrs?|hours?)\b|\b(\d{1,2})\s*days?\b", re.I)
SUBSAMPLES_RE = re.compile(r"\b(\d{1,3}|ten|twelve|fifteen|twenty)\s+(?:sub-?\s*)?(?:samples|subsamples|replicates)\b", re.I)
WORD_NUM = {"ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


def _matches(patterns: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _meta_list(meta: dict[str, Any], key: str) -> set[str]:
    value = meta.get(key) or []
    if isinstance(value, str):
        value = [value]
    return {str(v).strip().lower() for v in value if str(v).strip()}


def _applicable(applies_when: dict[str, Any], meta: dict[str, Any]) -> str:
    """Return 'yes', 'no', 'unknown' or 'manual' for a set of applicability conditions.

    Exemptions (`*_not`) apply only when the user has stated the triggering
    attribute; conditions that need a positive attribute (`*_any`, form, route)
    are 'unknown' until the attribute is entered.
    """
    if not applies_when:
        return "yes"
    form = (meta.get("product_form") or "").strip().lower()
    routes = _meta_list(meta, "routes")
    production = _meta_list(meta, "production_types")
    additive_type = _meta_list(meta, "additive_type")
    verdicts = []
    if "form" in applies_when:
        verdicts.append("unknown" if form in ("", "unknown") else ("yes" if form == applies_when["form"] else "no"))
    if "route" in applies_when:
        verdicts.append("unknown" if not routes else ("yes" if applies_when["route"] in routes else "no"))
    if "route_any" in applies_when:
        verdicts.append("unknown" if not routes else ("yes" if routes & set(applies_when["route_any"]) else "no"))
    if "production_type_any" in applies_when:
        verdicts.append("unknown" if not production else ("yes" if production & set(applies_when["production_type_any"]) else "no"))
    if "production_type_not" in applies_when:
        verdicts.append("no" if production and production <= set(applies_when["production_type_not"]) else "yes")
    if "additive_type_any" in applies_when:
        verdicts.append("unknown" if not additive_type else ("yes" if additive_type & set(applies_when["additive_type_any"]) else "no"))
    if "additive_type_not" in applies_when:
        verdicts.append("no" if additive_type & set(applies_when["additive_type_not"]) else "yes")
    if "components_min" in applies_when:
        verdicts.append("yes" if int(meta.get("_component_count") or 0) >= applies_when["components_min"] else "no")
    if "no" in verdicts:
        return "no"
    if "unknown" in verdicts:
        return "unknown"
    if applies_when.get("manual"):
        return "manual"
    return "yes"


def _page_neighbourhood(segments: list[Segment], hits: list[Segment], window: int = 12) -> list[Segment]:
    """Segments within `window` lines of any hit on the same page (tables of
    batch results usually sit just below the heading or label that matched)."""
    near: dict[tuple[str, int], list[int]] = {}
    for h in hits:
        near.setdefault((h.doc_id, h.page), []).append(h.line)
    return [s for s in segments
            if any(abs(s.line - line) <= window for line in near.get((s.doc_id, s.page), []))]


def _max_duration(segments: list[Segment], unit: str) -> Optional[tuple[float, str]]:
    best: Optional[tuple[float, str]] = None
    for seg in segments:
        regex = MONTHS_RE if unit == "months" else HOURS_RE
        for m in regex.finditer(seg.text):
            if unit == "months":
                value = float(m.group(1)) if m.group(1) else float(m.group(3)) / 4.345
            else:
                value = float(m.group(1)) if m.group(1) else float(m.group(3)) * 24
            if best is None or value > best[0]:
                best = (value, cite(seg))
    return best


def _check(label: str, met: Optional[bool], detail: str) -> dict[str, Any]:
    return {"label": label, "met": met, "detail": detail}


def evaluate_requirement(req: dict[str, Any], segments: list[Segment], meta: dict[str, Any]) -> dict[str, Any]:
    applicability = _applicable(req.get("applies_when", {}), meta)
    result: dict[str, Any] = {
        "id": req["id"],
        "title": req["title"],
        "guidance_section": req["guidance_section"],
        "guidance_page": req["guidance_page"],
        "section": req["template_section"],
        "requirement": req["requirement"],
        "quote": req["quote"],
        "applicability": applicability,
        "applicability_note": (req.get("applies_when") or {}).get("manual"),
        "evidence": [],
        "sub_items": [],
        "missing": [],
        "checks": [],
        "flags": [],
        "justification": [],
        "batch_check": None,
    }
    if req.get("conditional_note"):
        result["conditional_note"] = req["conditional_note"]
    if applicability == "no":
        result["status"] = "not_applicable"
        return result

    patterns = _compile(req.get("patterns", []))
    hits = [s for s in segments if _matches(patterns, s.text)]
    neighbourhood = _page_neighbourhood(segments, hits) if hits else []
    result["evidence"] = [{"citation": cite(s), "text": s.text[:300]} for s in hits[:8]]
    result["evidence_count"] = len(hits)

    if req.get("requires_meta") == "production_type" and not _meta_list(meta, "production_types"):
        result["missing"].append("Production type not entered — the minimum impurity set of §2.1.4 depends on it "
                                 "(chemical synthesis, fermentation, plant-derived, animal-derived, mineral).")

    production = _meta_list(meta, "production_types")
    required_missing = []
    for sub in req.get("sub_items", []):
        sub_app = _applicable(sub.get("applies_when", {}), meta)
        if sub_app == "no":
            continue
        sub_patterns = _compile(sub["patterns"])
        sub_hits = [s for s in hits if _matches(sub_patterns, s.text)] or [s for s in segments if _matches(sub_patterns, s.text)]
        sub_hits.sort(key=lambda seg: bool(HEADING_RE.match(seg.text)))  # content lines before headings
        located = bool(sub_hits)
        notes = [note for ptype, note in (sub.get("note_when") or {}).items() if ptype in production]
        entry = {
            "label": sub["label"],
            "required": bool(sub.get("required")) and sub_app in ("yes", "manual"),
            "applicability": sub_app,
            "located": located,
            "citations": sorted({cite(s) for s in sub_hits})[:6],
            "snippet": f"{sub_hits[0].text[:160]}" if sub_hits else "",
            "note": "; ".join(notes) or None,
            "field": sub.get("field"),
        }
        result["sub_items"].append(entry)
        if not located:
            suffix = f" ({entry['note']})" if entry["note"] else ""
            if entry["required"]:
                required_missing.append(sub["label"])
                result["missing"].append(f"{sub['label']} — not located in the submitted documents{suffix}")
            elif sub_app == "unknown" and sub.get("required"):
                result["missing"].append(f"{sub['label']} — not located; required if applicable (enter product form / route / production type)")
            else:
                result["missing"].append(f"{sub['label']} — not located (provide where relevant){suffix}")

    failed_check = False
    if hits:
        if req.get("min_batches"):
            batches = detect_batches(neighbourhood)
            ok = batches["best_estimate"] >= req["min_batches"]
            result["batch_check"] = {
                "required_min": req["min_batches"],
                "detected": batches["best_estimate"],
                "batch_ids": batches["distinct_batch_ids"][:20],
                "stated_counts": batches["stated_counts"],
                "met": ok,
            }
            if not ok:
                failed_check = True
                result["missing"].append(
                    f"At least {req['min_batches']} batches required (§{req['guidance_section']}); "
                    f"{batches['best_estimate']} detected on the pages carrying this evidence"
                )
        if req.get("recency_years"):
            years = [(int(m.group(1)), cite(s)) for s in neighbourhood for m in YEAR_RE.finditer(s.text)]
            limit = _dt.date.today().year - req["recency_years"]
            if not years:
                result["checks"].append(_check("Analyses produced within the last 5 years", None,
                                               "No dates located near the analytical data — confirm the date of the certificates of analysis."))
            else:
                latest = max(years)
                ok = latest[0] >= limit
                result["checks"].append(_check(
                    "Analyses produced within the last 5 years", ok,
                    f"Most recent year detected: {latest[0]} ({latest[1]})" + ("" if ok else f" — older than {limit}")))
                if not ok:
                    failed_check = True
                    result["missing"].append(f"Analytical data appear older than 5 years (latest year detected {latest[0]})")
        for key, unit, label in (("min_months", "months", "Study duration"), ("min_hours", "hours", "Study duration")):
            if req.get(key):
                found = _max_duration(neighbourhood, unit)
                if not found:
                    result["checks"].append(_check(f"{label} ≥ {req[key]} {unit}", None, "Duration not located — verify in the study report."))
                else:
                    ok = found[0] >= req[key]
                    result["checks"].append(_check(f"{label} ≥ {req[key]} {unit}", ok, f"Longest duration detected: {found[0]:g} {unit} ({found[1]})"))
                    if not ok:
                        failed_check = True
                        result["missing"].append(f"Duration below the guidance minimum of {req[key]} {unit} (§{req['guidance_section']})")
        if req.get("min_subsamples"):
            counts = []
            for s in neighbourhood:
                for m in SUBSAMPLES_RE.finditer(s.text):
                    raw = m.group(1).lower()
                    counts.append((WORD_NUM.get(raw, int(raw) if raw.isdigit() else 0), cite(s)))
            if not counts:
                result["checks"].append(_check(f"≥ {req['min_subsamples']} subsamples", None, "Number of subsamples not located."))
            else:
                best = max(counts)
                ok = best[0] >= req["min_subsamples"]
                result["checks"].append(_check(f"≥ {req['min_subsamples']} subsamples", ok, f"{best[0]} detected ({best[1]})"))
                if not ok:
                    failed_check = True
                    result["missing"].append(f"Fewer than {req['min_subsamples']} subsamples detected")
        if req.get("red_flag_patterns"):
            flagged = [s for s in neighbourhood if _matches(_compile(req["red_flag_patterns"]), s.text)]
            if flagged:
                result["flags"].append({"message": req["red_flag_message"],
                                        "citations": sorted({cite(s) for s in flagged})[:6]})
        if req.get("pilot_batch_patterns"):
            pilot = [s for s in neighbourhood if _matches(_compile(req["pilot_batch_patterns"]), s.text)]
            if pilot:
                result["flags"].append({"message": "Pilot batches referred to — acceptable only where commercial batches are not yet "
                                                   "available and they represent the intended manufacturing process (§2.1.3).",
                                        "citations": sorted({cite(s) for s in pilot})[:6]})

    if req.get("manual_review"):
        result["status"] = "manual_review"
    elif not hits:
        result["status"] = "gap"
        if not any("not located" in m for m in result["missing"]):
            result["missing"].append("No evidence located in the submitted documents")
    elif required_missing or failed_check:
        result["status"] = "partial"
    else:
        result["status"] = "evidence_located"
    if applicability in ("unknown", "manual") and result["status"] in ("gap", "partial"):
        result["status"] = "conditional"
    if req.get("requires_meta") == "production_type" and not production and result["status"] != "gap":
        result["status"] = "conditional"

    if result["status"] in ("gap", "partial", "conditional"):
        just = [s for s in segments if JUSTIFICATION_RE.search(s.text) and _matches(patterns, s.text)]
        result["justification"] = [{"citation": cite(s), "text": s.text[:240]} for s in just[:3]]
    return result


def _component_scope(segments: list[Segment], component: dict[str, Any], window: int = 25) -> list[Segment]:
    needles = [n.lower() for n in (component.get("name"), component.get("cas")) if n]
    if not needles:
        return []
    scope_keys: set[tuple[str, int, int]] = set()
    for i, seg in enumerate(segments):
        low = seg.text.lower()
        if any(n in low for n in needles):
            for j in range(i, min(len(segments), i + window)):
                if segments[j].doc_id == seg.doc_id and segments[j].page == seg.page:
                    scope_keys.add((segments[j].doc_id, segments[j].page, segments[j].line))
    return [s for s in segments if (s.doc_id, s.page, s.line) in scope_keys]


def infer_components(segments: list[Segment]) -> list[dict[str, Any]]:
    comps = []
    for entry in find_cas_numbers(segments):
        if not entry["valid"]:
            continue
        context = entry["context"]
        label = re.split(r"\(?\s*CAS", context, flags=re.I)[0].strip(" :|-–(") or ""
        label = label if 2 <= len(label) <= 80 else ""
        comps.append({"name": label, "cas": entry["cas"], "role": "Detected (role to confirm)", "auto": True,
                      "detected_from": entry["citation"]})
    return comps[:8]


def evaluate_components(catalogue: dict[str, Any], segments: list[Segment], meta: dict[str, Any]) -> list[dict[str, Any]]:
    components = [c for c in meta.get("components", []) if (c.get("name") or c.get("cas"))]
    if not components:
        components = infer_components(segments)
    component_reqs = [r for r in catalogue["requirements"] if r["scope"] == "component"]
    out = []
    single = len(components) <= 1
    for comp in components:
        scope = segments if single else _component_scope(segments, comp)
        identity = extract_identity(scope)
        if not comp.get("name"):
            for key in ("generic_name", "iupac_name"):
                if identity.get(key):
                    comp = {**comp, "name": str(identity[key]["value"])[:80]}
                    break
        reqs = []
        for req in component_reqs:
            evaluation = evaluate_requirement(req, scope, meta)
            for sub in evaluation["sub_items"]:
                if sub.get("field") and sub["field"] in identity:
                    sub["value"] = identity[sub["field"]]
            reqs.append(evaluation)
        cas_given = (comp.get("cas") or "").strip()
        cas_note = None
        if cas_given:
            cas_note = "CAS check digit valid" if cas_checksum_ok(cas_given) else "CAS check digit INVALID — verify the number"
            if identity.get("cas") and identity["cas"]["value"] != cas_given:
                cas_note += f"; documents state {identity['cas']['value']} ({identity['cas']['citation']})"
        out.append({
            "component": comp,
            "scope_segments": len(scope),
            "identity": identity,
            "cas_check": cas_note,
            "requirements": reqs,
        })
    return out


def _fermentation_flags(segments: list[Segment]) -> list[dict[str, str]]:
    compiled = _compile([r"ferment", r"production\s+(strain|organism)", r"corynebacterium", r"bacillus\s+\w+", r"aspergillus",
                         r"saccharomyces", r"escherichia\s+coli\s+\w*\d", r"\b(DSM|KCCM|CGMCC|NRRL|ATCC|NCIMB)\s*\d"])
    return [{"citation": cite(s), "text": s.text[:200]} for s in segments if _matches(compiled, s.text)][:5]


def analyse_dossier(docs: list[Document], meta: dict[str, Any], catalogue: Optional[dict[str, Any]] = None,
                    guidance_pages: Optional[list[str]] = None, fetch_notes: Optional[list[str]] = None) -> dict[str, Any]:
    catalogue = catalogue or load_catalogue()
    segments = segment_documents(docs)
    meta = dict(meta or {})
    meta["routes"] = sorted(_meta_list(meta, "routes"))
    meta["production_types"] = sorted(_meta_list(meta, "production_types"))
    entered = [c for c in meta.get("components", []) if (c.get("name") or c.get("cas"))]
    meta["_component_count"] = len(entered) or len(infer_components(segments))
    additive_reqs = [r for r in catalogue["requirements"] if r["scope"] == "additive"]
    additive_results = [evaluate_requirement(r, segments, meta) for r in additive_reqs]
    components = evaluate_components(catalogue, segments, meta)
    anchors = anchor_requirements(catalogue, guidance_pages)
    for res in additive_results:
        res["grounding"] = anchors[res["id"]]
    for comp in components:
        for res in comp["requirements"]:
            res["grounding"] = anchors[res["id"]]

    all_results = additive_results + [r for c in components for r in c["requirements"]]
    summary: dict[str, int] = {k: 0 for k in STATUS_LABELS}
    for res in all_results:
        summary[res["status"]] = summary.get(res["status"], 0) + 1

    scope_flags = []
    fermentation = _fermentation_flags(segments)
    if fermentation and "fermentation" not in meta["production_types"]:
        scope_flags.append({
            "flag": "Production by fermentation indicated in the documents",
            "detail": "Select 'fermentation' as production type so that the §2.1.4 fermentation-specific impurity requirements "
                      "(spent growth medium, absence of production organism and antimicrobial activity, LPS, DNA) are applied. "
                      "Characterisation of the production strain itself follows the FEEDAP microorganism guidance "
                      "(EFSA Journal 2018;16(3):5206) and is outside this MVP.",
            "evidence": fermentation,
        })
    elif "fermentation" in meta["production_types"]:
        scope_flags.append({
            "flag": "Fermentation product",
            "detail": "Production-strain characterisation (§2.2.1.2, §2.2.2.2) follows the FEEDAP microorganism guidance "
                      "(EFSA Journal 2018;16(3):5206) and is outside this chemical-characterisation MVP.",
            "evidence": fermentation,
        })
    if not components:
        scope_flags.append({
            "flag": "No component identified",
            "detail": "No component was entered and no valid CAS number was found. Enter each component of the product/mixture (§2.1.3, §2.2.1.1).",
            "evidence": [],
        })
    unreadable = [d for d in docs if not d.char_count]
    if unreadable:
        scope_flags.append({
            "flag": "Documents without extractable text",
            "detail": "Absence of evidence for these documents may reflect extraction limits rather than true data gaps: "
                      + ", ".join(f"{d.doc_id} {d.name}" for d in unreadable),
            "evidence": [],
        })

    meta_out = {k: v for k, v in meta.items() if not k.startswith("_")}
    result = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "meta": meta_out,
        "catalogue": {"id": catalogue["catalogue_id"], "version": catalogue["catalogue_version"],
                      "guidance": catalogue["guidance"]},
        "guidance_text_loaded": bool(guidance_pages),
        "documents": [
            {"doc_id": d.doc_id, "name": d.name, "source": d.source, "kind": d.kind, "doc_type": d.doc_type,
             "pages": len(d.pages), "characters": d.char_count, "warnings": d.warnings}
            for d in docs
        ],
        "fetch_notes": fetch_notes or [],
        "cas_numbers_found": find_cas_numbers(segments),
        "components": components,
        "requirements": additive_results,
        "summary": summary,
        "scope_flags": scope_flags,
    }
    result["markdown"] = render_markdown(result, catalogue)
    return result


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

STATUS_ICONS = {"evidence_located": "✅", "partial": "🟠", "gap": "❌", "not_applicable": "➖",
                "conditional": "❔", "manual_review": "👁"}


def _md_escape(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _status_md(status: str) -> str:
    return f"{STATUS_ICONS.get(status, '')} {STATUS_LABELS.get(status, status)}".strip()


def _grounding_md(res: dict[str, Any]) -> str:
    g = res.get("grounding") or {}
    status = g.get("status", "verified_primary")
    if status == "anchored_in_guidance_text":
        pages = ", ".join(sorted({f"p.{p['page']}" for p in g.get("passages", [])}))
        return f"anchored in guidance text ({pages})"
    if status == "not_found_in_guidance_text":
        return "⚠ anchors NOT found in loaded guidance text — review catalogue entry"
    return f"catalogue quote, p.{res.get('guidance_page')}"


def _requirement_block(res: dict[str, Any], level: str = "###") -> str:
    lines = [f"{level} {res['guidance_section']} {res['title']} `{res['id']}`", "",
             f"> *Guidance (§{res['guidance_section']}, p.{res['guidance_page']}):* \"{res['quote']}\"", "",
             f"**Status:** {_status_md(res['status'])} · *Grounding:* {_grounding_md(res)}", ""]
    if res.get("applicability_note"):
        lines += [f"*Applicability:* {res['applicability_note']}", ""]
    if res.get("conditional_note"):
        lines += [f"*Note:* {res['conditional_note']}", ""]
    if res["status"] == "not_applicable":
        return "\n".join(lines + ["Not applicable on the basis of the product form / route / production type / additive type entered.", ""])
    if res["status"] == "manual_review":
        lines += ["*Scientific-officer review item: this requirement cannot be assessed by pattern detection.*", ""]
    if res.get("sub_items"):
        lines += ["| Element | Located | Value / evidence | Source |", "|---|---|---|---|"]
        for sub in res["sub_items"]:
            value = sub.get("value", {})
            shown = value.get("value") if value else ""
            src = value.get("citation") if value else ", ".join(sub["citations"][:3])
            qualifier = "" if sub["required"] else " *(where relevant)*"
            if sub.get("note"):
                qualifier += f" *({sub['note']})*"
            lines.append(
                f"| {_md_escape(sub['label'])}{qualifier} | {'yes' if sub['located'] else '**no**'} | "
                f"{_md_escape(shown) or (('“' + _md_escape(sub.get('snippet')) + '”') if sub['located'] else '**[DATA GAP]**')} | {_md_escape(src) or '—'} |"
            )
        lines.append("")
    bc = res.get("batch_check")
    checks = list(res.get("checks", []))
    if bc:
        ids = ", ".join(bc["batch_ids"][:10]) or "none detected"
        checks.insert(0, _check(f"≥ {bc['required_min']} batches", bc["met"],
                                f"{bc['detected']} detected; identifiers: {ids}"))
    if checks:
        lines.append("**Quantitative checks against the guidance:**")
        for c in checks:
            icon = "✅" if c["met"] else ("❌" if c["met"] is False else "❔")
            lines.append(f"- {icon} {c['label']}: {_md_escape(c['detail'])}")
        lines.append("")
    for flag in res.get("flags", []):
        lines += [f"> ⚠ {flag['message']} ({', '.join(flag['citations'])})", ""]
    if res.get("evidence"):
        lines += ["<details><summary>Evidence excerpts</summary>", ""]
        lines += [f"- [{ev['citation']}] {_md_escape(ev['text'])}" for ev in res["evidence"][:5]]
        lines += ["", "</details>", ""]
    if res.get("missing"):
        lines.append("**Data gaps / points to clarify:**")
        lines += [f"- {_md_escape(m)}" for m in res["missing"]]
        lines.append("")
    if res.get("justification"):
        lines.append("**Possible applicant justification located (guidance p.5: reasons should be given for omissions):**")
        lines += [f"- [{j['citation']}] {_md_escape(j['text'])}" for j in res["justification"]]
        lines.append("")
    return "\n".join(lines)


IDENTITY_ROWS = [("generic_name", "Generic name"), ("iupac_name", "Chemical name (IUPAC)"), ("synonyms", "Other names / abbreviations"),
                 ("cas", "CAS No"), ("ec", "EINECS / EC No"), ("molecular_formula", "Molecular formula"),
                 ("structural_formula", "Structural formula"), ("smiles", "openSMILES"), ("molecular_weight", "Molecular weight"),
                 ("flavis", "FLAVIS No"), ("purity", "Purity / specification"), ("water_solubility", "Solubility in water"),
                 ("log_kow", "log Kow"), ("pka", "pKa"), ("melting_point", "Melting point"), ("optical_rotation", "Specific optical rotation")]


def _components_md(result: dict[str, Any]) -> str:
    if not result["components"]:
        return "**[DATA GAP]** No component identified. Enter each active substance/component of the product (§2.1.3, §2.2.1.1)."
    blocks = []
    for i, comp in enumerate(result["components"], start=1):
        c = comp["component"]
        ident = comp["identity"]
        title = c.get("name") or c.get("cas") or f"Component {i}"
        blocks += [f"### Component {i}: {title}", "",
                   f"*Role:* {c.get('role') or 'not stated'}" + (f" · detected from {c['detected_from']}" if c.get("detected_from") else ""), ""]
        if comp.get("cas_check"):
            blocks += [f"*CAS check:* {comp['cas_check']}", ""]
        blocks += ["| Identity element (§2.2.1.1 / §2.2.2.1) | Value as stated in the dossier | Source |", "|---|---|---|"]
        for key, label in IDENTITY_ROWS:
            v = ident.get(key)
            blocks.append(f"| {label} | {_md_escape(v['value']) if v else '**[not located]**'} | {v['citation'] if v else '—'} |")
        blocks.append("")
        for res in comp["requirements"]:
            blocks.append(_requirement_block(res, level="####"))
    return "\n".join(blocks)


def _gap_table_md(result: dict[str, Any]) -> str:
    rows = ["| § | Requirement | Scope | Status | Missing / to clarify | Justification located |", "|---|---|---|---|---|---|"]
    order = {"gap": 0, "partial": 1, "conditional": 2, "manual_review": 3, "evidence_located": 4, "not_applicable": 5}
    entries = [(res, "Additive") for res in result["requirements"]]
    for comp in result["components"]:
        name = comp["component"].get("name") or comp["component"].get("cas") or "component"
        entries += [(res, name) for res in comp["requirements"]]
    entries.sort(key=lambda e: (order.get(e[0]["status"], 9), [int(x) for x in e[0]["guidance_section"].split(".")]))
    for res, scope in entries:
        missing = "; ".join(res.get("missing", [])[:4]) or "—"
        just = ", ".join(j["citation"] for j in res.get("justification", [])) or "—"
        rows.append(f"| {res['guidance_section']} | {_md_escape(res['title'])} `{res['id']}` | {_md_escape(scope)} | "
                    f"{_status_md(res['status'])} | {_md_escape(missing)} | {just} |")
    s = result["summary"]
    head = (f"Not located: **{s.get('gap', 0)}** · Partially addressed: **{s.get('partial', 0)}** · "
            f"Applicability to confirm: **{s.get('conditional', 0)}** · SO review: **{s.get('manual_review', 0)}** · "
            f"Evidence located: **{s.get('evidence_located', 0)}** · Not applicable: **{s.get('not_applicable', 0)}**")
    flags = []
    for f in result.get("scope_flags", []):
        cites = ", ".join(e["citation"] for e in f.get("evidence", [])[:3])
        flags.append(f"> **{f['flag']}.** {f['detail']}{(' Evidence: ' + cites + '.') if cites else ''}")
    general = ("Per the guidance (p.5): *\"Reasons should be given for the omission from the dossier of any data prescribed there.\"* "
               "For each gap below, check whether the applicant has justified the omission.")
    return "\n".join([head, "", general, ""] + sum(([f, ""] for f in flags), []) + rows)


def _documents_md(result: dict[str, Any]) -> str:
    if not result["documents"]:
        return "**No documents were processed.**"
    rows = ["| ID | Document | Type (auto-classified) | Pages | Characters | Warnings |", "|---|---|---|---|---|---|"]
    for d in result["documents"]:
        rows.append(f"| {d['doc_id']} | {_md_escape(d['name'])} | {_md_escape(d['doc_type'])} | {d['pages']} | {d['characters']} | {_md_escape('; '.join(d['warnings'])) or '—'} |")
    notes = [f"- {_md_escape(n)}" for n in result.get("fetch_notes", [])]
    return "\n".join(rows + ([""] + ["**Retrieval notes:**"] + notes if notes else []))


def _grounding_section_md(result: dict[str, Any], catalogue: dict[str, Any]) -> str:
    g = catalogue["guidance"]
    lines = [f"- Guidance: {g['citation']} [doi:{g['doi']}]({g['url']}). {g['license']}.",
             f"- Legal basis: {g['legal_basis']}.",
             f"- Requirement catalogue `{catalogue['catalogue_id']}` v{catalogue['catalogue_version']} — every requirement quotes the guidance "
             "verbatim with section and page. Scope: " + catalogue["scope"]]
    if result["guidance_text_loaded"]:
        lines.append("- Guidance text loaded: each requirement was re-anchored against the guidance text at run time "
                     "(grounding column). Requirements marked ⚠ could not be anchored and must not be relied upon.")
    else:
        lines.append("- Guidance text not loaded in this instance: grounding relies on the catalogue quotes (verified against "
                     "the guidance by the automated test suite).")
    lines.append("- Extraction is deterministic (pattern-based); every value carries a document/page citation. "
                 "Statuses indicate whether evidence was *located*, not whether it is adequate or compliant.")
    return "\n".join(lines)


def render_markdown(result: dict[str, Any], catalogue: dict[str, Any], template_path: Path = TEMPLATE_PATH) -> str:
    template = template_path.read_text(encoding="utf-8")
    meta = result["meta"]
    by_section: dict[str, list[str]] = {}
    for res in result["requirements"]:
        by_section.setdefault(res["section"], []).append(_requirement_block(res))
    product = meta.get("product_name") or "[product name not entered]"
    header = "\n".join([
        f"*Applicant:* {meta.get('applicant') or '[not entered]'} · *Dossier / question reference:* {meta.get('dossier_ref') or '[not entered]'}  ",
        f"*Product form:* {meta.get('product_form') or 'not stated'} · *Routes:* {', '.join(meta.get('routes') or []) or 'not stated'} · "
        f"*Production type:* {', '.join(meta.get('production_types') or []) or 'not stated'} · *Additive type:* {meta.get('additive_type') or 'not stated'}  ",
        f"*Generated:* {result['generated_at']} by KEvidence step 0 (chemical characterisation MVP) against "
        f"{catalogue['guidance']['citation']}  ",
        "**Draft for scientific-officer verification — contains confidential dossier information.**",
    ])
    caveats = ("---\n*This draft structures the applicant's evidence against the FEEDAP (2017) guidance on identity, characterisation "
               "and conditions of use of feed additives. It is not an EFSA assessment or conclusion. Values are reproduced as stated "
               "in the dossier and must be verified against the source documents. A 'not located' element can result from "
               "extraction limits (scanned PDFs, images, unusual table layouts) as well as from a true data gap.*")
    narrative = result.get("narrative") or {}
    replacements = {
        "PRODUCT_NAME": product,
        "HEADER": header,
        "DOCUMENT_REGISTER": _documents_md(result),
        "GAP_ANALYSIS": _gap_table_md(result),
        "GROUNDING": _grounding_section_md(result, catalogue),
        "CAVEATS": caveats,
    }
    for section in catalogue["template_sections"]:
        token = section["token"]
        replacements[token] = "\n".join(by_section.get(token, []))
    replacements["S2_2"] = _components_md(result)
    for token, text in narrative.items():
        if token in replacements and text.get("text"):
            flag = ("all numbers traced to dossier excerpts" if text.get("grounded")
                    else f"⚠ values not traced to dossier excerpts: {', '.join(text.get('untraced', []))}")
            replacements[token] = (f"**Draft narrative (LLM-assisted; {flag})**\n\n> {text['text']}\n\n" + replacements[token])

    def sub(m):
        return replacements.get(m.group(1), m.group(0))
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", sub, template)


# ---------------------------------------------------------------------------
# Optional LLM drafting (off by default)
# ---------------------------------------------------------------------------

NARRATIVE_SYSTEM_PROMPT = """You draft the characterisation section of an EFSA FEEDAP scientific opinion.
Rules (strict):
1. Use ONLY the evidence excerpts provided. Never add values, batch numbers, methods or conclusions that are not in the excerpts.
2. Follow the requirement text, which comes from the FEEDAP (2017) identity/characterisation guidance (EFSA Journal 15(10):5023).
3. Report values as stated by the applicant ("The applicant reported…"), cite the source in square brackets, e.g. [D2 p.4].
4. Where the evidence is missing or below the guidance minimum (e.g. fewer batches than required), say so explicitly.
5. Do not express safety or efficacy conclusions.
Return JSON: {"sections": {"<SECTION_TOKEN>": "<one paragraph>"}} for the section tokens supplied."""


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".").replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", text or "")}


def draft_narrative(result: dict[str, Any], complete: Callable[[str, str], str], max_chars: int = 24000) -> dict[str, Any]:
    """Draft one paragraph per section with an LLM and check every number against the evidence."""
    sections: dict[str, list[dict[str, Any]]] = {}
    for res in result["requirements"]:
        sections.setdefault(res["section"], []).append(res)
    for comp in result["components"]:
        for res in comp["requirements"]:
            sections.setdefault("S2_2", []).append(res)
    payload, evidence_text = [], []
    for token, items in sections.items():
        block = {"section": token, "requirements": []}
        for res in items:
            ev = [f"[{e['citation']}] {e['text']}" for e in res.get("evidence", [])[:6]]
            evidence_text += ev
            block["requirements"].append({
                "id": res["id"], "guidance_section": res["guidance_section"], "requirement": res["requirement"], "status": res["status"],
                "missing": res.get("missing", []), "batch_check": res.get("batch_check"), "evidence": ev,
            })
        payload.append(block)
    user = json.dumps(payload)[:max_chars]
    raw = complete(NARRATIVE_SYSTEM_PROMPT, user)
    try:
        parsed = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        drafted = parsed.get("sections", {})
    except Exception:
        return {}
    allowed = _numbers(" ".join(evidence_text) + " " + user)
    out = {}
    for token, text in drafted.items():
        if not isinstance(text, str):
            continue
        citation_numbers = _numbers(" ".join(re.findall(r"\[[^\]]*\]", text)))
        untraced = sorted(n for n in _numbers(text) - allowed - citation_numbers)
        out[token] = {"text": text.strip(), "grounded": not untraced, "untraced": untraced}
    return out


# ---------------------------------------------------------------------------
# Assistant grounding helper
# ---------------------------------------------------------------------------

QUESTION_STOPWORDS = {
    "what", "which", "when", "where", "does", "should", "would", "could", "must", "with", "from", "that", "this",
    "there", "their", "they", "them", "have", "about", "into", "than", "then", "also", "only", "each", "other",
    "guidance", "require", "required", "requires", "requirement", "requirements", "explain", "tell", "please",
    "need", "needed", "needs", "data", "information", "provide", "provided", "additive", "additives", "feed",
    "efsa", "feedap", "dossier", "applicant", "says", "much", "many", "matter", "most", "exactly", "gaps",
}


def guidance_context_for_question(question: str, catalogue: Optional[dict[str, Any]] = None,
                                  guidance_pages: Optional[list[str]] = None, limit: int = 6) -> tuple[str, list[str]]:
    """Select catalogue requirements (and guidance passages, when loaded) relevant to a question."""
    catalogue = catalogue or load_catalogue()
    words = {w for w in re.findall(r"[a-z]{4,}", question.lower())} - QUESTION_STOPWORDS
    scored = []
    for req in catalogue["requirements"]:
        hay = f"{req['title']} {req['requirement']} {req['quote']} {' '.join(req.get('guidance_anchors', []))}".lower()
        score = sum(1 for w in words if w in hay)
        if re.search(re.escape(req["id"]), question, re.I) or re.search(r"(§|section\s*)" + re.escape(req["guidance_section"]) + r"\b", question, re.I):
            score += 10
        if score:
            scored.append((score, req))
    scored.sort(key=lambda x: -x[0])
    chosen = [r for _, r in scored[:limit]]
    anchors = anchor_requirements(catalogue, guidance_pages)
    parts = []
    for req in chosen:
        g = anchors[req["id"]]
        part = (f"[{req['id']}] Guidance §{req['guidance_section']} (p.{req['guidance_page']}): {req['title']}\n"
                f"Requirement (paraphrase): {req['requirement']}\nVerbatim guidance quote: \"{req['quote']}\"\n"
                f"Grounding status: {g['status']}")
        for p in g.get("passages", [])[:2]:
            part += f"\nGuidance text p.{p['page']}: \"{p['excerpt']}\""
        parts.append(part)
    return "\n\n".join(parts), [r["id"] for r in chosen]
