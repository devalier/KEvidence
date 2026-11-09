"""Sanitisation of PDF documents for publication under the Transparency Regulation.

Regulation (EU) 2019/1381 amended the General Food Law (Regulation (EC) No 178/2002, Articles 38 to 39e):
EFSA publishes the documents supporting its scientific outputs, with confidential information and personal
data masked. EFSA's practical arrangements (Decision of the Executive Director, ver. 2 of 18.01.2021) define
sanitisation as masking "in accordance with a confidentiality request or with a confidentiality decision,
including the masking of personal data" (Art. 3(1)(c)) and list the closed set of items that may be claimed
confidential, by sector (Annex a-h). The rules live in
data/guidance/transparency/efsa_2021_pa_transparency_confidentiality_rules.json; every entry quotes the
decision verbatim and is re-anchored against the bundled PDF.

Pipeline (stateless: the document is processed in memory and never stored):
1. propose()  - local detectors (personal data; Annex cue phrases), the confidentiality request/decision
                items the user supplies, and optionally an LLM pass. Every proposal names an Annex rule,
                carries the exact text and its rectangles on the page, and starts selected only when
                the rules say it must be masked (personal data, items under a request or decision).
2. The scientific officer reviews and selects.
3. apply()    - true redaction (the text, image pixels and links under each box are removed, not covered),
                annotations, form fields, metadata, XMP, JavaScript and attachments are scrubbed, the file is
                rewritten (no incremental update) and the output is re-read to verify nothing masked remains.

KEvidence proposes; the decision on what is confidential stays with EFSA (Art. 11 of the arrangements).
"""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

import pymupdf

import characterisation as charmod

TRANSPARENCY_DIR = charmod.GUIDANCE_ROOT / "transparency"
RULES_PATH = TRANSPARENCY_DIR / "efsa_2021_pa_transparency_confidentiality_rules.json"

MAX_FILE_BYTES = charmod.MAX_FILE_BYTES
MAX_PAGES = 400
MAX_PREVIEW_PAGES = 60
MAX_AI_PAGES = 80
AI_BATCH_CHARS = 9000
MAX_PROPOSALS = 2000
MAX_CUE_PROPOSALS_PER_RULE = 25
PREVIEW_WIDTH_PX = 760

STEP = "sanitisation"
PERSONAL_RULE = "PA-ANX-39E-1-PERSONAL-DATA"
TESTING_RULE = "PA-ANX-39E-2-TESTING-PERSONNEL"
NONCONF_RULE = "PA-ART4-5-PERSONAL-DATA"
REQUEST_RULE = "REQUEST"


class SanitisationError(ValueError):
    """The input cannot be sanitised (not a PDF, password-protected, too large...)."""


# ---------------------------------------------------------------------------
# Rules (EFSA practical arrangements, verbatim and anchored)
# ---------------------------------------------------------------------------

def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    """The rules catalogue plus the text of the bundled decision, shaped like a domain bundle so the
    assistant retrieval of characterisation.py works on it unchanged."""
    catalogue = charmod.load_knowledge_catalogue(path)
    sectors = catalogue.get("sectors") or {}
    for entry in catalogue["entries"]:
        if entry["kind"] not in ("procedure", "personal_data", "confidential_item"):
            raise ValueError(f"{entry['id']}: unknown kind {entry['kind']}")
        if entry["kind"] != "procedure":
            for key in ("label", "legal_basis", "default_action", "annex_sections"):
                if not entry.get(key):
                    raise ValueError(f"{entry['id']} is missing '{key}'")
            unknown = set(entry["annex_sections"]) - set(sectors)
            if unknown:
                raise ValueError(f"{entry['id']}: unknown Annex sections {sorted(unknown)}")
        for pattern in entry.get("cues", []):
            re.compile(pattern, re.I)
    pages = charmod.load_pdf_pages(path.parent / catalogue["guidance"]["bundled_file"])
    source = {"role": "primary", "catalogue": catalogue, "pages": pages}
    return {"id": "transparency", "label": "Transparency Regulation — sanitisation", "directory": path.parent,
            "assistant_role": "EFSA staff sanitising documents for publication", "datasets": {},
            "catalogue": catalogue, "pages": pages, "primary": source, "sources": [source]}


def rules_for_sector(rules: dict[str, Any], sector: str) -> list[dict[str, Any]]:
    """The maskable items (personal data and Annex items) that apply in one Annex section."""
    sectors = rules["catalogue"]["sectors"]
    if sector not in sectors:
        raise SanitisationError(f"Unknown sector '{sector}'. Available: {', '.join(sectors)}.")
    return [e for e in rules["catalogue"]["entries"] if e["kind"] != "procedure" and sector in e["annex_sections"]]


def rule_by_id(rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in rules["catalogue"]["entries"]}


def rules_status(rules: dict[str, Any], sector: Optional[str] = None) -> dict[str, Any]:
    cat = rules["catalogue"]
    anchors = charmod.anchor_requirements(cat, rules["pages"])
    applicable = {e["id"] for e in rules_for_sector(rules, sector)} if sector else None
    entries = []
    for e in cat["entries"]:
        entries.append({
            "id": e["id"], "title": e["title"], "kind": e["kind"], "section": e["guidance_section"],
            "page": e["guidance_page"], "label": e.get("label", ""), "legal_basis": e.get("legal_basis", ""),
            "default_action": e.get("default_action"), "safety_exception": e.get("safety_exception", ""),
            "annex_sections": e.get("annex_sections", []), "requirement": e["requirement"], "quote": e["quote"],
            "applies": (e["id"] in applicable) if applicable is not None else None,
            "grounding": anchors[e["id"]]["status"],
        })
    counts: dict[str, int] = {}
    for a in anchors.values():
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    return {
        "guidance": cat["guidance"], "catalogue_id": cat["catalogue_id"], "catalogue_version": cat["catalogue_version"],
        "scope": cat["scope"], "sectors": cat["sectors"], "guidance_text_loaded": bool(rules["pages"]),
        "guidance_pages": len(rules["pages"] or []), "verification_counts": counts, "entries": entries,
        "broken": [rid for rid, a in anchors.items() if a["status"] == "not_found_in_guidance_text"],
    }


