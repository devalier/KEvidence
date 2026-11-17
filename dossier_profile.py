"""Derive the workbench's form fields from an uploaded dossier (the automatic entry path).

Everything here is local pattern matching over the dossier text: no AI. Every derived field carries
where it was found (file and page) or says that it was inferred from another derived field, so the
assessor can confirm or correct it. Fields the dossier cannot answer are left empty, never guessed:
in particular the study IDs notified in EFSA's database are not taken from the dossier, because the
Art. 22(3) check compares the dossier against them.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Optional

# Applicant names end in a legal-form suffix; the most frequent such line across files is the applicant
# (dossier headers and footers repeat it, the names of test facilities appear once).
LEGAL_FORM = (r"S\.?A\.?|S\.?r\.?l\.?|S\.?p\.?A\.?|S\.?A\.?S\.?|GmbH|AG|Ltd\.?|Limited|LLC|Inc\.?|B\.?V\.?|N\.?V\.?|A/S|ApS|"
              r"AB|Oy|plc|Corp\.?|Co\.?|KG|S\.?L\.?|SE|Sp\.\s?z\s?o\.?o\.?|s\.?r\.?o\.?|Kft\.?")
ENTITY_RE = re.compile(rf"^\s*([A-Z][\w&.,'’ -]{{1,80}}?\s(?i:{LEGAL_FORM}))\s*$", re.M)
APPLICANT_RE = re.compile(rf"\bapplicant\s*[:\-]\s*(?:\([a-z]\)\s*)?([A-Z][^\n]{{1,120}}?\s(?:{LEGAL_FORM}))(?=[,;\n]|\s*$)", re.I | re.M)
PREAPP_ID_RE = re.compile(r"pre-?\s*application\s*(?:ID|identifier|number)s?\b\s*[:#]?\s*([A-Z0-9][A-Z0-9_./-]{3,})", re.I)
REF_RE = re.compile(r"(?:dossier|application)\s+(?:reference|ref\.?|number)\s*[:#]\s*([A-Z0-9][A-Z0-9_./-]{3,})", re.I)
FOLDER_REF_RE = re.compile(r"^[A-Z]{2,}[-_][A-Z0-9_-]*\d[A-Z0-9_-]*$")
USE_LEVEL_RE = re.compile(r"\b((?:up\s+to|maximum(?:\s+(?:use\s+)?level)?(?:\s+of)?|max\.?)\s*"
                          r"\d[\d.,]*\s*(?:mg|g|µg|μg|ug|IU|U|CFU|ml|mL)\s*/\s*(?:kg|l|L|t)\b[^.\n]{0,40})", re.I)

# Field-labelled values in application forms and summaries ("Target species: ...").
LABELS = {
    "substance": [r"additive", r"(?:trade|product)\s+name", r"name\s+of\s+the\s+(?:additive|enzyme|substance|product|novel\s+food)",
                  r"food\s+enzyme\s+name[^:\n]*", r"active\s+substance", r"substance"],
    "species": [r"target\s+(?:species|animals?)(?:/categor\w+)?", r"species(?:/categor\w+)?"],
    "category": [r"category"],
    "matrix": [r"foods?\s*(?:categor\w+)?", r"matrix"],
}


def _label_value(text: str, labels: list[str]) -> Optional[re.Match]:
    for label in labels:
        # "Label: value" on one line, or "Label:" with the value alone on the next line.
        m = re.search(rf"^[ \t]*(?:\([a-z]\)\s*)?(?:{label})\s*(?:\([^)\n]*\))?\s*:[ \t]*([^\n]*\S)?[ \t]*(?:\n[ \t]*([^\n:]{{2,120}}?)[ \t]*$)?",
                      text, re.I | re.M)
        if m and (m.group(1) or m.group(2)):
            return m
    return None


class _Doc:
    """A file's pages as (path, page number, text); shared by every extractor."""

    def __init__(self, path: str, pages: list[str], role: str, part: str):
        self.path, self.pages, self.role, self.part = path, pages, role, part


def _cite(doc: _Doc, page: int) -> dict[str, Any]:
    return {"file": doc.path, "page": page}


def _field(value: Any, source: Optional[dict] = None, basis: str = "found", note: str = "") -> dict[str, Any]:
    """basis: 'found' (read in the dossier), 'inferred' (follows from another derived field), 'default'."""
    out = {"value": value, "basis": basis, "source": source}
    if note:
        out["note"] = note
    return out


