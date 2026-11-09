"""Intake: completeness check and personal-data screening of an application dossier.

Mirrors what EFSA's front desk (FDP unit) does between receiving an application and declaring it valid:
check that the dossier is complete and correctly structured, verify the study-notification obligations
of the Transparency Regulation (Article 32b GFL), check the confidentiality request is consistent, and
find personal data that must be sanitised before the non-confidential version is published.

Like IUCLID's Validation Assistant, every check has a severity:
- blocking: a missing element that prevents the application from being considered valid; it goes into the
  request for missing information;
- warning: a quality issue the officer should look at (it may also lead to a request);
- info: procedural context.

Each check cites the rule it implements, quoted verbatim from a bundled EFSA document
(data/guidance/intake/ and the transparency rules). KEvidence locates and flags; the officer decides.
Documents are processed in memory for one request and are not stored.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Optional

import pymupdf

import characterisation as charmod
import sanitisation as sanmod

INTAKE_DIR = charmod.GUIDANCE_ROOT / "intake"
CATALOGUES = ("efsa_feed_completeness_checklist_rules.json", "efsa_2021_pa_presubmission_rules.json")
STEP = "completeness"

MAX_FILES = 300
MAX_FILE_BYTES = 60 * 1024 * 1024          # read files up to 60 MB so files over the 30 MB rule can be flagged
MAX_TOTAL_BYTES = 400 * 1024 * 1024
MAX_SCAN_PAGES = 250                       # personal-data scan per file
GUIDANCE_FILE_LIMIT = 30 * 1024 * 1024
NOTIFICATION_START = date(2021, 3, 27)
TEXT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".tsv", ".txt", ".md", ".json", ".html", ".htm"}
APPLICATION_TYPES = {"new": "New additive / new use (Art. 4 Reg. 1831/2003)",
                     "modification": "Modification of an authorisation (Art. 13)",
                     "renewal": "Renewal of an authorisation (Art. 14)"}


class CompletenessError(ValueError):
    """The upload cannot be checked (too large, unreadable archive...)."""


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def load_rules(transparency: Optional[dict] = None) -> dict[str, Any]:
    """Both intake catalogues (plus the transparency rules, for the assistant), shaped like a domain bundle."""
    sources = []
    for name in CATALOGUES:
        cat = charmod.load_knowledge_catalogue(INTAKE_DIR / name)
        for e in cat["entries"]:
            for key in ("category", "check", "severity", "domains"):
                if not e.get(key):
                    raise ValueError(f"{e['id']} is missing '{key}'")
            if e["severity"] not in ("blocking", "warning", "info"):
                raise ValueError(f"{e['id']}: unknown severity {e['severity']}")
        sources.append({"role": "primary" if not sources else "supporting", "catalogue": cat,
                        "pages": charmod.load_pdf_pages(INTAKE_DIR / cat["guidance"]["bundled_file"])})
    transparency = transparency or sanmod.load_rules()
    by_id = {e["id"]: (e, src) for src in sources for e in src["catalogue"]["entries"]}
    for e in transparency["catalogue"]["entries"]:
        by_id.setdefault(e["id"], (e, transparency["sources"][0]))
    return {"id": "intake", "label": "Intake — completeness check", "directory": INTAKE_DIR, "assistant_role": "EFSA front-desk staff",
            "datasets": {}, "sources": sources + [{**transparency["sources"][0], "role": "supporting"}],
            "primary": sources[0], "by_id": by_id, "transparency": transparency}


def rules_status(rules: dict[str, Any]) -> list[dict[str, Any]]:
    return [charmod.source_status(s) for s in rules["sources"]]


def _cite(rules: dict, rule_id: str) -> dict[str, Any]:
    entry, src = rules["by_id"][rule_id]
    return {"rule_id": rule_id, "title": entry["title"], "source": charmod.source_short_name(src["catalogue"]),
            "section": entry["guidance_section"], "page": entry["guidance_page"], "quote": entry["quote"],
            "requirement": entry["requirement"]}


# ---------------------------------------------------------------------------
# Reading the dossier
# ---------------------------------------------------------------------------

@dataclass
class DossierFile:
    path: str
    data: bytes
    ext: str
    size: int
    part: str = "unknown"            # administrative | technical | confidential | unknown
    role: str = "other"              # cover_letter, application_form, cclist, contact, pubsum, scsum, listdoc, confinfo,
                                     # sect_II..sect_V, annex, other
    section: str = ""                # II, III, IV, V for sections and their annexes
    is_pdf: bool = False
    pages: list[str] = field(default_factory=list)
    unsearchable_pages: list[int] = field(default_factory=list)
    restricted: str = ""
    error: str = ""

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


def _safe_path(name: str) -> str:
    parts = [p for p in re.split(r"[\\/]+", name or "") if p not in ("", ".", "..")]
    return "/".join(parts) or "unnamed"


def read_upload(uploads: list[tuple[str, bytes]]) -> tuple[list[DossierFile], list[str]]:
    """Files as uploaded; a .zip is expanded in memory (never written to disk), with size and count limits."""
    files: list[DossierFile] = []
    notes: list[str] = []
    total = 0

    def add(path: str, data: bytes) -> None:
        nonlocal total
        name = PurePosixPath(path).name
        if name.startswith(".") or "__MACOSX" in path:
            return
        if len(files) >= MAX_FILES:
            raise CompletenessError(f"At most {MAX_FILES} files per dossier.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise CompletenessError(f"The dossier exceeds {MAX_TOTAL_BYTES // (1024 * 1024)} MB.")
        files.append(DossierFile(path=_safe_path(path), data=data, ext=PurePosixPath(name).suffix.lower(), size=len(data)))

    for name, data in uploads:
        if name.lower().endswith(".zip") or data[:4] == b"PK\x03\x04" and not name.lower().endswith((".docx", ".xlsx", ".xlsm")):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise CompletenessError(f"{name}: not a readable ZIP archive.") from None
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES or len(infos) > MAX_FILES:
                raise CompletenessError(f"{name}: the archive is too large once expanded.")
            for info in infos:
                if info.file_size > MAX_FILE_BYTES:
                    notes.append(f"{info.filename}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB, not read.")
                    files.append(DossierFile(path=_safe_path(info.filename), data=b"", ext=PurePosixPath(info.filename).suffix.lower(),
                                             size=info.file_size, error="too large to read"))
                    continue
                if info.filename.lower().endswith(".zip"):
                    notes.append(f"{info.filename}: nested archives are not expanded.")
                add(info.filename, zf.read(info))
        else:
            add(name, data)
    if not files:
        raise CompletenessError("No files in the upload.")
    for f in files:
        _read_text(f)
        classify(f)
    return files, notes


def _read_text(f: DossierFile) -> None:
    if f.error or not f.data:
        return
    if f.ext == ".pdf" or f.data[:5] == b"%PDF-":
        f.is_pdf = True
        try:
            doc = pymupdf.open(stream=f.data, filetype="pdf")
        except Exception as exc:
            f.error = f"unreadable PDF ({type(exc).__name__})"
            return
        try:
            if doc.needs_pass:
                f.restricted = "password required to open"
                f.error = "password-protected"
                return
            if doc.is_encrypted or (doc.permissions is not None and doc.permissions != -1):
                perms = doc.permissions or 0
                blocked = [label for flag, label in ((pymupdf.PDF_PERM_PRINT, "printing"), (pymupdf.PDF_PERM_COPY, "copying"))
                           if not perms & flag]
                if blocked:
                    f.restricted = "security settings prevent " + " and ".join(blocked)
            for page in doc:
                text = page.get_text("text")
                f.pages.append(text)
                if len(text.strip()) < 20:
                    f.unsearchable_pages.append(page.number + 1)
        finally:
            doc.close()
    elif f.ext in TEXT_EXTENSIONS:
        d = charmod.extract_document(f.name, f.data)
        f.pages = d.pages
        if d.warnings and not d.pages:
            f.error = "; ".join(d.warnings)[:200]


# Role detection: the recommended file names of the guidance first, then the folder, then the content.
ROLE_NAME_RULES = [
    ("confinfo", r"conf_?info|list.{0,5}(of)?.{0,5}confidential|confidential.{0,5}(parts|list)"),
    ("cover_letter", r"efsa_?letter|cover.?letter"),
    ("application_form", r"^annex_?i(?![iv_\d])|application.?form"),
    ("cclist", r"cc_?list|completeness.?check"),
    ("contact", r"^contact|contact.?details"),
    ("pubsum", r"pub_?sum|public.?summary"),
    ("scsum", r"sc_?sum|scientific.?summary"),
    ("listdoc", r"list_?doc|list.?of.?documents"),
    ("sect_V", r"sect(ion)?_?v(?![a-z])|post.?mark"),
    ("sect_IV", r"sect(ion)?_?iv(?![a-z])|efficacy"),
    ("sect_III", r"sect(ion)?_?iii(?![a-z])|safety"),
    ("sect_II", r"sect(ion)?_?ii(?![ia-z])|identity"),
]
ANNEX_RE = re.compile(r"annex(es)?_?(ii|iii|iv|v)[_.\s-]?\d", re.I)
CONTENT_ROLE_RULES = [
    ("pubsum", re.compile(r"^\s*(1\.1\.?\s*)?public\s+summary\b", re.I | re.M)),
    ("scsum", re.compile(r"^\s*(1\.2\.?\s*)?scientific\s+summary\b", re.I | re.M)),
    ("listdoc", re.compile(r"^\s*(1\.3\.?\s*)?list\s+of\s+documents\b", re.I | re.M)),
    ("confinfo", re.compile(r"^\s*(1\.4\.?\s*)?list\s+of\s+(the\s+)?(parts|volumes)[^\n]{0,40}confidential", re.I | re.M)),
    ("cclist", re.compile(r"completeness\s+check\s*list", re.I)),
    ("application_form", re.compile(r"application\s+for\s+(the\s+)?authori[sz]ation[^\n]{0,80}(1831/2003|feed\s+additive)", re.I)),
    ("cover_letter", re.compile(r"^\s*(dear\s+(sir|madam|colleague)|subject\s*:)", re.I | re.M)),
    ("sect_II", re.compile(r"^\s*section\s+ii\b(?!i)", re.I | re.M)),
    ("sect_III", re.compile(r"^\s*section\s+iii\b", re.I | re.M)),
    ("sect_IV", re.compile(r"^\s*section\s+iv\b", re.I | re.M)),
    ("sect_V", re.compile(r"^\s*section\s+v\b", re.I | re.M)),
]
STUDY_CUES = re.compile(r"study\s+report|final\s+report|study\s+director|test\s+facility|study\s+plan|good\s+laboratory\s+practice|\bGLP\b", re.I)


def classify(f: DossierFile) -> None:
    lower_path = f.path.lower()
    stem = PurePosixPath(f.name).stem.lower()
    folders = lower_path.split("/")[:-1]
    if stem.endswith("_conf") or stem.endswith("-conf") or any("confidential" in d for d in folders):
        f.part = "confidential"
    elif any("admin" in d for d in folders):
        f.part = "administrative"
    elif any("technical" in d for d in folders):
        f.part = "technical"
    base = re.sub(r"[_-]conf$", "", stem)
    m = ANNEX_RE.search(base)
    if m:
        f.role, f.section = "annex", m.group(2).upper()
    else:
        for role, pattern in ROLE_NAME_RULES:
            if re.search(pattern, base, re.I):
                f.role = role
                break
    if f.role == "other" and f.pages:
        head = "\n".join(f.pages[:2])[:4000]
        for role, regex in CONTENT_ROLE_RULES:
            if regex.search(head):
                f.role = role
                break
        if f.role == "other" and STUDY_CUES.search(head):
            f.role = "annex"
    if f.role.startswith("sect_"):
        f.section = f.role.split("_")[1]
    if f.part == "unknown":
        f.part = ("administrative" if f.role in ("cover_letter", "application_form", "cclist", "contact")
                  else "technical" if f.role != "other" else "unknown")


ROLE_LABELS = {"cover_letter": "Cover letter", "application_form": "Application form (Annex I)", "cclist": "Completeness checklist",
               "contact": "Contact details", "pubsum": "Public summary (1.1)", "scsum": "Scientific summary (1.2)",
               "listdoc": "List of documents (1.3)", "confinfo": "List of confidential parts (1.4)",
               "sect_II": "Section II — identity, characterisation", "sect_III": "Section III — safety",
               "sect_IV": "Section IV — efficacy", "sect_V": "Section V — post-market monitoring", "annex": "Annex / study report",
               "other": "Not recognised"}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

SUBSECTIONS = {
    "II": [("2.1", "Identity of the additive", r"identity"), ("2.2", "Characterisation of the active substance/agent", r"characteri[sz]ation"),
           ("2.3", "Manufacturing process", r"manufactur|production\s+process"),
           ("2.4", "Physico-chemical and technological properties", r"physico|technological\s+properties|stability|homogeneity"),
           ("2.5", "Conditions of use", r"conditions\s+of\s+use"), ("2.6", "Methods of analysis and reference samples", r"methods?\s+of\s+analysis")],
    "III": [("3.1", "Safety for the target animals", r"target\s+(animals|species)"), ("3.2", "Safety for consumers", r"consumer"),
            ("3.3", "Safety for users/workers", r"user|worker"), ("3.4", "Safety for the environment", r"environment")],
    "IV": [("4.1", "Efficacy for the target animals", r"efficacy")],
    "V": [("5", "Proposal for post-market monitoring", r"post.?market\s+monitoring")],
}
SECTION_RULE = {"II": "CC-SECTION-II", "III": "CC-SECTION-III", "IV": "CC-SECTION-IV", "V": "CC-SECTION-V"}
FORBIDDEN_NAME_CHARS = set('\\:*?"<>|#')
NEXT_HEADING_RE = re.compile(r"^\s*(?:\d+\.)+\d*\.?\s+[A-Z]|^\s*SECTION\s+[IVX]+\b", re.M)
OMISSION_RE = re.compile(r"justif|not\s+(applicable|relevant|required)|omitted|omission|waiv", re.I)
ENGLISH_WORDS = {"the", "and", "of", "to", "in", "is", "for", "with", "was", "were", "on", "by", "be", "are", "as", "at", "from", "this", "that"}
PAGE_REF_RE = re.compile(r"\b(p\.|pp\.|page|pages|vol\.|volume)\s*[IVX]*-?\d+", re.I)
STUDY_ID_RE = re.compile(r"\b(?:EFSA[\s-]*)?(?:study|notification)\s*(?:ID|identifier|number|no\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9_./-]{4,})", re.I)
PREAPP_RE = re.compile(r"pre-?\s*application\s*(?:ID|identifier|number)", re.I)
NOTIF_JUSTIFICATION_RE = re.compile(r"(justif\w*|reason)[^.\n]{0,120}(notif|non-?inclusion|not\s+(been\s+)?notified)|not\s+(been\s+)?notified\s+because", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})\b"), lambda m: (int(m[3]), MONTHS.get(m[2].lower()), int(m[1]))),
    (re.compile(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"), lambda m: (int(m[3]), MONTHS.get(m[1].lower()), int(m[2]))),
]
START_LABEL_RE = re.compile(r"(?:study|experimental|in-?life|animal\s+phase|trial)?\s*(?:start(?:ing)?|initiation|commencement)\s+date"
                            r"|date\s+of\s+(?:the\s+)?(?:study\s+)?(?:start|initiation|commencement)|study\s+initiat\w*", re.I)


def parse_date(text: str) -> Optional[date]:
    for regex, conv in DATE_RES:
        m = regex.search(text)
        if m:
            try:
                y, mo, d = conv(m)
                if mo:
                    return date(y, mo, d)
            except (ValueError, TypeError):
                continue
    return None


def study_start_date(text: str) -> Optional[tuple[date, str]]:
    for m in START_LABEL_RE.finditer(text):
        window = text[m.end(): m.end() + 60]
        d = parse_date(window)
        if d:
            return d, re.sub(r"\s+", " ", text[m.start(): m.end() + 40]).strip()
    return None


def _page_of(f: DossierFile, needle_regex: re.Pattern) -> Optional[int]:
    for i, p in enumerate(f.pages, 1):
        if needle_regex.search(p):
            return i
    return None


def _shingles(text: str, n: int = 10) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9%.,]+", text.lower())
    return {tuple(words[i:i + n]) for i in range(0, max(0, len(words) - n + 1))}


class _Results:
    def __init__(self, rules: dict, domain: str, app_type: str):
        self.rules, self.domain, self.app_type = rules, domain, app_type
        self.items: list[dict[str, Any]] = []

    def applies(self, rule_id: str) -> tuple[bool, str]:
        entry, _ = self.rules["by_id"][rule_id]
        domains = entry.get("domains", ["*"])
        if "*" not in domains and self.domain not in domains:
            return False, f"The completeness checklist for this domain is not loaded (available for: {', '.join(domains)})."
        types = entry.get("application_types")
        if types and self.app_type not in types:
            return False, f"Applies to {', '.join(types)} applications only."
        return True, ""

    def add(self, rule_id: str, status: str, detail: str, evidence: Optional[list[dict]] = None, title: str = "",
            severity: Optional[str] = None) -> None:
        entry, _ = self.rules["by_id"][rule_id]
        self.items.append({"rule_id": rule_id, "category": entry.get("category", "Confidentiality and personal data"),
                           "title": title or entry["title"], "severity": severity or entry.get("severity", "warning"),
                           "status": status, "detail": detail, "evidence": evidence or [], "citation": _cite(self.rules, rule_id)})


def run_checks(files: list[DossierFile], rules: dict, *, domain: str = "feed", application_type: str = "new",
               applicant: str = "", pre_application_ids: list[str] = (), notified_study_ids: list[str] = (),
               sector: str = "c", scan_personal_data: bool = True) -> dict[str, Any]:
    R = _Results(rules, domain, application_type)
    readable = [f for f in files if not f.error]
    by_role: dict[str, list[DossierFile]] = {}
    for f in readable:
        by_role.setdefault(f.role, []).append(f)
    conf_files = [f for f in readable if f.part == "confidential" and f.role != "confinfo"]
    nonconf = [f for f in readable if f.part != "confidential"]

    def ev(f: DossierFile, page: Optional[int] = None) -> dict:
        return {"file": f.path, "page": page}

    # --- Structure and format -------------------------------------------------------------
    ok, why = R.applies("CC-STRUCT-THREE-PARTS")
    if not ok:
        R.add("CC-STRUCT-THREE-PARTS", "not_applicable", why)
    else:
        parts = {f.part for f in files}
        needed = ["administrative", "technical"] + (["confidential"] if conf_files or by_role.get("confinfo") else [])
        missing = [p for p in needed if p not in parts]
        if "unknown" in parts and len(parts) == 1:
            R.add("CC-STRUCT-THREE-PARTS", "review", "No part could be recognised from folder or file names: check the structure manually.")
        elif missing:
            R.add("CC-STRUCT-THREE-PARTS", "fail", f"Part(s) not recognised: {', '.join(missing)}.")
        else:
            R.add("CC-STRUCT-THREE-PARTS", "ok", "Parts recognised: " + ", ".join(sorted(parts - {"unknown"})) + ".")
    ok, why = R.applies("CC-STRUCT-ONE-FILE-PER-SECTION")
    if ok:
        multi = []
        for f in readable:
            if f.role in ("listdoc", "scsum", "cclist", "pubsum", "application_form", "cover_letter", "confinfo"):
                continue
            heads = {m.group(1).upper() for m in re.finditer(r"^\s*section\s+(ii|iii|iv|v)\b", f.text, re.I | re.M)}
            if len(heads) > 1:
                multi.append(ev(f) | {"note": "sections " + ", ".join(sorted(heads))})
        R.add("CC-STRUCT-ONE-FILE-PER-SECTION", "fail" if multi else "ok",
              f"{len(multi)} file(s) combine several sections." if multi else "No file combines several sections.", multi)
    else:
        R.add("CC-STRUCT-ONE-FILE-PER-SECTION", "not_applicable", why)
    scans = [ev(f) | {"note": f"{len(f.unsearchable_pages)} of {len(f.pages)} page(s) without text: "
                               + ", ".join(map(str, f.unsearchable_pages[:12])) + ("…" if len(f.unsearchable_pages) > 12 else "")}
             for f in readable if f.is_pdf and f.unsearchable_pages]
    R.add("CC-FORMAT-SEARCHABLE", "fail" if scans else "ok",
          f"{len(scans)} PDF(s) with pages that cannot be searched (scanned or image-only)." if scans else "All PDF pages carry text.", scans)
    big = [ev(f) | {"note": f"{f.size / 1048576:.1f} MB"} for f in files if f.size > GUIDANCE_FILE_LIMIT]
    R.add("CC-FORMAT-SIZE", "fail" if big else "ok", f"{len(big)} file(s) over 30 MB." if big else "All files are 30 MB or less.", big)
    locked = [ev(f) | {"note": f.restricted} for f in files if f.restricted]
    R.add("CC-FORMAT-SECURITY", "fail" if locked else "ok",
          f"{len(locked)} file(s) with security settings." if locked else "No security settings found.", locked)
    bad_names = [ev(f) | {"note": "contains " + " ".join(sorted({c for c in f.path if c in FORBIDDEN_NAME_CHARS}))}
                 for f in files if any(c in FORBIDDEN_NAME_CHARS for c in f.path)]
    R.add("CC-FORMAT-FILENAMES", "fail" if bad_names else "ok",
          f"{len(bad_names)} file name(s) with special characters." if bad_names else "File names are clean.", bad_names)
    non_en = []
    for f in readable:
        words = re.findall(r"[a-zA-Z]+", f.text[:20000].lower())
        if len(words) >= 150 and sum(w in ENGLISH_WORDS for w in words) / len(words) < 0.04:
            non_en.append(ev(f))
    R.add("CC-FORMAT-ENGLISH", "fail" if non_en else "ok",
          f"{len(non_en)} document(s) may not be in English." if non_en else "Documents read as English.", non_en)

    # --- Administrative documents and Section I -------------------------------------------------
    ok, why = R.applies("CC-ADMIN-DOCUMENTS")
    if ok:
        for role in ("cover_letter", "application_form", "cclist", "contact"):
            found = by_role.get(role, [])
            R.add("CC-ADMIN-DOCUMENTS", "ok" if found else "fail", "Located." if found else "Not located.",
                  [ev(f) for f in found], title=ROLE_LABELS[role])
    else:
        R.add("CC-ADMIN-DOCUMENTS", "not_applicable", why)
    ok, why = R.applies("CC-SECTION-I")
    if ok:
        for role in ("pubsum", "scsum", "listdoc"):
            found = by_role.get(role, [])
            R.add("CC-SECTION-I", "ok" if found else "fail", "Located." if found else "Not located.", [ev(f) for f in found],
                  title=ROLE_LABELS[role])
    else:
        R.add("CC-SECTION-I", "not_applicable", why)

    # Public summary must not carry confidential text: shared 10-word passages with the confidential copies.
    ok, why = R.applies("CC-PUBSUM-NO-CONFIDENTIAL")
    if not ok:
        R.add("CC-PUBSUM-NO-CONFIDENTIAL", "not_applicable", why)
    elif not by_role.get("pubsum") or not conf_files:
        R.add("CC-PUBSUM-NO-CONFIDENTIAL", "not_applicable", "No public summary or no confidential copies to compare.")
    else:
        # The technical dossier legitimately carries the confidential text (marked); the public summary must not.
        conf_sh = set().union(*(_shingles(f.text) for f in conf_files))
        leaks = []
        for f in by_role["pubsum"]:
            for page_no, page in enumerate(f.pages, 1):
                shared = _shingles(page) & conf_sh
                if shared:
                    leaks.append(ev(f, page_no) | {"note": "“" + " ".join(sorted(shared)[0]) + " …”"})
        R.add("CC-PUBSUM-NO-CONFIDENTIAL", "fail" if leaks else "ok",
              "The public summary repeats text of the confidential copies." if leaks
              else "No passage of the confidential copies found in the public summary.", leaks)

    ok, why = R.applies("CC-CONFIDENTIAL-PARTS")
    confinfo = by_role.get("confinfo", [])
    if not ok:
        # Outside the feed checklist the transparency rule still applies: a request must locate the parts precisely.
        if confinfo and not any(PAGE_REF_RE.search(f.text) for f in confinfo):
            R.add("PA-ART10-A-PRECISE-SCOPE", "fail", "The confidentiality list gives no page references.", [ev(f) for f in confinfo],
                  severity="warning")
        R.add("CC-CONFIDENTIAL-PARTS", "not_applicable", why)
    elif not conf_files and not confinfo:
        R.add("CC-CONFIDENTIAL-PARTS", "not_applicable", "No confidentiality requested (no list of confidential parts, no '_Conf' copies).")
    else:
        if not confinfo:
            R.add("CC-CONFIDENTIAL-PARTS", "fail", f"{len(conf_files)} confidential cop(ies) but no list of confidential parts (Section I, 1.4).",
                  [ev(f) for f in conf_files[:10]])
        elif not conf_files:
            R.add("CC-CONFIDENTIAL-PARTS", "fail", "A list of confidential parts is given but no confidential copies ('_Conf') were found.",
                  [ev(f) for f in confinfo], severity="warning")
        else:
            R.add("CC-CONFIDENTIAL-PARTS", "ok", f"List of confidential parts and {len(conf_files)} confidential cop(ies) located.",
                  [ev(f) for f in confinfo])
        if confinfo:
            refs = any(PAGE_REF_RE.search(f.text) for f in confinfo)
            R.add("PA-ART10-A-PRECISE-SCOPE", "ok" if refs else "fail",
                  "The list gives page references." if refs else "The list gives no page references: each confidential part must be "
                  "identified by paragraph, page or line.", [ev(f) for f in confinfo], severity="warning")
    R.add("CC-CONFIDENTIAL-MARKED", "info", "Check by eye that confidential passages are marked in the technical dossier.")

    ok, why = R.applies("CC-RENEWAL-PREVIOUS-AUTH")
    if ok:
        hits = [ev(f, _page_of(f, re.compile(r"previous(ly)?\s+authori[sz]", re.I))) for f in readable
                if re.search(r"previous(ly)?\s+authori[sz]", f.text, re.I)]
        R.add("CC-RENEWAL-PREVIOUS-AUTH", "ok" if hits else "fail", "Located." if hits else "No information on the previous authorisation located.",
              hits[:5])
    else:
        R.add("CC-RENEWAL-PREVIOUS-AUTH", "not_applicable", why)

    # --- Technical sections II-V and their headings -----------------------------------------------
    technical = [f for f in readable if f.part in ("technical", "unknown")]
    for sec, subs in SUBSECTIONS.items():
        rule_id = SECTION_RULE[sec]
        ok, why = R.applies(rule_id)
        if not ok:
            R.add(rule_id, "not_applicable", why)
            continue
        docs = by_role.get(f"sect_{sec}", [])
        if not docs:
            heading = re.compile(rf"^\s*section\s+{sec}\b" + ("(?!i)" if sec == "II" else ""), re.I | re.M)
            docs = [f for f in technical if f.role not in ("listdoc", "scsum", "cclist", "pubsum") and heading.search(f.text)]
        soft = sec == "IV" and application_type == "renewal"
        if not docs:
            R.add(rule_id, "fail", "Section not located." + (" For a renewal, confirm whether efficacy data are required." if soft else ""),
                  severity="warning" if soft else None)
            continue
        text = "\n".join(f.text for f in docs)
        R.add(rule_id, "ok", "Section located.", [ev(f) for f in docs])
        for num, label, kw in subs:
            head = re.compile(rf"^\s*{re.escape(num)}\.?\s+[^\n]{{0,80}}?(?:{kw})" if num != "5" else rf"(?:{kw})", re.I | re.M)
            m = head.search(text) or re.search(rf"^\s*[^\n]{{0,20}}(?:{kw})[^\n]{{0,60}}$", text, re.I | re.M)
            if not m:
                R.add(rule_id, "fail", "Heading not located: check the section.", title=f"{num} {label}", severity="warning")
                continue
            # Look for a justification only up to the next numbered heading, so one omission does not mark its neighbours.
            body = text[m.end(): m.end() + 600]
            nxt = NEXT_HEADING_RE.search(body)
            justified = bool(OMISSION_RE.search(body[: nxt.start()] if nxt else body))
            src = next((f for f in docs if m.group(0) in f.text), docs[0])
            page = _page_of(src, re.compile(re.escape(m.group(0).strip()[:40]), re.I))
            R.add(rule_id, "justified" if justified else "ok",
                  "Omission justified — review the justification." if justified else "Heading located.",
                  [ev(src, page)], title=f"{num} {label}", severity="info")
    R.add("CC-OMISSION-JUSTIFIED", "info", "Omissions marked “justified” above need the officer's judgement.")

    # --- Study notifications (Art. 32b GFL; pre-submission arrangements Art. 19-23) ----------------
    studies = []
    known_ids = [s.strip() for s in notified_study_ids if s.strip()]
    for f in readable:
        if f.part == "confidential" or f.role not in ("annex", "other"):
            continue
        head = "\n".join(f.pages[:4])
        if len(STUDY_CUES.findall(head)) < (1 if f.role == "annex" else 2):
            continue  # an annex that is not a study report (e.g. certificates of analysis)
        start = study_start_date(head) or study_start_date(f.text[:30000])
        ids_found = [i for i in known_ids if i and i in f.text] or [m.group(1) for m in STUDY_ID_RE.finditer(f.text)]
        justified = bool(NOTIF_JUSTIFICATION_RE.search(f.text))
        if start is None:
            status, detail = "review", "Study start date not located: check whether the study had to be notified."
        elif start[0] < NOTIFICATION_START:
            status, detail = "ok", f"Started {start[0].isoformat()}: before 27 March 2021, no notification required."
        elif ids_found:
            status, detail = "ok", f"Started {start[0].isoformat()}; study ID {ids_found[0]} given."
        elif justified:
            status, detail = "justified", f"Started {start[0].isoformat()}; no study ID but a justification is given — assess it (Art. 22(4))."
        else:
            status, detail = "fail", f"Started {start[0].isoformat()}; no study ID and no justification: validity at risk (Art. 32b(4) GFL)."
        studies.append({"file": f.path, "start": start[0].isoformat() if start else None, "start_text": start[1] if start else "",
                        "study_ids": ids_found[:3], "status": status, "detail": detail})
        R.add("PS-ART19-1-SCOPE", status, detail, [ev(f, _page_of(f, START_LABEL_RE) if start else None)],
              title=f"Study notification — {f.name}", severity="blocking" if status == "fail" else "info")
    if not studies:
        R.add("PS-ART19-1-SCOPE", "not_applicable", "No study report recognised in the non-confidential dossier.")
    required = [s for s in studies if s["start"] and s["start"] >= NOTIFICATION_START.isoformat()]
    if known_ids:
        everything = "\n".join(f.text for f in readable)
        absent = [i for i in known_ids if i not in everything]
        R.add("PS-ART22-3-MATCH", "fail" if absent else "ok",
              ("Notified study ID(s) not found in the dossier: " + ", ".join(absent) + ". Each needs the study or a justification "
               "for its non-inclusion (Art. 32b(5) GFL).") if absent else "Every notified study ID appears in the dossier.")
    else:
        R.add("PS-ART22-3-MATCH", "review", "Enter the study IDs from the notification database to verify that every notified study "
                                            "is included (and no other).")
    preapp_given = [p for p in pre_application_ids if p.strip()]
    admin_text = "\n".join(f.text for f in readable if f.part == "administrative" or f.role in ("cover_letter", "application_form"))
    preapp_found = [p for p in preapp_given if p in admin_text] or ([] if not PREAPP_RE.search(admin_text) else ["(mentioned)"])
    if preapp_found:
        R.add("PS-ART21-IDS", "ok", "Pre-application ID given in the administrative documents.")
    elif required:
        R.add("PS-ART21-IDS", "fail", "Studies from 27 March 2021 are included, but no pre-application ID was found in the cover letter or "
                                      "application form.")
    else:
        R.add("PS-ART21-IDS", "not_applicable", "No study requiring notification recognised.")
    for rid in ("PS-ART19-3-BEFORE-START", "PS-ART23-CONSEQUENCES"):
        R.add(rid, "info", "Procedural reference.")

    # --- Personal data in the non-confidential version (Art. 4(5) of the transparency arrangements) --------
    personal = []
    if scan_personal_data:
        trules = rules["transparency"]
        for f in nonconf:
            if f.role == "contact":
                continue
            count, kinds = 0, set()
            if f.is_pdf:
                try:
                    doc = pymupdf.open(stream=f.data, filetype="pdf")
                    if doc.page_count > MAX_SCAN_PAGES:
                        doc.select(list(range(MAX_SCAN_PAGES)))
                    col, _ = sanmod.detect_local(doc, trules, sector, applicant)
                    doc.close()
                    hits = [p for p in col.items if p["kind"] == "personal_data" and p["selected"]]
                    count, kinds = len(hits), {p["category"] for p in hits}
                except Exception:
                    continue
            else:
                hits = sanmod.EMAIL_RE.findall(f.text) + [m for m in sanmod.TITLE_RE.findall(f.text)]
                count, kinds = len(hits), {"email/name"} if hits else set()
            if count:
                personal.append({"file": f.path, "count": count, "kinds": sorted(kinds), "pdf": f.is_pdf})
        R.add("PA-ART4-5-PERSONAL-DATA", "fail" if personal else "ok",
              f"Personal data found in {len(personal)} non-confidential file(s): sanitise before publication." if personal
              else "No personal data detected in the non-confidential files (local rules only: check names without titles by eye).",
              [{"file": p["file"], "page": None, "note": f"{p['count']} item(s): {', '.join(p['kinds'])}"} for p in personal],
              severity="warning")
    R.add("CC-TIMELINE-30WD", "info", "Target: outcome communicated within 30 working days of receipt; the applicant has 30 days to "
                                      "answer a request for missing information.")

    # --- Verdict ----------------------------------------------------------------------------------------
    blocking = [i for i in R.items if i["status"] == "fail" and i["severity"] == "blocking"]
    warnings = [i for i in R.items if i["status"] == "fail" and i["severity"] == "warning"]
    reviews = [i for i in R.items if i["status"] in ("review", "justified")]
    return {
        "verdict": "incomplete" if blocking else "complete_with_warnings" if warnings or reviews else "complete",
        "counts": {"blocking": len(blocking), "warnings": len(warnings), "review": len(reviews),
                   "ok": sum(1 for i in R.items if i["status"] == "ok")},
        "results": R.items, "studies": studies, "personal_data": personal,
        "files": [{"path": f.path, "name": f.name, "part": f.part, "role": f.role, "label": ROLE_LABELS.get(f.role, f.role),
                   "section": f.section, "size": f.size, "pages": len(f.pages), "unsearchable_pages": len(f.unsearchable_pages),
                   "pdf": f.is_pdf, "error": f.error, "restricted": f.restricted,
                   "personal_data": next((p["count"] for p in personal if p["file"] == f.path), 0)} for f in files],
        "domain": domain, "application_type": application_type,
    }


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def _esc(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def report_markdown(result: dict[str, Any], dossier_ref: str = "") -> str:
    v = {"incomplete": "INCOMPLETE — blocking items must be resolved before validation",
         "complete_with_warnings": "Complete, with warnings and items to review", "complete": "Complete"}[result["verdict"]]
    c = result["counts"]
    lines = [f"# Completeness check{(' — ' + dossier_ref) if dossier_ref else ''}", "",
             f"**Outcome:** {v}  ", f"Blocking: {c['blocking']} · Warnings: {c['warnings']} · To review: {c['review']} · Passed: {c['ok']}  ",
             f"Application type: {APPLICATION_TYPES.get(result['application_type'], result['application_type'])} · Domain: {result['domain']}", "",
             "> Draft prepared by KEvidence for the officer's review. It locates and flags; validity is decided by EFSA/the Commission.", ""]
    cats: dict[str, list] = {}
    for i in result["results"]:
        if i["status"] in ("info", "not_applicable"):
            continue
        cats.setdefault(i["category"], []).append(i)
    mark = {"ok": "✓", "fail": "✕", "review": "?", "justified": "J"}
    for cat, items in cats.items():
        lines += [f"## {cat}", "", "| | Check | Severity | Result | Evidence | Rule |", "|---|---|---|---|---|---|"]
        for i in items:
            evid = "; ".join(f"{e['file']}{(' p.' + str(e['page'])) if e.get('page') else ''}{(' (' + e['note'] + ')') if e.get('note') else ''}"
                             for e in i["evidence"][:6])
            ci = i["citation"]
            lines.append(f"| {mark.get(i['status'], '')} | {_esc(i['title'])} | {i['severity']} | {_esc(i['detail'])} | {_esc(evid)} | "
                         f"{_esc(ci['source'])} {_esc(ci['section'])}, p.{ci['page']} |")
        lines.append("")
    lines += ["## File inventory", "", "| File | Part | Recognised as | Pages | Unsearchable pages | Personal data |", "|---|---|---|---|---|---|"]
    for f in result["files"]:
        lines.append(f"| {_esc(f['path'])} | {f['part']} | {_esc(f['label'])} | {f['pages']} | {f['unsearchable_pages']} | {f['personal_data'] or ''} |")
    return "\n".join(lines) + "\n"


def missing_information_letter(result: dict[str, Any], dossier_ref: str = "", applicant: str = "") -> str:
    """Draft request for missing information (blocking items, then warnings worth raising)."""
    blocking = [i for i in result["results"] if i["status"] == "fail" and i["severity"] == "blocking"]
    warnings = [i for i in result["results"] if i["status"] == "fail" and i["severity"] == "warning"]
    ref = dossier_ref or "[dossier reference]"
    out = [f"**Subject:** {ref} — request for missing information (completeness check)", "",
           f"Dear {applicant or '[applicant]'},", "",
           f"EFSA has checked the completeness of the application {ref}. Before it can be considered valid, the following parts of the "
           "dossier need to be completed or modified:", ""]
    n = 0
    for i in blocking:
        n += 1
        ci = i["citation"]
        files = ", ".join(sorted({e["file"] for e in i["evidence"]})[:5])
        out.append(f"{n}. **{i['title']}** — {i['detail']}{(' (' + files + ')') if files else ''} "
                   f"[{ci['source']}, {ci['section']}]")
    if warnings:
        out += ["", "In addition, please address the following points:", ""]
        for i in warnings:
            n += 1
            files = ", ".join(sorted({e["file"] for e in i["evidence"]})[:5])
            out.append(f"{n}. {i['title']} — {i['detail']}{(' (' + files + ')') if files else ''}")
    if not n:
        out.append("_No missing information identified: no letter is needed._")
    out += ["", "Please submit a consolidated version of the dossier within 30 days, with a cover letter describing how each point was "
                "addressed. If this is not possible, indicate the date by which you expect to respond and why.", "",
            "Kind regards,", "", "[EFSA officer]", "",
            "_Draft generated by KEvidence for review; edit before sending._"]
    return "\n".join(out) + "\n"


def check_dossier(uploads: list[tuple[str, bytes]], rules: dict, **kw) -> dict[str, Any]:
    files, notes = read_upload(uploads)
    dossier_ref = kw.pop("dossier_ref", "")
    result = run_checks(files, rules, **kw)
    result["notes"] = notes + [f"{f.path}: {f.error}" for f in files if f.error]
    result["report_markdown"] = report_markdown(result, dossier_ref)
    result["letter_markdown"] = missing_information_letter(result, dossier_ref, kw.get("applicant", ""))
    return result


def extract_file(uploads: list[tuple[str, bytes]], path: str) -> tuple[str, bytes]:
    """One file of the uploaded dossier (e.g. to sanitise it), looked up by its normalised path."""
    files, _ = read_upload_raw(uploads)
    for f in files:
        if f.path == _safe_path(path):
            return f.name, f.data
    raise CompletenessError("File not found in the dossier.")


def read_upload_raw(uploads: list[tuple[str, bytes]]) -> tuple[list[DossierFile], list[str]]:
    """read_upload without text extraction or classification (fast path for extract_file)."""
    files: list[DossierFile] = []
    for name, data in uploads:
        if name.lower().endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise CompletenessError(f"{name}: not a readable ZIP archive.") from None
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
                raise CompletenessError(f"{name}: the archive is too large once expanded.")
            for info in infos:
                if info.file_size <= MAX_FILE_BYTES:
                    files.append(DossierFile(path=_safe_path(info.filename), data=zf.read(info), ext="", size=info.file_size))
        else:
            files.append(DossierFile(path=_safe_path(name), data=data, ext="", size=len(data)))
    return files, []