# ---------------------------------------------------------------------------
# PDF access
# ---------------------------------------------------------------------------

def open_pdf(content: bytes) -> pymupdf.Document:
    if not content:
        raise SanitisationError("Empty file.")
    if len(content) > MAX_FILE_BYTES:
        raise SanitisationError(f"File exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if not content.lstrip()[:5].startswith(b"%PDF"):
        raise SanitisationError("Sanitisation works on PDF files only. Convert the document to PDF first.")
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise SanitisationError(f"Unreadable PDF: {type(exc).__name__}") from None
    if doc.needs_pass:
        doc.close()
        raise SanitisationError("The PDF is password-protected. Remove the protection, then upload it again.")
    if doc.page_count > MAX_PAGES:
        doc.close()
        raise SanitisationError(f"At most {MAX_PAGES} pages per document.")
    return doc


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", charmod._fix_ligatures(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _compact(text: str) -> str:
    return charmod._compact(_norm(text))[0]


def _token(word: str) -> str:
    return re.sub(r"^[^\w@]+|[^\w@]+$", "", _norm(word).lower())


def _rect_list(rect: pymupdf.Rect) -> list[float]:
    return [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]


def _merge_line_rects(rects: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """Merge word rectangles that sit on the same text line into one box per line."""
    merged: list[pymupdf.Rect] = []
    for r in sorted(rects, key=lambda r: (round(r.y0), r.x0)):
        if merged:
            last = merged[-1]
            same_line = abs(r.y0 - last.y0) < max(2.0, 0.4 * last.height) and r.x0 - last.x1 < 3 * max(last.height, 6)
            if same_line:
                merged[-1] = last | r
                continue
        merged.append(pymupdf.Rect(r))
    return merged


def locate(page: pymupdf.Page, text: str, words: Optional[list] = None) -> list[pymupdf.Rect]:
    """Rectangles of every occurrence of `text` on the page. Exact character search first (case-insensitive,
    across line breaks); if extraction spacing differs, fall back to matching the word sequence."""
    text = _norm(text)
    if not text:
        return []
    hits = page.search_for(text)
    if hits:
        return _merge_line_rects(hits)
    wanted = [t for t in (_token(w) for w in text.split(" ")) if t]
    if not wanted:
        return []
    words = words if words is not None else page.get_text("words")
    toks = [_token(w[4]) for w in words]
    n = len(wanted)
    out: list[pymupdf.Rect] = []
    for i in range(len(toks) - n + 1):
        if toks[i] == wanted[0] and toks[i:i + n] == wanted:
            out.extend(pymupdf.Rect(w[:4]) for w in words[i:i + n])
    return _merge_line_rects(out)


# ---------------------------------------------------------------------------
# Local detectors
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w-])")
PHONE_RE = re.compile(r"(?:(?<=\s)|(?<=^)|(?<=[:(]))(?:\+|00)\d{1,3}[\s./-]?(?:\(0\)\s?)?\d{1,4}(?:[\s./-]?\d{2,5}){1,4}(?!\d)"
                      r"|(?i:(?:tel(?:ephone)?|phone|mobile|mob|fax|gsm)\.?\s*(?:no\.?)?\s*[:.]?\s*)(\(?\d[\d\s()./-]{6,18}\d)", re.M)
UPPER = "A-ZÀ-ÖØ-ÞĀ-ŽŁ"
LOWER = "a-zß-öø-ÿā-žł"
NAME_WORD = rf"[{UPPER}][{LOWER}'’-]+(?:-[{UPPER}][{LOWER}]+)?"
PARTICLE = r"(?:van|von|de|da|di|del|der|den|du|la|le|dos|das|ten|ter)"
PERSON = (rf"(?:(?:[{UPPER}]\.\s?){{1,3}}(?:{PARTICLE}\s)?{NAME_WORD}"
          rf"|{NAME_WORD}(?:\s(?:[{UPPER}]\.\s?){{0,2}}(?:{PARTICLE}\s)?{NAME_WORD}){{1,3}})")
TITLE_RE = re.compile(rf"\b(?:Dr|Prof|Mr|Mrs|Ms|Mme|Dott|Dott\.ssa|Ing|Dipl\.-Ing)\.?\s+(?:[{UPPER}]\.\s?)*{NAME_WORD}(?:\s(?:{PARTICLE}\s)?{NAME_WORD})?")
ROLE_RE = re.compile(
    r"(?im)^[ \t]*(?P<role>study\s+director|principal\s+investigator|(?:co-?)?investigators?|study\s+monitor|monitor|"
    r"(?:study\s+)?pathologist|(?:study\s+|attending\s+)?veterinarian|technicians?|statistician|study\s+personnel|authors?|"
    r"(?:report\s+)?prepared\s+by|reviewed\s+by|approved\s+by|checked\s+by|verified\s+by|audited\s+by|written\s+by|signed(?:\s+by)?|"
    r"contact(?:\s+person)?|responsible\s+person|quality\s+assurance(?:\s+(?:manager|officer|auditor|unit))?|qa\s+(?:manager|officer|auditor)|"
    r"test\s+facility\s+management|sponsor(?:'s)?\s+representative|scientist|analyst|name)\s*[:–-]\s*(?P<value>.+)$")