def _ordered(docs: list[_Doc]) -> list[_Doc]:
    """Administrative documents and summaries first: they state identity and scope most plainly."""
    rank = {"application_form": 0, "cover_letter": 1, "pubsum": 2, "scsum": 3, "sect_II": 4}
    return sorted(docs, key=lambda d: (d.part == "confidential", rank.get(d.role, 9), d.path))


def _first(docs: list[_Doc], fn) -> Optional[tuple[Any, dict]]:
    for d in _ordered(docs):
        for i, page in enumerate(d.pages[:40], 1):
            hit = fn(page)
            if hit:
                return hit, _cite(d, i)
    return None


def detect_domain(docs: list[_Doc], registry: dict[str, Any]) -> dict[str, Any]:
    """Score each registered domain by its `dossier_cues` (regulation numbers weigh most). Ties or no cue: undecided."""
    scores: dict[str, float] = {}
    evidence: dict[str, dict] = {}
    for dom in registry["domains"]:
        cues = dom.get("dossier_cues") or {}
        total = 0.0
        for weight_key, weight in (("regulations", 3.0), ("phrases", 1.0)):
            for cue in cues.get(weight_key, []):
                rx = re.compile(cue, re.I)
                for d in docs:
                    for i, page in enumerate(d.pages[:40], 1):
                        n = len(rx.findall(page))
                        if n:
                            # Saturate per file so one long document cannot outvote the rest of the dossier.
                            boost = 2.0 if d.role in ("application_form", "cover_letter", "pubsum") else 1.0
                            total += weight * boost * min(n, 3)
                            evidence.setdefault(dom["id"], _cite(d, i))
                            break
        if total:
            scores[dom["id"]] = total
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out = {"scores": {k: round(v, 1) for k, v in ranked}}
    if not ranked:
        return {**out, "field": _field(None, basis="not_found", note="No regulation or product-type cue of a registered domain found.")}
    if len(ranked) > 1 and ranked[1][1] >= 0.8 * ranked[0][1]:
        top = ", ".join(k for k, _ in ranked[:2])
        return {**out, "field": _field(ranked[0][0], evidence[ranked[0][0]], "found",
                                       note=f"Close call between {top}: confirm the domain.")}
    return {**out, "field": _field(ranked[0][0], evidence[ranked[0][0]])}


def detect_application_type(docs: list[_Doc]) -> dict[str, Any]:
    def ticked(page: str) -> Optional[str]:
        for line in page.splitlines():
            s = line.strip()
            if any(s.startswith(t) for t in ("☒", "☑", "✓", "✔", "■", "[x]", "[X]")):
                low = s.lower()
                if "renew" in low:
                    return "renewal"
                if "modification" in low or "extension" in low:
                    return "modification"
                if "new" in low:
                    return "new"
        return None

    hit = _first(docs, ticked)
    if hit:
        return _field(hit[0], hit[1])
    for kind, rx in (("renewal", r"\brenewal\s+of\s+(?:the\s+)?authori[sz]ation|\bapplication\s+for\s+(?:the\s+)?renewal"),
                     ("modification", r"\b(?:use\s+extension|extension\s+of\s+(?:the\s+)?use|modification\s+of\s+(?:the\s+)?"
                                      r"(?:conditions\s+of\s+use|authori[sz]ation|specifications?))"),
                     ("new", r"\bapplication\s+for\s+(?:the\s+)?authori[sz]ation\b|\bnew\s+(?:feed\s+additive|food\s+enzyme|application)")):
        hit = _first(docs, lambda p, rx=rx: re.search(rx, p, re.I))
        if hit:
            return _field(kind, hit[1])
    return _field(None, basis="not_found")


def detect_applicant(docs: list[_Doc]) -> dict[str, Any]:
    hit = _first(docs, lambda p: (m := APPLICANT_RE.search(p)) and m.group(1).rstrip(" ,;"))
    if hit:
        return _field(hit[0], hit[1])
    counts: Counter = Counter()
    where: dict[str, dict] = {}
    for d in docs:
        seen = set()
        for i, page in enumerate(d.pages[:40], 1):
            for m in ENTITY_RE.finditer(page):
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                if name not in seen:
                    seen.add(name)
                    counts[name] += 1
                    where.setdefault(name, _cite(d, i))
    if counts:
        name, n = counts.most_common(1)[0]
        if n >= 2 or len(docs) == 1:
            return _field(name, where[name], note=f"Named in {n} file(s); confirm it is the applicant.")
    return _field(None, basis="not_found")