QUALIFICATIONS_RE = re.compile(r",?\s*\b(?:PhD|Ph\.D\.|DVM|MSc|M\.Sc\.|BSc|B\.Sc\.|MD|DABT|ERT|FRCPath|Dipl\.?\s?ECVP|MRCVS)\b\.?", re.I)
SIGNATURE_RE = re.compile(r"\b(signature|signed|sign-off|date\s+and\s+sign)\w*", re.I)
STREET_RE = re.compile(
    rf"\b\d{{1,5}}[a-z]?,?\s(?:[{UPPER}][\w'’.-]+\s){{1,3}}(?:Street|St\.|Road|Rd\.?|Avenue|Ave\.?|Lane|Way|Drive|Boulevard|Blvd\.?|Close|Place|Square)\b"
    rf"|\b(?:Via|Viale|Piazza|Rue|Avenue|Boulevard|Calle|Avenida|Rua|Plaza|ul\.)\s(?:[\w'’.-]+\s){{0,4}}\d{{1,5}}[a-z]?\b"
    rf"|\b[{UPPER}][{LOWER}-]*(?:straße|strasse|str\.|weg|gasse|allee|platz|laan|straat|gracht|vej|gade|gatan|vägen|katu)\s\d{{1,5}}[a-z]?\b")
REFERENCES_HEADING_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(references|bibliography|literature(?:\s+cited)?|cited\s+literature)\s*$", re.I)
TOX_CONTEXT_RE = re.compile(r"\b(GLP|toxicity|toxicolog\w*|genotoxic\w*|in\s+vivo|rats?|mice|dogs?|rabbits?|chickens?|broilers?|"
                            r"piglets?|pigs?|cattle|calves|fish|test\s+animals?|necropsy|histopatholog\w*|tolerance\s+study)\b", re.I)
NOT_A_PERSON = re.compile(r"\b(GmbH|Ltd|Limited|Inc|S\.?A\.?|S\.?p\.?A\.?|B\.?V\.?|AG|Srl|Company|Laborator\w*|Universit\w*|Institut\w*|"
                          r"Department|Facility|Authority|Agency|Panel|Committee|Table|Figure|Annex|Appendix|Section|Study|Report|Guideline|"
                          r"Regulation|Directive|Method|Analysis|Results|Batch|Product|Sample|European|Food|Feed|Safety)\b")


def _person_values(value: str) -> list[str]:
    """Split a 'Role: A. Smith, PhD; B. Jones' value into the person names it contains."""
    value = QUALIFICATIONS_RE.sub("", value)
    names = []
    for part in re.split(r"\s*(?:;|,|\band\b|&|/)\s*", value):
        part = part.strip(" .:\t")
        m = re.fullmatch(rf"(?:(?:Dr|Prof|Mr|Mrs|Ms|Mme)\.?\s+)?({PERSON})", part)
        if m and not NOT_A_PERSON.search(part):
            names.append(part)
    return names


class _Collector:
    def __init__(self, rules: dict[str, Any], sector: str):
        self.by_id = rule_by_id(rules)
        self.applicable = {e["id"] for e in rules_for_sector(rules, sector)}
        self.items: list[dict[str, Any]] = []
        self.index: dict[tuple, dict[str, Any]] = {}

    def add(self, page: pymupdf.Page, text: str, rule_id: str, *, category: str, source: str, reason: str,
            selected: bool, confidence: str = "high", rects: Optional[list[pymupdf.Rect]] = None,
            flags: Optional[list[str]] = None, words: Optional[list] = None, basis_text: str = "") -> Optional[dict[str, Any]]:
        if len(self.items) >= MAX_PROPOSALS:
            return None
        rects = rects if rects is not None else locate(page, text, words)
        if not rects:
            return None
        key = (page.number + 1, _compact(text) if category != "signature" else tuple(_rect_list(rects[0])))
        if key in self.index:
            existing = self.index[key]
            if source not in existing["sources"]:
                existing["sources"].append(source)
                if source in ("request", "manual"):
                    existing["group"] = "request"
                existing["reason"] += f" | {source.upper()}: {reason}"
                existing["selected"] = existing["selected"] or selected
            return existing
        rule = self.by_id.get(rule_id, {})
        kind = "request" if rule_id == REQUEST_RULE else rule.get("kind", "personal_data")
        rot = page.rotation_matrix
        item = {
            "id": f"S{len(self.items) + 1}", "page": page.number + 1, "text": _norm(text)[:600], "category": category,
            "rule_id": rule_id, "kind": kind,
            "redaction_type": "personal_data" if kind == "personal_data" else "confidential_information",
            # What the reviewer sees: items from the request/decision or added by hand are grouped as such.
            "group": "request" if source in ("request", "manual") or kind == "request" else kind,
            "label": rule.get("label") or (basis_text or "Confidentiality request/decision"),
            "legal_basis": rule.get("legal_basis") or basis_text or "As stated in the confidentiality request/decision",
            "sources": [source], "reason": reason, "confidence": confidence, "selected": bool(selected),
            "flags": flags or [], "rects": [_rect_list(r) for r in rects],
            "view_rects": [_rect_list(pymupdf.Rect(r) * rot) for r in rects],
        }
        self.items.append(item)
        self.index[key] = item
        return item


def _reference_pages(doc: pymupdf.Document) -> dict[int, int]:
    """{page_number: first line index} of reference-list sections, where author names are public (Art. 39e(1)(b))."""
    out: dict[int, int] = {}
    in_refs = False
    for page in doc:
        lines = page.get_text("text").splitlines()
        if in_refs:
            out[page.number + 1] = 0
        for i, line in enumerate(lines):
            if REFERENCES_HEADING_RE.match(line):
                in_refs = True
                out.setdefault(page.number + 1, i)
            elif in_refs and re.match(r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(appendix|annex|annexes|abbreviations)\b", line, re.I) and len(line) < 60:
                in_refs = False
    return out


def _in_exception(text: str, exceptions: list[str]) -> bool:
    c = _compact(text)
    return bool(c) and any(c in e or (len(e) > 4 and e in c) for e in exceptions)


def detect_local(doc: pymupdf.Document, rules: dict[str, Any], sector: str, applicant: str = "",
                 applicant_address: str = "", collector: Optional[_Collector] = None) -> tuple[_Collector, dict[str, Any]]:
    col = collector or _Collector(rules, sector)
    exceptions = [_compact(x) for x in [applicant, *re.split(r"[\n;]+", applicant_address or "")] if _compact(x)]
    refs = _reference_pages(doc)
    full_text = "\n".join(p.get_text("text") for p in doc)
    tox_context = bool(TOX_CONTEXT_RE.search(full_text))
    person_rule = TESTING_RULE if tox_context else PERSONAL_RULE
    skipped = {"applicant": 0, "reference_list": 0}
    no_text_pages = []
    applicable = col.applicable

    for page in doc:
        pno = page.number + 1
        text = page.get_text("text")
        words = page.get_text("words")
        if not text.strip():
            no_text_pages.append(pno)
            continue
        lines = text.splitlines()
        ref_from = refs.get(pno)
        ref_text = "\n".join(lines[ref_from:]) if ref_from is not None else ""

        def in_refs(s: str) -> bool:
            return bool(ref_text) and _compact(s) in _compact(ref_text) and _compact(s) not in _compact("\n".join(lines[:ref_from]))

        def personal(s: str, category: str, reason: str, rule_id: str = PERSONAL_RULE, selected: bool = True, confidence: str = "high"):
            if _in_exception(s, exceptions):
                skipped["applicant"] += 1
                return
            if in_refs(s):
                skipped["reference_list"] += 1
                return
            col.add(page, s, rule_id, category=category, source="rule", reason=reason, selected=selected,
                    confidence=confidence, words=words)

        for m in EMAIL_RE.finditer(text):
            personal(m.group(0), "email", "E-mail address of a natural person or a personal mailbox (Art. 4(5) PA; Art. 39e GFL).")
        for m in PHONE_RE.finditer(text):
            s = (m.group(1) or m.group(0)).strip()
            if sum(ch.isdigit() for ch in s) >= 7:
                personal(s, "phone", "Telephone/fax number (Art. 4(5) PA; Art. 39e GFL).", confidence="medium")
        for m in ROLE_RE.finditer(text):
            for name in _person_values(m.group("value")):
                role = re.sub(r"\s+", " ", m.group("role")).strip().lower()
                testing = tox_context and role != "name"
                personal(name, "person",
                         f"Name of a natural person ({role})" + (" involved in testing or obtaining toxicological information (Art. 39e(2) GFL)." if testing
                                                                  else " (Art. 39e(1) GFL; Art. 4(5) PA)."),
                         rule_id=TESTING_RULE if testing else PERSONAL_RULE)
        for m in TITLE_RE.finditer(text):
            if not NOT_A_PERSON.search(m.group(0)):
                personal(m.group(0), "person", "Name of a natural person with a title (Art. 39e(1) GFL; Art. 4(5) PA).", rule_id=person_rule)
        applicant_lines = [ln for ln in lines if applicant and _compact(applicant) in _compact(ln)]
        for m in STREET_RE.finditer(text):
            if any(_compact(m.group(0)) in _compact(ln) for ln in applicant_lines):
                skipped["applicant"] += 1  # the address on the applicant's line is the applicant's (Art. 39e(1)(a))
                continue
            personal(m.group(0), "address", "Street address: mask if it is the address of a natural person or of individuals involved in testing "
                     "(Art. 39e(2) GFL); the applicant's address stays public (Art. 39e(1)(a)).", selected=False, confidence="medium")
        # Signatures: images placed next to a 'signature' / 'signed' line.
        sig_lines = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if SIGNATURE_RE.search(b[4] or "")]
        if sig_lines:
            for info in page.get_image_info():
                r = pymupdf.Rect(info["bbox"])
                if r.is_empty or r.width > page.rect.width * 0.8:
                    continue
                if any(abs(r.y0 - s.y1) < 120 or abs(s.y0 - r.y1) < 120 or r.intersects(s) for s in sig_lines):
                    col.add(page, f"[signature image p.{pno}]", PERSONAL_RULE, category="signature", source="rule",
                            reason="Image next to a signature line: handwritten signature of a natural person (Art. 39e GFL).",
                            selected=True, rects=[r])
        # Annex cue phrases: whole sentences proposed as candidates for a confidentiality request, never masked by default.
        sentences = [s for b in page.get_text("blocks") if b[6] == 0
                     for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z0-9(])", _norm(b[4]))]
        for rule_id in sorted(applicable):
            rule = col.by_id[rule_id]
            cues = [re.compile(p, re.I) for p in rule.get("cues", [])]
            if not cues:
                continue
            count = sum(1 for it in col.items if it["rule_id"] == rule_id and it["category"] == "cue")
            for sentence in sentences:
                if count >= MAX_CUE_PROPOSALS_PER_RULE:
                    break
                if len(sentence) < 12 or len(sentence) > 600 or not any(c.search(sentence) for c in cues):
                    continue
                if in_refs(sentence):
                    continue
                exc = rule.get("safety_exception")
                item = col.add(page, sentence, rule_id, category="cue", source="rule",
                               reason=f"Matches the Annex item '{rule['title']}'. Mask only if it is covered by a confidentiality request "
                                      f"(pending) or a confidentiality decision{' — ' + exc if exc else ''}.",
                               selected=False, confidence="low", words=words)
                if item:
                    count += 1
    notes = {"no_text_pages": no_text_pages, "tox_context": tox_context, "skipped_exceptions": skipped,
             "reference_pages": sorted(refs)}
    return col, notes


# ---------------------------------------------------------------------------
# Confidentiality request / decision items supplied by the user
# ---------------------------------------------------------------------------
# Confidentiality request / decision items supplied by the user
# ---------------------------------------------------------------------------

def parse_request_items(raw: str) -> list[dict[str, str]]:
    """One item per line: `text to mask | legal basis or rule id` (the basis is optional)."""
    items = []
    for line in (raw or "").splitlines()[:300]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        text, _, basis = line.partition("|")
        text = text.strip().strip('"“”')
        if text:
            items.append({"text": text[:600], "basis": basis.strip()[:200]})
    return items


def _resolve_basis(basis: str, by_id: dict[str, dict[str, Any]], applicable: set[str]) -> str:
    if not basis:
        return REQUEST_RULE
    if basis in by_id:
        return basis
    b = _compact(basis)
    for rid in applicable:
        if _compact(by_id[rid].get("label", "")) == b:
            return rid
    return REQUEST_RULE