def detect_dossier_ref(docs: list[_Doc]) -> dict[str, Any]:
    hit = _first(docs, lambda p: (m := REF_RE.search(p)) and m.group(1).rstrip("."))
    if hit:
        return _field(hit[0], hit[1])
    tops = {PurePosixPath(d.path).parts[0] for d in docs if len(PurePosixPath(d.path).parts) > 1}
    if len(tops) == 1:
        top = tops.pop()
        if FOLDER_REF_RE.match(top):
            return _field(top, {"file": top + "/", "page": None}, note="Name of the dossier's top folder.")
    return _field(None, basis="not_found")


def detect_pre_application_ids(docs: list[_Doc]) -> dict[str, Any]:
    ids: list[str] = []
    src = None
    for d in _ordered(docs):
        for i, page in enumerate(d.pages[:40], 1):
            for m in PREAPP_ID_RE.finditer(page):
                v = m.group(1).rstrip(".,;")
                if v not in ids:
                    ids.append(v)
                    src = src or _cite(d, i)
    return _field(ids, src) if ids else _field([], basis="not_found")


def detect_labelled(docs: list[_Doc], key: str) -> dict[str, Any]:
    def fn(page: str):
        m = _label_value(page, LABELS[key])
        if not m:
            return None
        v = (m.group(1) or m.group(2) or "").strip(" .;")
        return v[:200] if v and len(v) > 1 else None
    hit = _first(docs, fn)
    return _field(hit[0], hit[1]) if hit else _field(None, basis="not_found")


def detect_use_level(docs: list[_Doc]) -> dict[str, Any]:
    pref = [d for d in docs if d.role in ("application_form", "sect_II", "pubsum")] or docs
    hit = _first(pref, lambda p: (m := USE_LEVEL_RE.search(p)) and re.sub(r"\s+", " ", m.group(1)).strip(" .;"))
    return _field(hit[0], hit[1]) if hit else _field(None, basis="not_found")


def detect_processes(docs: list[_Doc]) -> dict[str, Any]:
    """Food manufacturing processes listed by a food enzyme dossier ("Production of baked products")."""
    procs: list[str] = []
    src = None
    for d in _ordered(docs):
        for i, page in enumerate(d.pages[:40], 1):
            for m in re.finditer(r"^[\s•·\-–]*((?:production|manufacture|processing)\s+of\s+[^\n]{3,90}?)\s*$", page, re.I | re.M):
                v = m.group(1).strip(" .;")
                # A heading or sentence fragment ("Production of the food enzyme and how it is"), not a food process.
                if re.search(r"enzyme|\b(?:is|are|and|or|the|of|to|in|which|that)$", v, re.I):
                    continue
                if v.lower() not in {p.lower() for p in procs}:
                    procs.append(v[0].upper() + v[1:])
                    src = src or _cite(d, i)
        if len(procs) >= 12:
            break
    return _field(procs, src) if procs else _field([], basis="not_found")


def detect_routes(docs: list[_Doc]) -> dict[str, Any]:
    """Feed additive administration routes (characterisation §2.4/§2.5): feed, premixtures, drinking water."""
    found: list[str] = []
    src = None
    for key, rx in (("feed", r"complete\s+feed|feedingstuffs?|compound\s+feed|in\s+feed\b"),
                    ("premixture", r"premix(?:ture)?s?\b"), ("water", r"(?:drinking\s+water|water\s+for\s+drinking)")):
        hit = _first([d for d in docs if d.role in ("application_form", "sect_II", "pubsum", "scsum")] or docs,
                     lambda p, rx=rx: re.search(rx, p, re.I))
        if hit:
            found.append(key)
            src = src or hit[1]
    return _field(found, src) if found else _field([], basis="not_found")


ASSESSMENT_TYPE = {"new": "New application", "modification": "Modification / extension of use", "renewal": "Renewal / re-evaluation"}
AUTH_STATUS = {"new": "New application (not yet authorised)", "modification": "Authorised — modification / extension of use requested",
               "renewal": "Authorised — renewal requested"}