def apply_requests(doc: pymupdf.Document, items: list[dict[str, str]], col: _Collector) -> list[dict[str, str]]:
    """Locate every request/decision item; returns the items not found verbatim (left for the AI pass or the user)."""
    unlocated = []
    for it in items:
        rule_id = _resolve_basis(it["basis"], col.by_id, col.applicable)
        found = False
        for page in doc:
            added = col.add(page, it["text"], rule_id, category="request", source="request",
                            reason="Listed in the confidentiality request/decision supplied (Art. 3(1)(c), Art. 13 PA).",
                            selected=True, basis_text=it["basis"])
            found = found or bool(added)
        if not found:
            unlocated.append(it)
    return unlocated


def locate_text(content: bytes, rules: dict[str, Any], sector: str, text: str, basis: str = "") -> list[dict[str, Any]]:
    """Every occurrence of a text the user wants masked, as selected proposals (manual addition during review)."""
    text = _norm(text)[:600]
    if not text:
        raise SanitisationError("Text to mask is empty.")
    col = _Collector(rules, sector)
    if basis and basis not in col.applicable:
        raise SanitisationError(f"Rule '{basis}' does not apply to sector '{sector}'.")
    doc = open_pdf(content)
    try:
        for page in doc:
            col.add(page, text, basis or REQUEST_RULE, category="manual", source="manual",
                    reason="Added by the reviewer during sanitisation.", selected=True, basis_text="" if basis else "As stated in the request/decision")
    finally:
        doc.close()
    return col.items


# ---------------------------------------------------------------------------
# AI-led review (the user's own AI provider; the local rules are the fallback and a cross-check)
# ---------------------------------------------------------------------------

# Shown with every result: rule-based detection is a fallback, not a sanitisation method.
AI_RECOMMENDATION = (
    "KEvidence recommends that sanitisation be performed by AI: a sovereign, domain-specific language model fine-tuned for "
    "sanitisation, or a frontier model where your organisation permits its use for this type of work. Pattern-based rules miss "
    "personal data and confidential information that is not written in a predictable form; use them only as a fallback and "
    "check every page.")

# Procedural rules of the practical arrangements the AI must apply when deciding (quoted verbatim from the catalogue).
AI_DECISION_RULES = ["PA-ART3-SANITISATION", "PA-ART9-4-CLOSED-LIST", "PA-ART10-A-PRECISE-SCOPE",
                     "PA-ART14-1-REVIEW-FORESEEABLE-EFFECTS", "PA-ART16-3-PENDING-NOT-DISCLOSED"]

AI_SYSTEM_PROMPT = """You sanitise a document for EFSA before publication under the Transparency Regulation (Regulation (EU)
2019/1381; Articles 38 to 39e of Regulation (EC) No 178/2002), applying EFSA's practical arrangements concerning transparency and
confidentiality (Decision of the Executive Director, 2021). You lead the review; EFSA staff check every finding, and EFSA decides
on confidentiality.

There are TWO types of redaction. Classify every finding as one of them and apply its rules:

A. PERSONAL DATA ("type": "personal_data") — always masked, no request needed.
   Rules (use only these rule_id values for type A):
{personal_rules}
   - Mask: names, initials or signatures identifying a natural person, personal e-mail addresses, phone and fax numbers,
     personal or home addresses, staff/badge IDs, any other data identifying a natural person.
   - Use {testing} for people involved in testing on vertebrate animals or in obtaining toxicological information (study
     directors, investigators, pathologists, veterinarians, technicians, QA staff, their addresses); otherwise {personal}.
   - NEVER mask (exceptions in the rules): the applicant's name and address ({applicant}); names of authors of published or
     publicly available studies (citations and reference lists); names of participants and observers in public meetings of
     EFSA's Scientific Committee, Panels and working groups; names of companies, laboratories or test facilities (legal
     persons are not personal data).

B. CONFIDENTIAL INFORMATION ("type": "confidential_information") — masked ONLY when claimed by the applicant (request
   pending a decision) or granted in a confidentiality decision. Only items on the closed list of the Annex for this sector
   qualify. Rules (use only these rule_id values for type B, or "REQUEST"):
{confidential_rules}
   - For every passage that falls within an Annex item, say which confidentiality request/decision item covers it in "claim"
     (e.g. "R2"), or null when none does. A passage with no claim is still reported (so staff can see it) but stays public.
   - If a request/decision item does not name an Annex item that fits, use rule_id "REQUEST" with its claim number.
   - Set "safety_relevant": true when the information is relevant to the assessment of safety or concerns foreseeable
     health effects (the Annex excludes it from confidentiality: e.g. impurities that may have adverse effects, composition
     needed for the exposure or safety assessment). Such information is never masked, even if claimed.
   - Never propose study results, conclusions, methods needed to understand the safety assessment, or general scientific
     content.

How EFSA's rules say to decide (verbatim):
{decision_rules}

Output rules:
1. Copy "text" EXACTLY, character for character, from the page text, and keep it minimal: the name, number or clause to mask,
   not the whole sentence or page (Art. 10(a)). At most 300 characters. Report every occurrence you see, page by page.
2. "reason": one short sentence that cites the rule (article and point).
3. Return JSON only: {{"findings": [{{"page": <int>, "text": "<exact>", "type": "personal_data|confidential_information",
   "rule_id": "<id>", "claim": "<R number or null>", "safety_relevant": <bool>, "reason": "<...>",
   "confidence": "high|medium|low"}}]}}. Return {{"findings": []}} when nothing qualifies."""


def _ai_rules_block(rules: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"   - {r['id']} {r.get('label', '')} — {r['title']}: \"{r['quote']}\""
        + (f" (exception: {r['safety_exception']})" if r.get("safety_exception") else "")
        for r in rules)


def _ai_decision_block(rules: dict[str, Any]) -> str:
    by_id = rule_by_id(rules)
    return "\n".join(f"   - {by_id[i]['title']} ({by_id[i].get('guidance_section', i)}): \"{by_id[i]['quote']}\""
                     for i in AI_DECISION_RULES if i in by_id)


def ai_propose(doc: pymupdf.Document, rules: dict[str, Any], sector: str, complete: Callable[[str, str], str],
               col: _Collector, applicant: str = "", applicant_address: str = "",
               request_items: Optional[list[dict[str, str]]] = None) -> dict[str, Any]:
    """AI-led review of both redaction types. The AI proposes; this function applies EFSA's rules to what it returns:
    personal data is masked; confidential information is masked only when tied to a supplied request/decision item and not
    relevant to safety; anything not on the cited page, under a rule that does not apply, or public by exception is rejected."""
    applicable = rules_for_sector(rules, sector)
    personal_rules = [r for r in applicable if r["kind"] == "personal_data"]
    confidential_rules = [r for r in applicable if r["kind"] == "confidential_item"]
    allowed = {r["id"] for r in applicable} | {REQUEST_RULE}
    exceptions = [_compact(x) for x in [applicant, *re.split(r"[\n;]+", applicant_address or "")] if _compact(x)]
    system = AI_SYSTEM_PROMPT.format(
        personal_rules=_ai_rules_block(personal_rules), confidential_rules=_ai_rules_block(confidential_rules) or "   - none in this sector",
        decision_rules=_ai_decision_block(rules), testing=TESTING_RULE, personal=PERSONAL_RULE,
        applicant=f"{applicant or 'not given'}; {applicant_address or 'address not given'}")
    sector_label = rules["catalogue"]["sectors"][sector]["label"]
    claims = {f"R{i + 1}": it for i, it in enumerate(request_items or [])}
    req_block = "\n".join(f"- {k}: {it['text']}" + (f" (basis: {it['basis']})" if it["basis"] else "") for k, it in claims.items())
    pages = [(p.number + 1, p.get_text("text")) for p in doc if p.number < MAX_AI_PAGES]
    batches, cur, size = [], [], 0
    for pno, text in pages:
        if not text.strip():
            continue
        if cur and size + len(text) > AI_BATCH_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append((pno, text[:AI_BATCH_CHARS]))
        size += len(text[:AI_BATCH_CHARS])
    if cur:
        batches.append(cur)
    stats = {"batches": len(batches), "pages_sent": sum(len(b) for b in batches), "accepted": 0,
             "by_type": {"personal_data": 0, "confidential_information": 0}, "claims_located": [],
             "rejected": {"unknown_rule": 0, "not_on_page": 0, "exception": 0, "malformed": 0}, "errors": []}
    if doc.page_count > MAX_AI_PAGES:
        stats["errors"].append(f"Only the first {MAX_AI_PAGES} pages were reviewed by the AI.")
    for batch in batches:
        user = (f"Sector: Annex ({sector}) {sector_label}\nApplicant: {applicant or 'not given'}\n"
                f"Confidentiality request/decision items (claims):\n{req_block or '- none supplied: no confidential information can be masked'}\n\n"
                + "\n\n".join(f"=== Page {pno} ===\n{text}" for pno, text in batch))
        try:
            raw = complete(system, user)
            findings = json.loads(raw or "{}").get("findings", [])
            if not isinstance(findings, list):
                raise ValueError
        except Exception as exc:
            stats["errors"].append(f"Pages {batch[0][0]}-{batch[-1][0]}: AI review failed ({type(exc).__name__}).")
            continue
        batch_pages = {pno for pno, _ in batch}
        for f in findings:
            if not isinstance(f, dict) or not isinstance(f.get("text"), str) or not str(f.get("text")).strip():
                stats["rejected"]["malformed"] += 1
                continue
            rule_id = str(f.get("rule_id") or "")
            if rule_id not in allowed:
                stats["rejected"]["unknown_rule"] += 1
                continue
            try:
                pno = int(f.get("page"))
            except (TypeError, ValueError):
                stats["rejected"]["malformed"] += 1
                continue
            text = f["text"].strip()[:300]
            kind = "request" if rule_id == REQUEST_RULE else col.by_id[rule_id]["kind"]
            if kind == "personal_data" and _in_exception(text, exceptions):
                stats["rejected"]["exception"] += 1
                continue
            if pno not in batch_pages:
                stats["rejected"]["not_on_page"] += 1
                continue
            claim_id = str(f.get("claim") or "").strip().upper()
            claim = claims.get(claim_id)
            if kind == "request" and not claim:
                stats["rejected"]["unknown_rule"] += 1  # "REQUEST" without a supplied claim has no basis
                continue
            safety = bool(f.get("safety_relevant")) and kind != "personal_data"
            confidence = f.get("confidence") if f.get("confidence") in ("high", "medium", "low") else "medium"
            reason = str(f.get("reason") or "")[:400] or "Proposed by the AI review."
            flags = ["safety_relevant"] if safety else []
            if kind == "personal_data":
                selected = confidence != "low"
            else:
                # Art. 9(4) and Art. 16(3) PA: confidential information is masked only when claimed (pending) or granted;
                # Annex exception / Art. 14: never when relevant to the safety assessment.
                selected = bool(claim) and not safety
                reason += (f" Claimed in {claim_id}: “{claim['text'][:120]}”." if claim
                           else " No confidentiality request/decision item covers it: stays public unless claimed.")
            item = col.add(doc[pno - 1], text, rule_id, category="ai" if kind != "request" else "request", source="ai",
                           reason=reason, selected=selected, confidence=confidence, flags=flags,
                           basis_text=(claim or {}).get("basis", ""))
            if item is None:
                stats["rejected"]["not_on_page"] += 1
                continue
            if claim:
                if item["group"] == "confidential_item":
                    item["group"] = "request"
                if claim_id not in stats["claims_located"]:
                    stats["claims_located"].append(claim_id)
            if safety:
                if "safety_relevant" not in item["flags"]:
                    item["flags"].append("safety_relevant")
                item["selected"] = False
            elif selected:
                item["selected"] = True
            stats["accepted"] += 1
            stats["by_type"]["personal_data" if kind == "personal_data" else "confidential_information"] += 1
    return stats