def derive(files: list[Any], registry: dict[str, Any], domain_override: str = "") -> dict[str, Any]:
    """Profile of the dossier: every field the workbench asks for that the dossier can answer.

    `files` are completeness.DossierFile objects (text already extracted and classified)."""
    docs = [_Doc(f.path, f.pages, f.role, f.part) for f in files if f.pages and not f.error]
    domains = {d["id"]: d for d in registry["domains"]}
    dom = detect_domain(docs, registry)
    if domain_override in domains:
        dom["field"] = _field(domain_override, None, "chosen", note="Set by the assessor.")
    domain_id = dom["field"]["value"]
    dinfo = domains.get(domain_id or "", {})
    feed = domain_id == "feed"

    app_type = detect_application_type(docs)
    substance = detect_labelled(docs, "substance")
    species = detect_labelled(docs, "species") if feed else _field(None, basis="not_found")
    category = detect_labelled(docs, "category")
    use_level = detect_use_level(docs)
    processes = detect_processes(docs) if domain_id == "food-enzymes" else _field([], basis="not_found")
    routes = detect_routes(docs) if feed else _field([], basis="not_found")

    f: dict[str, dict] = {
        "domain": dom["field"],
        "application_type": app_type,
        "applicant": detect_applicant(docs),
        "dossier_ref": detect_dossier_ref(docs),
        "pre_application_ids": detect_pre_application_ids(docs),
        "substance": substance,
        "species": species,
        "use_level": use_level,
        "routes": routes,
    }
    # Problem formulation, from the fields above. "inferred" fields follow from a found field or the domain.
    if app_type["value"]:
        f["assessment_type"] = _field(ASSESSMENT_TYPE[app_type["value"]], app_type["source"], "inferred")
        f["authorization_status"] = _field(AUTH_STATUS[app_type["value"]], app_type["source"], "inferred")
    if category["value"] and feed:
        f["intended_use"] = category
    elif processes["value"]:
        f["intended_use"] = _field("Processing aid in: " + "; ".join(p.lower() for p in processes["value"]), processes["source"])
        f["matrix"] = _field("; ".join(processes["value"]), processes["source"])
    if feed:
        if species["value"]:
            f["population"] = _field(species["value"], species["source"], "inferred")
        f["route"] = _field("Oral, via " + (", ".join({"feed": "feed", "premixture": "premixtures", "water": "drinking water"}[r]
                                                      for r in routes["value"]) or "feed"),
                            routes["source"], "inferred" if routes["value"] else "default")
        if not f.get("matrix") and "feed" in routes["value"]:
            f["matrix"] = _field("Complete feed", routes["source"], "inferred")
    elif domain_id:
        f["route"] = _field("Dietary oral", None, "default", note="Default for food-domain applications.")
        f["population"] = _field("Consumers (general population, all age groups)", None, "default")
    if dinfo.get("legal_context"):
        f["legal_context"] = _field(dinfo["legal_context"], dom["field"]["source"], "inferred")
        f["decision_context"] = _field(f"Scientific opinion on the application, for the risk manager under {dinfo['legal_context']}",
                                       None, "default")
    if substance["value"]:
        target = {"feed": "for the target species, consumers, users and the environment", "food-enzymes": "for consumers"}.get(domain_id or "", "")
        conditions = f" at {use_level['value'][0].lower() + use_level['value'][1:]}" if use_level["value"] else " under the proposed conditions of use"
        f["regulatory_question"] = _field(f"Is {substance['value']} safe {target}{conditions}?".replace("  ", " "),
                                          substance["source"], "inferred", note="Drafted from the dossier: edit as needed.")
    f["output_purpose"] = _field("draft narrative support", None, "default", note="Default for an application dossier.")
    not_derivable = {
        "notified_study_ids": "Comes from EFSA's study-notification database, not from the dossier: the check compares the dossier against it.",
        "endpoint_domain": "Set by the assessor once hazards are identified.",
        "duration": "Set by the assessor in the exposure assessment.",
    }
    return {"fields": f, "domain_scores": dom["scores"], "not_derivable": not_derivable,
            "files_read": len(docs), "files_total": len(files)}