# ---------------------------------------------------------------------------
# Propose
# ---------------------------------------------------------------------------

def render_previews(doc: pymupdf.Document, limit: int = MAX_PREVIEW_PAGES) -> list[dict[str, Any]]:
    out = []
    for page in doc:
        if page.number >= limit:
            break
        view = page.rect * page.rotation_matrix if page.rotation else page.rect
        zoom = min(1.5, PREVIEW_WIDTH_PX / max(abs(view.width), 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        data = base64.b64encode(pix.tobytes("jpeg", jpg_quality=62)).decode("ascii")
        out.append({"page": page.number + 1, "width": round(abs(view.width), 2), "height": round(abs(view.height), 2),
                    "image": f"data:image/jpeg;base64,{data}"})
    return out


def propose(content: bytes, rules: dict[str, Any], sector: str, *, filename: str = "document.pdf", applicant: str = "",
            applicant_address: str = "", requests_raw: str = "", complete: Optional[Callable[[str, str], str]] = None,
            previews: bool = True) -> dict[str, Any]:
    """Proposed redactions for one PDF. `complete(system, user) -> JSON str` enables the AI pass."""
    rules_for_sector(rules, sector)  # validates the sector
    doc = open_pdf(content)
    try:
        col = _Collector(rules, sector)
        request_items = parse_request_items(requests_raw)
        unlocated = apply_requests(doc, request_items, col)
        col, notes = detect_local(doc, rules, sector, applicant, applicant_address, col)
        ai = {"requested": complete is not None, "used": False}
        if complete is not None:
            ai.update(ai_propose(doc, rules, sector, complete, col, applicant, applicant_address, request_items))
            ai["used"] = ai["batches"] > 0 and len(ai["errors"]) < ai["batches"] + (1 if doc.page_count > MAX_AI_PAGES else 0)
            located_now = {_compact(i["text"]) for i in col.items if "request" in i["sources"] or i["rule_id"] == REQUEST_RULE}
            located_now |= {_compact(request_items[int(c[1:]) - 1]["text"]) for c in ai.get("claims_located", [])}
            unlocated = [u for u in unlocated if _compact(u["text"]) not in located_now]
        ai["mode"] = "ai-led" if ai["used"] else "rules-only"
        ai["recommendation"] = AI_RECOMMENDATION
        warnings = []
        if ai["used"]:
            # The AI's minimal span supersedes a rule-based whole-sentence candidate around it (Art. 10(a) PA: precise scope).
            ai_spans = [(i["page"], _compact(i["text"])) for i in col.items if "ai" in i["sources"]]
            col.items = [i for i in col.items if not (i["category"] == "cue" and i["sources"] == ["rule"] and any(
                pg == i["page"] and t and t in _compact(i["text"]) for pg, t in ai_spans))]
            for it in col.items:
                if "ai" not in it["sources"] and it["sources"] != ["manual"] and it["category"] != "signature":
                    it["flags"].append("not_confirmed_by_ai")  # the AI reads text only, not signature images
        else:
            warnings.append("Rule-based fallback only — the AI review did not run. " + AI_RECOMMENDATION)
        if notes["no_text_pages"]:
            warnings.append(f"No text layer on page(s) {', '.join(map(str, notes['no_text_pages'][:30]))}: nothing there can be detected. "
                            "Run OCR first, or inspect those pages and mask manually.")
        if any(p.rotation for p in doc):
            warnings.append("Some pages are rotated; check the preview boxes on those pages carefully.")
        if unlocated:
            warnings.append(f"{len(unlocated)} confidentiality request/decision item(s) not found verbatim in the document.")
        items = sorted(col.items, key=lambda i: (i["page"], i["rects"][0][1] if i["rects"] else 0, i["rects"][0][0] if i["rects"] else 0))
        summary: dict[str, int] = {}
        for it in items:
            summary[it["group"]] = summary.get(it["group"], 0) + 1
        return {
            "document": {"name": filename, "pages": doc.page_count, "text_pages": doc.page_count - len(notes["no_text_pages"]),
                         "metadata_fields": sorted(k for k, v in (doc.metadata or {}).items() if v and k not in ("format", "encryption")),
                         "annotations": sum(1 for p in doc for _ in p.annots()), "embedded_files": doc.embfile_count()},
            "sector": {"id": sector, **rules["catalogue"]["sectors"][sector]},
            "proposals": items, "summary": summary, "selected": sum(1 for i in items if i["selected"]),
            "unlocated_requests": unlocated, "notes": notes, "warnings": warnings, "ai": ai,
            "previews": render_previews(doc) if previews else [],
            "preview_limit": MAX_PREVIEW_PAGES,
        }
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _clean_redactions(redactions: Any, page_count: int) -> list[dict[str, Any]]:
    if not isinstance(redactions, list):
        raise SanitisationError("redactions must be a list")
    out = []
    for r in redactions[:MAX_PROPOSALS]:
        if not isinstance(r, dict):
            continue
        try:
            page = int(r.get("page"))
            rects = [pymupdf.Rect(*[float(v) for v in rect]) for rect in (r.get("rects") or [])[:50] if len(rect) == 4]
        except (TypeError, ValueError):
            raise SanitisationError("Malformed redaction") from None
        if not 1 <= page <= page_count:
            raise SanitisationError(f"Redaction on page {page} outside the document")
        rects = [x for x in rects if not x.is_empty and not x.is_infinite]
        if rects:
            out.append({"page": page, "rects": rects, "text": str(r.get("text") or "")[:600],
                        "label": str(r.get("label") or "")[:60], "category": str(r.get("category") or "")[:20],
                        "id": str(r.get("id") or "")[:20]})
    return out


def apply(content: bytes, redactions: Any, *, label_boxes: bool = False, title: str = "") -> tuple[bytes, dict[str, Any]]:
    """Burn the selected redactions into the PDF and verify the result. Returns (pdf bytes, report)."""
    doc = open_pdf(content)
    try:
        reds = _clean_redactions(redactions, doc.page_count)
        if not reds:
            raise SanitisationError("No redactions selected.")
        by_page: dict[int, list[dict[str, Any]]] = {}
        for r in reds:
            by_page.setdefault(r["page"], []).append(r)
        masked_texts = [_norm(r["text"]) for r in reds if r["text"] and r["category"] != "signature"]
        report = {"redaction_boxes": 0, "pages_redacted": len(by_page), "annotations_removed": 0, "form_fields_removed": 0,
                  "links_removed": 0, "embedded_files_removed": doc.embfile_count(),
                  "metadata_cleared": sorted(k for k, v in (doc.metadata or {}).items() if v and k not in ("format", "encryption"))}
        for page in doc:
            # Comments, highlights and form fields can carry names and claimed text: remove them all.
            for annot in list(page.annots() or []):
                page.delete_annot(annot)
                report["annotations_removed"] += 1
            for widget in list(page.widgets() or []):
                page.delete_widget(widget)
                report["form_fields_removed"] += 1
            page_reds = by_page.get(page.number + 1, [])
            boxes = [rect for r in page_reds for rect in r["rects"]]
            for link in page.get_links():
                uri = (link.get("uri") or "").lower()
                hit_box = any(pymupdf.Rect(link["from"]).intersects(b) for b in boxes)
                hit_text = any(t and _compact(t) in _compact(uri) for t in masked_texts)
                if hit_box or hit_text or uri.startswith("mailto:"):
                    page.delete_link(link)
                    report["links_removed"] += 1
            if not page_reds:
                continue
            for r in page_reds:
                for rect in r["rects"]:
                    page.add_redact_annot(rect + (-0.5, -0.5, 0.5, 0.5), text=(r["label"] if label_boxes and r["label"] else None),
                                          fontsize=5, fill=(0, 0, 0), text_color=(1, 1, 1), cross_out=False)
                    report["redaction_boxes"] += 1
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                                  text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=False, javascript=True, metadata=True,
                  redactions=True, remove_links=False, reset_fields=True, reset_responses=True, thumbnails=True, xml_metadata=True)
        doc.set_metadata({"title": (title or "Non-confidential version")[:200], "producer": "KEvidence sanitisation"})
        out = doc.tobytes(garbage=4, deflate=True, clean=True, no_new_id=False)
    finally:
        doc.close()
    report["verification"] = verify(out, reds)
    return out, report


def verify(pdf: bytes, reds: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-open the sanitised file and check that no masked text survives anywhere and nothing identifying is left."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        pages = [_compact(p.get_text("text")) for p in doc]
        residual = []
        seen = set()
        for r in reds:
            c = _compact(r["text"])
            if not c or r["category"] == "signature" or c in seen or len(c) < 3:
                continue
            seen.add(c)
            left = [i + 1 for i, p in enumerate(pages) if c in p]
            if left:
                residual.append({"id": r["id"], "page": r["page"], "still_on_pages": left, "same_page": r["page"] in left})
        meta_left = sorted(k for k, v in (doc.metadata or {}).items() if v and k not in ("format", "encryption", "title", "producer", "creationDate", "modDate"))
        checks = {
            # Text masked on a page must be gone from that page; copies elsewhere that were not selected are reported.
            "masked_text_removed": not any(x["same_page"] for x in residual),
            "no_annotations": sum(1 for p in doc for _ in p.annots()) == 0,
            "no_embedded_files": doc.embfile_count() == 0,
            "no_xmp_metadata": not (doc.get_xml_metadata() or "").strip(),
            "metadata_cleared": not meta_left,
            "not_encrypted": not doc.is_encrypted,
        }
        return {"passed": all(checks.values()), "checks": checks, "residual": residual, "pages": doc.page_count}
    finally:
        doc.close()


def log_markdown(filename: str, sector: dict[str, Any], applied: list[dict[str, Any]], report: dict[str, Any], rules: dict[str, Any]) -> str:
    """Internal sanitisation record (contains the masked text: CONFIDENTIAL, not for publication)."""
    g = rules["catalogue"]["guidance"]
    v = report.get("verification", {})
    lines = [f"# Sanitisation record — {filename}", "",
             "> CONFIDENTIAL — internal record. It lists the masked text; do not publish it.", "",
             f"- Sector: Annex ({sector.get('id')}) {sector.get('label')} — {sector.get('legislation')}",
             f"- Rules: {g['citation']}",
             f"- Redaction boxes: {report.get('redaction_boxes')} on {report.get('pages_redacted')} page(s); annotations removed: "
             f"{report.get('annotations_removed')}; form fields removed: {report.get('form_fields_removed')}; links removed: {report.get('links_removed')}; "
             f"embedded files removed: {report.get('embedded_files_removed')}; metadata cleared: {', '.join(report.get('metadata_cleared') or []) or 'none'}",
             f"- Verification: {'PASSED' if v.get('passed') else 'FAILED — see residual items'}"
             + "".join(f"; {k.replace('_', ' ')}: {'yes' if ok else 'NO'}" for k, ok in (v.get("checks") or {}).items()), "",
             "| # | Page | Legal basis | Category | Source | Masked text | Reason |", "|---|---|---|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    for i, r in enumerate(applied, 1):
        lines.append(f"| {i} | {r.get('page')} | {esc(r.get('label', ''))} | {esc(r.get('category', ''))} | {esc(', '.join(r.get('sources') or []))} | "
                     f"{esc(r.get('text', ''))[:200]} | {esc(r.get('reason', ''))[:300]} |")
    if v.get("residual"):
        lines += ["", "## Masked text that still appears elsewhere (not selected for masking there)", ""]
        lines += [f"- {x['id']} (masked on p.{x['page']}) still appears on page(s) {', '.join(map(str, x['still_on_pages']))}"
                  + (" — INCLUDING THE SAME PAGE" if x.get("same_page") else "") for x in v["residual"]]
    lines += ["", "KEvidence proposes masking; the confidentiality decision is EFSA's (Art. 11 of the practical arrangements). "
                  "Check the output before publication."]
    return "\n".join(lines) + "\n"
