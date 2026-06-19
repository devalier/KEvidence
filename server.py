#!/usr/bin/env python3
"""
kevidence.devalier.com — AI Augmented Regulatory Chatbot for AOP-Wiki
Use case #7 from the AOP Wiki analysis: "Regulatory Augmented Chatbot"
"""

import csv
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = Path("/var/www/kevidence/data")
STATIC_DIR = Path("/var/www/kevidence/static")
AOP_CACHE_DIR = DATA_DIR / "aops"
DB_PATH = DATA_DIR / "kevidence.db"
LLM_MODEL = "gpt-4o-mini"  # cheap, good enough for protoype

app = FastAPI(title="KEvidence — Risk Assessment Workbench")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Case-insensitive, ASCII-folded string for matching."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.lower().strip()


def load_aop_list():
    """Load (aop_id, title, oecd_status) from the TSV."""
    aops = {}
    with open(DATA_DIR / "aop_ke_mie_ao.tsv") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row or not row[0].startswith("Aop:"):
                continue
            aop_id = int(row[0].replace("Aop:", ""))
            if aop_id not in aops:
                aops[aop_id] = {
                    "id": aop_id,
                    "kievs": [],
                    "mie": None,
                    "ao": None,
                    "oecd_status": "Unknown",
                    "title": "",
                }
    return aops


def build_db():
    """Load TSV data into SQLite for fast querying."""
    if DB_PATH.exists():
        return
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aops (
            id INTEGER PRIMARY KEY,
            title TEXT,
            mie TEXT,
            ao TEXT,
            oecd_status TEXT DEFAULT 'Unknown'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER,
            aop_id INTEGER,
            event_id INTEGER,
            event_type TEXT,
            event_name TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kers (
            aop_id INTEGER,
            upstream_event_id INTEGER,
            downstream_event_id INTEGER,
            rel_id INTEGER,
            rel_type TEXT,
            evidence INTEGER,
            quantitative INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_components (
            aop_id INTEGER,
            event_id INTEGER,
            action TEXT,
            object_source TEXT,
            object_ontology_id TEXT,
            object_term TEXT,
            process_source TEXT,
            process_ontology_id TEXT,
            process_term TEXT
        )
    """)

    # Load AOP-KE table
    seen_aops = {}
    with open(DATA_DIR / "aop_ke_mie_ao.tsv") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row or not row[0].startswith("Aop:"):
                continue
            aop_id = int(row[0].replace("Aop:", ""))
            event_id = int(row[1].replace("Event:", ""))
            event_type = row[2]
            event_name = row[3]
            if aop_id not in seen_aops:
                seen_aops[aop_id] = {"mie": None, "ao": None, "title": ""}

            # Derive title from MIE+AO where possible
            if event_type == "MolecularInitiatingEvent":
                seen_aops[aop_id]["mie"] = event_name
            elif event_type == "AdverseOutcome":
                seen_aops[aop_id]["ao"] = event_name

            # Title heuristic: "MIE leading to AO"
            parts = event_name.split(",", 1)
            short_name = parts[1].strip() if len(parts) > 1 else event_name

            cur.execute(
                "INSERT INTO events (aop_id, event_id, event_type, event_name) VALUES (?, ?, ?, ?)",
                (aop_id, event_id, event_type, event_name),
            )
            seen_aops[aop_id]["title"] = event_name

    # Fill AOP titles
    for aop_id, info in seen_aops.items():
        mie = info["mie"] or "Unknown MIE"
        ao = info["ao"] or "Unknown AO"
        title = f"{mie} leading to {ao}"
        # Clean up — take the first event_name if it looks like a title
        cur.execute(
            "INSERT OR REPLACE INTO aops (id, title, mie, ao) VALUES (?, ?, ?, ?)",
            (aop_id, title, mie, ao),
        )

    # Load KERs
    with open(DATA_DIR / "aop_ke_ker.tsv") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row or not row[0].startswith("Aop:"):
                continue
            aop_id = int(row[0].replace("Aop:", ""))
            up = int(row[1].replace("Event:", ""))
            down = int(row[2].replace("Event:", ""))
            rel_id = int(row[3].replace("Relationship:", ""))
            rel_type = row[4]
            evidence = int(row[5]) if len(row) > 5 and row[5].strip() else None
            quant = int(row[6]) if len(row) > 6 and row[6].strip() else None
            cur.execute(
                "INSERT INTO kers (aop_id, upstream_event_id, downstream_event_id, rel_id, rel_type, evidence, quantitative) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (aop_id, up, down, rel_id, rel_type, evidence, quant),
            )

    # Load event components
    with open(DATA_DIR / "aop_ke_ec.tsv") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row or not row[0].startswith("Aop:"):
                continue
            aop_id = int(row[0].replace("Aop:", ""))
            event_id = int(row[1].replace("Event:", ""))
            action = row[2]
            obj_src = row[3] if len(row) > 3 else ""
            obj_ont = row[4] if len(row) > 4 else ""
            obj_term = row[5] if len(row) > 5 else ""
            proc_src = row[6] if len(row) > 6 else ""
            proc_ont = row[7] if len(row) > 7 else ""
            proc_term = row[8] if len(row) > 8 else ""
            cur.execute(
                "INSERT INTO event_components (aop_id, event_id, action, object_source, object_ontology_id, object_term, process_source, process_ontology_id, process_term) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aop_id, event_id, action, obj_src, obj_ont, obj_term, proc_src, proc_ont, proc_term),
            )

    conn.commit()
    conn.close()
    print(f"DB built at {DB_PATH}")


def _build_chemical_index():
    """Parse XML for chemical + stressor data and add AOP-stressor mappings to DB."""
    xml_path = DATA_DIR / "aop-wiki-xml.gz"
    if not xml_path.exists():
        print("No XML file found, skipping chemical index")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Create chemicals and stressors tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chemicals (
            uuid TEXT PRIMARY KEY,
            preferred_name TEXT,
            casrn TEXT,
            dsstox_id TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chemical_synonyms (
            chemical_uuid TEXT,
            synonym TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stressors (
            uuid TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aop_stressors (
            aop_uuid TEXT,
            stressor_uuid TEXT,
            evidence TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aop_chemicals (
            aop_uuid TEXT,
            chemical_uuid TEXT
        )
    """)

    # Check if already populated
    cur.execute("SELECT COUNT(*) FROM chemicals")
    if cur.fetchone()[0] > 0:
        conn.close()
        print("Chemical index already populated")
        return

    import gzip
    with gzip.open(str(xml_path), "rt", errors="replace") as f:
        content = f.read()

    # Parse chemicals
    chem_count = 0
    for m in re.finditer(r'<chemical\s+id="([^"]+)">(.*?)</chemical\s*>', content, re.DOTALL):
        uid = m.group(1)
        body = m.group(2)
        name = re.search(r'<preferred-name>(.*?)</preferred-name>', body)
        casrn = re.search(r'<casrn>(.*?)</casrn>', body)
        dsstox = re.search(r'<dsstox-id>(.*?)</dsstox-id>', body)
        cur.execute(
            "INSERT OR IGNORE INTO chemicals (uuid, preferred_name, casrn, dsstox_id) VALUES (?, ?, ?, ?)",
            (uid, name.group(1) if name else "", casrn.group(1) if casrn else "", dsstox.group(1) if dsstox else ""),
        )
        chem_count += 1
        # Synonyms
        for syn in re.finditer(r'<synonym>(.*?)</synonym>', body):
            cur.execute("INSERT OR IGNORE INTO chemical_synonyms (chemical_uuid, synonym) VALUES (?, ?)",
                        (uid, syn.group(1).strip()))

    # Parse stressors
    stressor_count = 0
    for m in re.finditer(r'<stressor\s+id="([^"]+)">.*?<name>(.*?)</name>', content, re.DOTALL):
        cur.execute("INSERT OR IGNORE INTO stressors (uuid, name) VALUES (?, ?)",
                    (m.group(1), m.group(2).strip()))
        stressor_count += 1

    # Parse AOP elements for stressor + chemical references
    aop_count = 0
    for m in re.finditer(r'<aop[ >].*?</aop\s*>', content, re.DOTALL):
        aop_uid_match = re.search(r'<aop\s+id="([^"]+)"', m.group())
        if not aop_uid_match:
            continue
        aop_uid = aop_uid_match.group(1)
        aop_body = m.group()

        # Stressor refs
        for s in re.finditer(r'<aop-stressor\s+stressor-id="([^"]+)"\s*>\s*<evidence>(.*?)</evidence>', aop_body, re.DOTALL):
            cur.execute("INSERT OR IGNORE INTO aop_stressors (aop_uuid, stressor_uuid, evidence) VALUES (?, ?, ?)",
                        (aop_uid, s.group(1), s.group(2).strip()))

        # Also check for stressor-reference elements (newer format?)
        for s in re.finditer(r'<stressor-reference[^>]*id="([^"]+)"', aop_body):
            cur.execute("INSERT OR IGNORE INTO aop_stressors (aop_uuid, stressor_uuid, evidence) VALUES (?, ?, ?)",
                        (aop_uid, s.group(1), "Not Specified"))

        # Chemical refs
        for c in re.finditer(r'<chemical-reference[^>]*id="([^"]+)"', aop_body):
            cur.execute("INSERT OR IGNORE INTO aop_chemicals (aop_uuid, chemical_uuid) VALUES (?, ?)",
                        (aop_uid, c.group(1)))

        aop_count += 1

    conn.commit()
    conn.close()
    print(f"Chemical index built: {chem_count} chems, {stressor_count} stressors, {aop_count} AOPs")


build_db()
_build_chemical_index()


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def search_aops_text(query: str, limit: int = 10):
    """Search AOPs by keyword in title, events, or event components.
    Uses individual keywords + AOP ID detection for robust search."""
    conn = get_db()
    cur = conn.cursor()

    # Check for explicit AOP ID mentions like "AOP 3", "AOP3", or just "3" in context
    aop_id_matches = re.findall(r"(?:AOP\s*)(\d{1,4})", query, re.I)
    if not aop_id_matches:
        # Also match standalone numbers that look like AOP IDs
        aop_id_matches = re.findall(r"\bAOP[\s#]*?(\d{1,4})\b", query, re.I)
    
    # If we found an explicit AOP ID reference, return that AOP
    for aid_str in aop_id_matches:
        aid = int(aid_str)
        cur.execute("SELECT id, title, mie, ao FROM aops WHERE id = ?", (aid,))
        row = cur.fetchone()
        if row:
            conn.close()
            return [dict(row)]

    seen = {}
    raw_results = []

    # Extract meaningful keywords (skip common English words)
    stopwords = {"which", "what", "how", "why", "where", "when", "who", "do", "does",
                 "is", "are", "was", "were", "the", "a", "an", "and", "or", "for",
                 "of", "to", "in", "it", "with", "that", "this", "i", "me", "my",
                 "you", "your", "they", "them", "their", "about", "tell", "show",
                 "find", "list", "give", "have", "has", "not", "can", "all",
                 "would", "could", "should", "some", "any", "from", "by", "at",
                 "be", "been", "being", "also", "very", "just", "such", "each",
                 "both", "more", "most", "other", "into", "than", "then", "so",
                 "no", "if", "out", "up", "like", "use", "used", "using",
                 "regulatory", "science", "scientist", "related", "involve",
                 "involves", "involving", "please",
                 # Words that cause false positives via substring match in titles/events
                 "eat", "bit", "say", "see", "get", "set", "put", "let", "run",
                 "cut", "hit", "sit", "fit", "win", "die", "try", "ask","age",
                 "ago", "few", "own", "old", "new", "big", "hot", "bad", "low",
                 "top", "far", "due", "per", "via", "vs", "vs", "etc", "ie", "eg",
                 "red", "blue", "key", "eye", "end", "way", "day", "week", "month",
                 "year", "time", "thing", "help", "need", "want", "look", "make",
                 "take", "come", "know", "think", "work", "live", "move", "keep",
                 "bring", "leave", "begin", "start", "stop", "done", "done",
                 # Substring false positive hazards in AOP titles/events
                 "there", "here", "where", "than", "then", "else", "also", "even",
                 "still", "just", "very", "much", "many", "some", "all", "any",
                 "both", "each", "such", "same", "thing", "part", "area", "line",
                 "step", "type", "form", "case", "fact", "idea", "kind", "sort",
                 "means", "cause", "lead", "role", "need", "side", "way", "point",
                 # Food items that aren't AOP chemicals
                 "peach", "bits", "apple", "seed", "food", "fruit", "meat", "bread",
                 "rice", "bean", "fish", "milk", "salt", "soup", "cake", "wine",
                 "beer", "corn", "rice", "sugar", "honey", "lemon", "onion",
                 "drink", "water", "juice", "cream", "butter", "cheese", "pork",
                 "beef", "chicken", "lamb", "sauce", "spice", "herb", "leaf"}

    terms = [t.lower().strip(".,;:!?\"'") for t in query.split()]
    # Min 4 chars to avoid false positives from substring matches in AOP titles
    keywords = [t for t in terms if len(t) >= 4 and t not in stopwords]

    if not keywords:
        keywords = [query.lower().strip()]

    # Also search the whole query as a phrase (for multi-word matches)
    # Only use phrase search if query has 2+ words to avoid single-word noise
    if len(query.split()) >= 2:
        q_phrase = f"%{query.lower()}%"
        for tbl, score in [("aops", 5), ("events", 3)]:
            if tbl == "aops":
                cur.execute(
                    "SELECT id, title, mie, ao FROM aops WHERE LOWER(title) LIKE ? LIMIT 5",
                    (q_phrase,),
                )
            else:
                cur.execute(
                    """SELECT DISTINCT a.id, a.title, a.mie, a.ao FROM aops a
                       JOIN events e ON e.aop_id = a.id
                       WHERE LOWER(e.event_name) LIKE ? LIMIT 5""",
                    (q_phrase,),
                )
            for row in cur.fetchall():
                d = dict(row)
                if d["id"] not in seen:
                    seen[d["id"]] = 0
                    raw_results.append(d)
                seen[d["id"]] += score

    # Search each keyword individually (breadth-first)
    # Use WORD-BOUNDARY matching to avoid substring false positives
    # A keyword matches if it appears as a standalone word (preceded/followed by
    # space, punctuation, or string boundary)
    for kw in keywords:
        # Build patterns for word-boundary matching
        # Match: keyword, keyword..., ...keyword, ...keyword..., "keyword", (keyword)
        word_q = f"%{kw} %"  # followed by space
        word_q2 = f"% {kw}%"  # preceded by space
        
        # Title search (word boundary)
        cur.execute(
            "SELECT id, title, mie, ao FROM aops "
            "WHERE (LOWER(title) = ? OR LOWER(title) LIKE ? OR LOWER(title) LIKE ?)"
            "LIMIT 8",
            (kw, word_q, word_q2),
        )
        for row in cur.fetchall():
            d = dict(row)
            if d["id"] not in seen:
                seen[d["id"]] = 0
                raw_results.append(d)
            seen[d["id"]] += 2

        # Event name search (word boundary)
        cur.execute(
            """SELECT DISTINCT a.id, a.title, a.mie, a.ao
               FROM aops a
               JOIN events e ON e.aop_id = a.id
               WHERE (LOWER(e.event_name) = ? OR LOWER(e.event_name) LIKE ? OR LOWER(e.event_name) LIKE ?)
               LIMIT 10""",
            (kw, word_q, word_q2),
        )
        for row in cur.fetchall():
            d = dict(row)
            if d["id"] not in seen:
                seen[d["id"]] = 0
                raw_results.append(d)
            seen[d["id"]] += 1

    # Sort by score descending, then by AOP ID
    raw_results.sort(key=lambda r: (-seen.get(r["id"], 0), r["id"]))

    conn.close()
    return raw_results[:limit]


def get_aop_detail(aop_id: int):
    """Get full AOP details including all events and KERs."""
    conn = get_db()
    cur = conn.cursor()

    aop = cur.execute("SELECT * FROM aops WHERE id = ?", (aop_id,)).fetchone()
    if not aop:
        conn.close()
        return None
    aop = dict(aop)

    aop["events"] = [dict(row) for row in cur.execute(
        "SELECT * FROM events WHERE aop_id = ? ORDER BY event_type", (aop_id,)
    ).fetchall()]

    aop["kers"] = [dict(row) for row in cur.execute(
        "SELECT * FROM kers WHERE aop_id = ?", (aop_id,)
    ).fetchall()]

    aop["components"] = [dict(row) for row in cur.execute(
        "SELECT * FROM event_components WHERE aop_id = ?", (aop_id,)
    ).fetchall()]

    # Load scraped text if available
    txt_path = AOP_CACHE_DIR / f"aop_{aop_id}.txt"
    if txt_path.exists():
        aop["full_text"] = txt_path.read_text()[:8000]
        # Try to extract OECD status from scraped text if not already set
        if not aop.get("oecd_status") or aop["oecd_status"] == "Unknown":
            oecd_patterns = [
                r"WPHA/WNT Endorsed",
                r"Under Review",
                r"Under Development",
                r"Open for Adoption",
            ]
            for pat in oecd_patterns:
                if re.search(pat, aop["full_text"], re.I):
                    aop["oecd_status"] = pat
                    break
    else:
        aop["full_text"] = ""

    conn.close()
    return aop


def get_all_aops():
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("SELECT id, title, mie, ao FROM aops ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------
llm = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are **kevidence**, an AI regulatory science assistant specialised in Adverse Outcome Pathways (AOPs). You help regulatory scientists, toxicologists, and risk assessors understand AOPs, weight of evidence, chemical-pathway associations, and OECD review status.

**Your knowledge base includes:**
- {aop_count} AOPs from the OECD AOP-Wiki (https://aopwiki.org)
- 421 chemicals with CAS numbers and DSSTox IDs from the AOP-Wiki
- Stressor-to-AOP mappings (738 prototypical stressors)
- Each AOP has: a Molecular Initiating Event (MIE), Key Events (KEs), Key Event Relationships (KERs), and an Adverse Outcome (AO)
- OECD status levels: WPHA/WNT Endorsed, Under Review, Under Development, Open for Adoption
- Weight of Evidence scored as High, Moderate, Low, or Not Specified for each KER
- Quantitative Understanding scored as High, Moderate, Low, or Not Specified
- Event Components linked to ontologies (GO, CHEBI, NCBITaxon, MESH, etc.)

**Rules:**
1. Be concise but thorough — regulatory scientists need evidence, not fluff
2. Cite specific AOP IDs and event names when relevant
3. Explain the regulatory significance (OECD status, evidence strength)
4. Present Weight of Evidence clearly: summarize the overall strength, then detail KER-level evidence
5. When asked about a chemical, identify the relevant AOPs and explain which pathways the chemical triggers
6. If you don't know something, say so — don't fabricate data
7. For OECD submission guidance, refer to the OECD AOP Development Programme workplan

You have access to search results from the AOP-Wiki database — use them to ground your answers. When the user asks about a specific chemical, pathway, or adverse outcome, reference the relevant AOPs.

**Examples of what you can do:**
- "Which AOPs involve mitochondrial dysfunction?" → list AOP 3, AOP 273, AOP 276
- "What's the weight of evidence for AOP 3?" → explain KER evidence scores + overall assessment
- "What AOPs are linked to rotenone?" → AOP 3 (complex I inhibition → Parkinsonian)
- "How do I submit an AOP for OECD review?" → guide through the workplan process
- "Is there an AOP for liver steatosis?" → yes, AOP 34, 36, 57-62, etc.
- "What's the weight of evidence for rotenone causing Parkinsonian deficits?" → chemical lookup + WoE"""


def build_context_for_query(query: str) -> str:
    """Search AOPs and build a context snippet for the LLM."""
    # Detect chemical name queries — add WoE data
    chemical_aops = find_aops_by_chemical(query)
    if chemical_aops:
        ctx_parts = []
        for a in chemical_aops[:3]:
            detail = get_aop_detail(a["aop_id"])
            if detail:
                ctx_parts.append(_format_aop_detail(detail, include_all_kers=True))
        if ctx_parts:
            chem_context = f"[CHEMICAL QUERY: '{query}' matched these chemicals via the AOP-Wiki chemical database]\n\n"
            return chem_context + "\n\n---\n\n".join(ctx_parts)

    # Detect explicit AOP ID reference for richer single-AOP context
    aop_id_matches = re.findall(r"(?:AOP\s*)(\d{1,4})", query, re.I)
    if aop_id_matches:
        detail = get_aop_detail(int(aop_id_matches[0]))
        if detail:
            ctx = _format_aop_detail(detail, include_all_kers=True, include_all_events=True)
            # Also grab a couple related AOPs as bonus context
            related = search_aops_text(detail["mie"] or detail["title"], limit=3)
            extras = []
            for r in related:
                if r["id"] != detail["id"]:
                    extra = get_aop_detail(r["id"])
                    if extra:
                        extras.append(_format_aop_detail(extra, include_all_kers=False))
            if extras:
                ctx += "\n\n---\n\nAlso related:\n\n" + "\n\n".join(extras)
            return ctx

    results = search_aops_text(query, limit=5)
    if not results:
        return ""

    ctx_parts = []
    for aop in results:
        detail = get_aop_detail(aop["id"])
        if detail:
            has_explicit_id = bool(re.findall(r"(?:AOP\s*)(\d{1,4})", query, re.I))
            ctx_parts.append(
                _format_aop_detail(detail, include_all_kers=not has_explicit_id)
            )

    return "\n\n---\n\n".join(ctx_parts)


def _format_aop_detail(detail: dict, include_all_kers: bool = True, include_all_events: bool = False) -> str:
    """Format an AOP detail dict into a readable string for the LLM context."""
    parts = [f"AOP {detail['id']}: {detail['title']}"]

    if detail.get("mie"):
        parts.append(f"  MIE: {detail['mie']}")
    if detail.get("ao"):
        parts.append(f"  AO: {detail['ao']}")
    if detail.get("oecd_status") and detail["oecd_status"] != "Unknown":
        parts.append(f"  OECD Status: {detail['oecd_status']}")

    # Key events
    event_limit = None if include_all_events else 10
    events = detail.get("events", [])
    if event_limit:
        events = events[:event_limit]
    for ev in events:
        parts.append(f"  KE ({ev['event_type']}): {ev['event_name']}")

    # KER evidence
    kers = detail.get("kers", [])
    if not include_all_kers:
        kers = kers[:8]
    for ker in kers:
        evidence_label = {1: "High", 2: "Moderate", 3: "Low", 5: "Not Specified"}.get(
            ker.get("evidence"), "Unknown"
        )
        quant_label = {1: "High", 2: "Moderate", 3: "Low", 5: "Not Specified"}.get(
            ker.get("quantitative"), "Unknown"
        )
        parts.append(
            f"  KER up={ker['upstream_event_id']} → down={ker['downstream_event_id']}"
            f" [{ker['rel_type']} | evidence={evidence_label} | quant={quant_label}]"
        )

    # Add scraped text if available
    full_text = detail.get("full_text", "")
    if full_text:
        # Extract prototypical stressors (chemical names associated with this AOP)
        stressor_section = re.search(
            r"Prototypical Stressors.*?(?=Abstract|AOP Development|Table of Contents|$)",
            full_text, re.DOTALL
        )
        if stressor_section:
            # Find lines that look like chemical names (single words ending in date)
            stressors = re.findall(
                r"(?:^|\n)\s{2,}([A-Z][a-zA-Z0-9+/-]+(?:\s+[A-Z][a-zA-Z0-9]+)?)\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)",
                stressor_section.group()
            )
            if stressors:
                parts.append(f"  Prototypical stressors: {', '.join(stressors)}")
            else:
                # Fallback: just grab lines around the stressor section
                text_clean = re.sub(r"<[^>]+>", " ", stressor_section.group())
                # Simple extraction of capitalized words after "Prototypical Stressors"
                stressor_names = re.findall(r"(?:MPP\+|Rotenone|Deguelin|Pyrimidifen|Fenpyroximate|Tebufenpyrad|MPTP|Paraquat|Maneb|Cyanide|Oligomycin|Antimycin)", text_clean, re.I)
                if stressor_names:
                    # Deduplicate preserving order
                    seen = set()
                    unique = []
                    for s in stressor_names:
                        if s.lower() not in seen:
                            seen.add(s.lower())
                            unique.append(s)
                    parts.append(f"  Prototypical stressors: {', '.join(unique)}")

        # Abstract
        abstract_match = re.search(
            r"(?:Abstract|abstract|This AOP describes|This Adverse outcome Pathway|A concise and informative summation)[^.]*(?:\.|$)",
            full_text,
        )
        if abstract_match:
            excerpt = abstract_match.group()[:600]
            parts.append(f"  Abstract: {excerpt}")
        else:
            # First meaningful paragraph
            clean = re.sub(r"<[^>]+>|\s+", " ", full_text)[:400].strip()
            if clean:
                parts.append(f"  Excerpt: {clean}")

    return "\n".join(parts)


def evidence_label(code):
    return {1: "High", 2: "Moderate", 3: "Low", 5: "Not Specified"}.get(code, "Unknown")


def find_aops_by_chemical(chemical_name: str) -> list:
    """Find AOPs associated with a chemical by name.
    Uses the XML stressor→AOP mapping (aop_stressors table) then resolves
    XML UUIDs to wiki AOP IDs by checking scraped text for the stressor name.
    Only returns matches when the stressor name is a KNOWN entity.
    Returns list of dicts with aop_id, aop_title, chemical, stressor."""
    results = []
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    q = f"%{chemical_name.lower()}%"

    # Find matching stressors (known entities from XML)
    cur.execute("SELECT uuid, name FROM stressors WHERE LOWER(name) LIKE ? LIMIT 10", (q,))
    stressor_matches = [{"uuid": r[0], "name": r[1]} for r in cur.fetchall()]

    # If no direct stressor match, try matching through chemicals table
    if not stressor_matches:
        cur.execute(
            "SELECT LOWER(preferred_name) FROM chemicals WHERE LOWER(preferred_name) LIKE ? LIMIT 5",
            (q,),
        )
        chem_names = [r[0] for r in cur.fetchall()]
        for cname in chem_names:
            cur.execute(
                "SELECT uuid, name FROM stressors WHERE LOWER(name) = ?", (cname,)
            )
            for s in cur.fetchall():
                stressor_matches.append({"uuid": s[0], "name": s[1]})

    if not stressor_matches:
        conn.close()
        return results

    # For each matching stressor, find AOP wikis via scraped text
    for sm in stressor_matches:
        sname_lower = sm["name"].lower()

        # Get aop_uuid from aop_stressors
        cur.execute("SELECT aop_uuid FROM aop_stressors WHERE stressor_uuid = ?", (sm["uuid"],))
        aop_uuids = [r[0] for r in cur.fetchall()]

        # For each aop_uuid, find the wiki AOP ID by searching scraped text
        for aop_uuid in aop_uuids:
            found_aop_id = None
            found_title = None

            # Search ALL scraped AOP text for this stressor name
            for fpath in AOP_CACHE_DIR.glob("aop_*.txt"):
                try:
                    aop_id = int(fpath.stem.replace("aop_", ""))
                    text = fpath.read_text().lower()

                    # Only match if stressor name appears in the PROTOTYPICAL STRESSOR section
                    # (revision dates table after KEs, before abstract)
                    stressor_section = re.search(
                        r"revision dates for related pages.*?abstract\s+a concise",
                        text, re.DOTALL,
                    )
                    if not stressor_section:
                        # Fallback: just check if stressor name appears in whole text
                        # but only if it's a named stressor (preceded/followed by date context)
                        if sname_lower not in text:
                            continue
                        # Accept if it appears in the context of dates
                        date_context = re.search(
                            rf"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{{1,2}},\s+\d{{4}}\s+\d{{2}}:\d{{2}}",
                            text,
                        )
                        if not date_context:
                            continue
                    else:
                        section = stressor_section.group()
                        if sname_lower not in section:
                            continue

                    # Found it!
                    found_aop_id = aop_id
                    # Get title from database
                    cur.execute("SELECT title FROM aops WHERE id = ?", (aop_id,))
                    t = cur.fetchone()
                    found_title = t[0] if t else f"AOP {aop_id}"
                    break
                except Exception:
                    continue

            if found_aop_id:
                results.append({
                    "aop_id": found_aop_id,
                    "aop_title": found_title,
                    "chemical": chemical_name,
                    "stressor": sm["name"],
                })

    conn.close()
    # Deduplicate
    seen_ids = set()
    unique = []
    for r in results:
        if r["aop_id"] not in seen_ids:
            seen_ids.add(r["aop_id"])
            unique.append(r)
    return unique[:10]


# ---------------------------------------------------------------------------
# Query Decomposition
# ---------------------------------------------------------------------------

DECOMPOSE_SYSTEM_PROMPT = """You are a toxicological reasoning assistant. The user's query will not match any known AOP entity directly. Your job is to DECOMPOSE the query into AOP-relevant entities (chemicals, stressors, adverse outcomes, biological processes) that the system can then look up in the AOP-Wiki database.

Think step by step about the chain from the user's everyday language to well-known toxicological concepts:

Examples:
- "what happens if I eat peach pits" → think: peach pits contain amygdalin → amygdalin metabolizes to cyanide → cyanide is a mitochondrial toxin → entities: ["cyanide"]
- "is sunscreen bad for coral reefs" → think: sunscreens contain oxybenzone → oxybenzone is an endocrine disruptor → entities: ["oxybenzone", "endocrine disruption"]
- "can plastic bottles cause cancer" → think: plastic bottles may leach bisphenol A → BPA is an estrogen receptor agonist → entities: ["bisphenol a", "estrogen receptor agonism"]
- "why is mercury dangerous" → think: mercury is a neurotoxicant → inhibits enzymes → entities: ["mercury", "neurotoxicity"]

RULES:
1. Only suggest entities that could plausibly exist in the AOP-Wiki
2. Prioritize specific chemical names (e.g., "cyanide" not "toxins")
3. Return 1-3 entities, STRICTLY as a JSON array of strings
4. If the query genuinely has nothing to do with toxicology, return an empty array

Respond with ONLY a JSON array: ["entity1", "entity2", "entity3"]"""


def _decompose_query(query: str) -> list:
    """Ask the LLM to suggest AOP-relevant entities the query might relate to.
    Returns list of entity name strings, or empty list if no plausible connection."""
    try:
        resp = llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Decompose this query: {query}"},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        content = resp.choices[0].message.content.strip()
        # Parse JSON array from response
        if content.startswith("[") and content.endswith("]"):
            entities = json.loads(content)
            if isinstance(entities, list):
                return [e.lower().strip() for e in entities if isinstance(e, str)][:3]
        # Try to extract JSON from markdown code block
        import json as _json
        json_match = re.search(r"\[.*?\]", content, re.DOTALL)
        if json_match:
            entities = _json.loads(json_match.group())
            if isinstance(entities, list):
                return [e.lower().strip() for e in entities if isinstance(e, str)][:3]
    except Exception:
        pass
    return []


def _decompose_with_verification(query: str, aop_count: int) -> Optional[dict]:
    """Ask the LLM to decompose the query, verify each entity against the DB,
    and return context with AOP data (if found) or a rich explanation."""
    entities = _decompose_query(query)
    if not entities:
        return None

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    found_aops = []  # entities with AOP data
    found_chems = []  # entities in chemical DB but no AOP
    not_found = []  # entities not in DB at all

    for entity in entities:
        # Check chemical/stressor → AOP
        chem_res = find_aops_by_chemical(entity)
        if chem_res:
            for r in chem_res:
                found_aops.append({"entity": entity, "aop_id": r["aop_id"], "title": r.get("aop_title", "")})
            continue

        # Check keyword → AOP
        aop_res = search_aops_text(entity, limit=3)
        if aop_res:
            for r in aop_res:
                found_aops.append({"entity": entity, "aop_id": r["id"], "title": r["title"]})
            continue

        # Check if chemical exists in DB (fuzzy match via LIKE)
        cur.execute(
            "SELECT preferred_name FROM chemicals WHERE LOWER(preferred_name) LIKE ? LIMIT 1",
            (f"%{entity.lower()}%",)
        )
        row = cur.fetchone()
        if row:
            found_chems.append(row[0])
            continue
        # Check synonyms (LIKE match)
        cur.execute(
            "SELECT synonym FROM chemical_synonyms WHERE LOWER(synonym) LIKE ? LIMIT 1",
            (f"%{entity.lower()}%",)
        )
        row = cur.fetchone()
        if row:
            found_chems.append(row[0])
            continue
        # Also check stressors
        cur.execute(
            "SELECT name FROM stressors WHERE LOWER(name) LIKE ? LIMIT 1",
            (f"%{entity.lower()}%",)
        )
        row = cur.fetchone()
        if row:
            found_chems.append(row[0])
            continue
        not_found.append(entity)

    conn.close()

    # CASE 1: Found AOP data → build context
    if found_aops:
        best = found_aops[0]
        detail = get_aop_detail(best["aop_id"])
        if detail:
            ctx = _format_aop_detail(detail, include_all_kers=True)
            ctx = f"[QUERY DECOMPOSITION: User asked about '{query}'. Suggested entity '{best['entity']}' maps to the following AOP data.]\n\n{ctx}"

            # Send to LLM with decomposition context
            system = SYSTEM_PROMPT.format(aop_count=aop_count)
            # Create a user message that includes both the decomposition and the original query
            user_msg = (
                f"A user asked: '{query}'\n\n"
                f"I analyzed this query and determined it relates to '{best['entity']}', "
                f"which maps to the following AOP data in the database:\n\n{ctx}\n\n"
                f"Please answer the user's original question using this AOP data. "
                f"Explain the chain: the user asked about '{query}' → relates to '{best['entity']}' → triggers this AOP."
            )
            try:
                resp = llm.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.3,
                    max_tokens=1200,
                )
                answer = resp.choices[0].message.content
                refs = re.findall(r"AOP\s+(\d+)", answer)
                source_aops = []
                for rid in refs[:5]:
                    d = get_aop_detail(int(rid))
                    if d:
                        source_aops.append({"id": d["id"], "title": d["title"]})
                return {"answer": answer, "sources": source_aops}
            except Exception as e:
                return {"answer": f"I found AOP data related to '{best['entity']}', but encountered an error processing it.", "sources": []}

    # CASE 2: No AOP data, but found chemicals in DB
    if found_chems:
        chain_parts = [f"'{e}' is in the AOP-Wiki chemical database" for e in found_chems]
        return {
            "answer": "Your query relates to " + ", ".join(f"'{e}'" for e in found_chems) +
                      ", which " + ("are " if len(found_chems) > 1 else "is ") +
                      "in the AOP-Wiki chemical database but not linked to any AOP yet. "
                      "This may be a gap in the current AOP coverage for this substance.",
            "sources": [],
            "no_data": True,
        }

    return None



# ---------------------------------------------------------------------------
# Evidence-to-decision assessment workspace
# ---------------------------------------------------------------------------

EVIDENCE_SCORE = {"High": 3, "Moderate": 2, "Low": 1, "Not Specified": 0, "Unknown": 0}


def _safe_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _confidence_from_score(score: float) -> str:
    """Convert a numeric evidence score to a regulator-readable confidence label."""
    if score >= 2.5:
        return "high"
    if score >= 1.6:
        return "moderate"
    if score >= 0.8:
        return "low"
    return "very low"


def _overall_confidence(*labels: str) -> str:
    """Conservative roll-up: overall confidence is constrained by weak evidence dimensions."""
    order = {"very low": 0, "low": 1, "moderate": 2, "high": 3}
    present = [order.get(label, 0) for label in labels if label]
    if not present:
        return "very low"
    avg = sum(present) / len(present)
    if min(present) == 0:
        avg -= 0.4
    return _confidence_from_score(avg)


def _available_data_for_aop(available_data: list[dict[str, Any]], detail: dict) -> list[dict[str, Any]]:
    """Return submitted data records that appear to map to this AOP's events or text."""
    if not available_data:
        return []

    event_ids = {ev.get("event_id") for ev in detail.get("events", [])}
    event_names = {str(ev.get("event_name", "")).lower() for ev in detail.get("events", [])}
    components = " ".join(
        " ".join(str(c.get(k, "")) for k in ("object_term", "process_term", "object_ontology_id", "process_ontology_id"))
        for c in detail.get("components", [])
    ).lower()

    mapped = []
    for record in available_data:
        if not isinstance(record, dict):
            continue
        record_aop_id = _safe_int(record.get("aop_id"))
        record_event_id = _safe_int(record.get("event_id"))
        if record_aop_id and record_aop_id == int(detail["id"]):
            mapped.append(record)
            continue
        if record_event_id in event_ids:
            mapped.append(record)
            continue
        endpoint = str(record.get("endpoint") or record.get("assay") or "").lower()
        if endpoint and (any(endpoint in name or name in endpoint for name in event_names) or endpoint in components):
            mapped.append(record)
    return mapped


def _event_data_coverage(detail: dict, mapped_data: list[dict[str, Any]]) -> dict[str, Any]:
    events = detail.get("events", [])
    event_ids = {ev.get("event_id") for ev in events}
    measured_ids = {_safe_int(r.get("event_id")) for r in mapped_data if _safe_int(r.get("event_id")) in event_ids}
    return {
        "measured_events": len(measured_ids),
        "total_events": len(event_ids),
        "coverage_fraction": round(len(measured_ids) / len(event_ids), 2) if event_ids else 0,
        "measured_event_ids": sorted(measured_ids),
    }


def _assessment_evidence_summary(detail: dict) -> dict[str, Any]:
    evidence_counts = {"High": 0, "Moderate": 0, "Low": 0, "Not Specified": 0, "Unknown": 0}
    quantitative_counts = {"High": 0, "Moderate": 0, "Low": 0, "Not Specified": 0, "Unknown": 0}
    kers = detail.get("kers", [])
    ker_details = []

    for ker in kers:
        ev_label = evidence_label(ker.get("evidence"))
        q_label = evidence_label(ker.get("quantitative"))
        evidence_counts[ev_label] = evidence_counts.get(ev_label, 0) + 1
        quantitative_counts[q_label] = quantitative_counts.get(q_label, 0) + 1
        ker_details.append({
            "upstream_event_id": ker.get("upstream_event_id"),
            "downstream_event_id": ker.get("downstream_event_id"),
            "relationship_type": ker.get("rel_type"),
            "evidence": ev_label,
            "quantitative_understanding": q_label,
        })

    evidence_score = (
        sum(EVIDENCE_SCORE.get(label, 0) * count for label, count in evidence_counts.items()) / len(kers)
        if kers else 0
    )
    quantitative_score = (
        sum(EVIDENCE_SCORE.get(label, 0) * count for label, count in quantitative_counts.items()) / len(kers)
        if kers else 0
    )

    return {
        "evidence_counts": evidence_counts,
        "quantitative_counts": quantitative_counts,
        "pathway_confidence": _confidence_from_score(evidence_score),
        "quantitative_confidence": _confidence_from_score(quantitative_score),
        "ker_details": ker_details,
        "total_kers": len(kers),
    }


def _infer_chemical_specific_confidence(mapped_data: list[dict[str, Any]], matched_by: str) -> str:
    if not mapped_data:
        return "moderate" if matched_by == "chemical/stressor index" else "low"
    quality_scores = []
    for record in mapped_data:
        quality = str(record.get("quality") or record.get("confidence") or "").lower()
        if quality in {"high", "validated", "guideline"}:
            quality_scores.append(3)
        elif quality in {"medium", "moderate", "acceptable"}:
            quality_scores.append(2)
        elif quality in {"low", "uncertain", "screening"}:
            quality_scores.append(1)
        else:
            quality_scores.append(2)
    return _confidence_from_score(sum(quality_scores) / len(quality_scores))


def _exposure_context_confidence(context: dict[str, Any]) -> str:
    if not context:
        return "very low"
    keys = {"route", "duration", "population", "species", "exposure", "use_case"}
    present = sum(1 for k in keys if context.get(k))
    if context.get("exposure"):
        present += 1
    return _confidence_from_score(min(3, present / 2))


def _build_uncertainties_and_gaps(detail: dict, confidence: dict[str, str], coverage: dict[str, Any], context: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    uncertainties = []
    gaps = []

    if confidence["chemical_specific"] in {"low", "very low"}:
        uncertainties.append({
            "type": "chemical-specific evidence",
            "description": "The AOP is biologically relevant, but submitted or indexed chemical-specific NAM/stressor evidence is limited.",
            "impact": "Limits confidence that this chemical perturbs the pathway under the assessment conditions.",
        })
        gaps.append({
            "priority": "high",
            "gap": "Add chemical-specific NAM or stressor evidence mapped to the MIE or earliest measurable KE.",
        })

    if confidence["quantitative"] in {"low", "very low"}:
        uncertainties.append({
            "type": "quantitative extrapolation",
            "description": "KER quantitative understanding is weak or not specified for much of the pathway.",
            "impact": "Supports qualitative hazard concern better than dose-response or point-of-departure derivation.",
        })
        gaps.append({
            "priority": "high",
            "gap": "Add concentration-response NAM data and, where possible, IVIVE or dosimetry to estimate a screening POD.",
        })

    if coverage["coverage_fraction"] < 0.5:
        gaps.append({
            "priority": "medium",
            "gap": "Measure additional downstream key events to improve pathway coverage and temporal concordance.",
        })

    weak_kers = [ker for ker in detail.get("kers", []) if evidence_label(ker.get("evidence")) in {"Low", "Not Specified", "Unknown"}]
    if weak_kers:
        uncertainties.append({
            "type": "KER support",
            "description": f"{len(weak_kers)} KER(s) have low, unknown, or unspecified evidence support.",
            "impact": "Weak KERs may limit confidence in progression from early perturbation to adverse outcome.",
        })

    if not context.get("exposure"):
        gaps.append({
            "priority": "medium",
            "gap": "Add exposure or internal concentration estimates to compare bioactivity with realistic exposure.",
        })

    if not (context.get("species") or context.get("population")):
        uncertainties.append({
            "type": "human/ecological relevance",
            "description": "The target species or population was not specified.",
            "impact": "Species applicability and susceptible-population relevance remain uncertain.",
        })

    return uncertainties, gaps


def _recommend_next_tests(detail: dict, coverage: dict[str, Any], gaps: list[dict[str, str]]) -> list[dict[str, str]]:
    recommendations = []
    measured = set(coverage.get("measured_event_ids", []))
    events = detail.get("events", [])

    mie = next((ev for ev in events if ev.get("event_type") == "MolecularInitiatingEvent"), None)
    if mie and mie.get("event_id") not in measured:
        recommendations.append({
            "rank": "1",
            "recommendation": f"Run or import a NAM that measures the MIE: {mie.get('event_name')}",
            "reason": "MIE evidence anchors chemical-specific pathway activation and is usually the fastest first uncertainty reducer.",
        })

    for ker in detail.get("kers", []):
        down_id = ker.get("downstream_event_id")
        if down_id in measured:
            continue
        if evidence_label(ker.get("evidence")) in {"High", "Moderate"}:
            ev = next((e for e in events if e.get("event_id") == down_id), None)
            if ev:
                recommendations.append({
                    "rank": str(len(recommendations) + 1),
                    "recommendation": f"Measure downstream KE {down_id}: {ev.get('event_name')}",
                    "reason": "This fills the first unmeasured downstream event connected by a moderate/high-evidence KER.",
                })
                break

    if any("exposure" in g.get("gap", "").lower() for g in gaps):
        recommendations.append({
            "rank": str(len(recommendations) + 1),
            "recommendation": "Add exposure, toxicokinetic, or IVIVE information for bioactivity-exposure comparison.",
            "reason": "Risk assessment decisions require context on whether pathway activity occurs near realistic exposure levels.",
        })

    return recommendations[:3]


def _regulatory_conclusion(confidence: dict[str, str], gaps: list[dict[str, str]]) -> str:
    high_priority_gaps = sum(1 for gap in gaps if gap.get("priority") == "high")
    overall = confidence.get("overall", "very low")
    if overall in {"high", "moderate"} and high_priority_gaps == 0:
        return "Sufficient for screening/prioritization and may support a transparent regulatory hazard hypothesis."
    if overall == "moderate":
        return "Sufficient for screening/prioritization, but targeted NAM or exposure data should be added before higher-tier decisions."
    if overall == "low":
        return "Useful for hypothesis generation and data-gap planning; insufficient as a stand-alone regulatory conclusion."
    return "Insufficient for regulatory decision-making beyond identifying data gaps and candidate follow-up NAMs."


def _hazard_hypothesis(detail: dict, chemical: str, matched_by: str, confidence: dict[str, str]) -> dict[str, Any]:
    chem_label = chemical or "The queried stressor/chemical"
    mie = detail.get("mie") or "an unspecified molecular initiating event"
    ao = detail.get("ao") or "an unspecified adverse outcome"
    conclusion = (
        f"{chem_label} has a plausible hazard hypothesis via AOP {detail['id']}: "
        f"{mie} leading to {ao}. Overall confidence is {confidence['overall']}."
    )
    return {
        "aop_id": detail["id"],
        "title": detail.get("title", ""),
        "matched_by": matched_by,
        "molecular_initiating_event": mie,
        "adverse_outcome": ao,
        "oecd_status": detail.get("oecd_status", "Unknown"),
        "conclusion": conclusion,
    }


def semantic_aop_context(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search AOP-Wiki-derived content as a semantic fallback for chemical queries.

    This is intentionally deterministic rather than embedding-based: it combines
    the curated chemical/stressor index with title/event/component text search so
    a known stressor such as rotenone does not produce an empty result just
    because OpenFoodTox has not been indexed yet.
    """
    results: list[dict[str, Any]] = []
    seen: set[int] = set()

    for match in find_aops_by_chemical(query):
        detail = get_aop_detail(match["aop_id"])
        if not detail or detail["id"] in seen:
            continue
        seen.add(detail["id"])
        results.append({
            "id": detail["id"],
            "title": detail.get("title"),
            "mie": detail.get("mie"),
            "ao": detail.get("ao"),
            "match_basis": "AOP-Wiki chemical/stressor index",
            "matched_stressor": match.get("stressor"),
        })
        if len(results) >= limit:
            return results

    for result in search_aops_text(query, limit=limit):
        if result["id"] in seen:
            continue
        seen.add(result["id"])
        item = dict(result)
        item["match_basis"] = "AOP-Wiki title/event/component semantic text search"
        results.append(item)
        if len(results) >= limit:
            break

    return results


def _candidate_assessment_aops(chemical: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    candidates = []
    seen = set()

    if chemical:
        for match in find_aops_by_chemical(chemical):
            if match["aop_id"] in seen:
                continue
            seen.add(match["aop_id"])
            candidates.append({"aop_id": match["aop_id"], "matched_by": "chemical/stressor index", "match": match})

    search_query = query or chemical
    if len(candidates) < limit and search_query:
        for result in search_aops_text(search_query, limit=limit):
            if result["id"] in seen:
                continue
            seen.add(result["id"])
            candidates.append({"aop_id": result["id"], "matched_by": "AOP/event text search", "match": result})

    return candidates[:limit]


def build_evidence_to_decision_assessment(body: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic evidence-to-decision assessment for regulatory triage."""
    chemical = str(body.get("chemical") or body.get("stressor") or "").strip()
    query = str(body.get("query") or chemical or "").strip()
    context = body.get("context") or {}
    available_data = body.get("available_data") or []

    if not chemical and not query:
        raise HTTPException(400, "chemical or query is required")
    if not isinstance(context, dict):
        raise HTTPException(400, "context must be an object")
    if not isinstance(available_data, list):
        raise HTTPException(400, "available_data must be a list")

    candidate_refs = _candidate_assessment_aops(chemical, query)
    if not candidate_refs:
        return {
            "chemical": chemical or query,
            "hazard_hypotheses": [],
            "confidence": {"overall": "very low"},
            "uncertainties": [{
                "type": "AOP coverage",
                "description": "No candidate AOPs were found in the local AOP-Wiki-derived database.",
                "impact": "The assessment cannot form an AOP-grounded hazard hypothesis for this query.",
            }],
            "critical_data_gaps": [{"priority": "high", "gap": "Identify relevant AOPs, key events, or NAM endpoints for the chemical/use scenario."}],
            "recommended_next_tests": [],
            "regulatory_summary": "No AOP-grounded regulatory conclusion can be made from the current database coverage.",
            "candidate_aops": [],
        }

    assessments = []
    for ref in candidate_refs:
        detail = get_aop_detail(ref["aop_id"])
        if not detail:
            continue
        mapped_data = _available_data_for_aop(available_data, detail)
        coverage = _event_data_coverage(detail, mapped_data)
        evidence_summary = _assessment_evidence_summary(detail)
        confidence = {
            "pathway": evidence_summary["pathway_confidence"],
            "chemical_specific": _infer_chemical_specific_confidence(mapped_data, ref["matched_by"]),
            "quantitative": evidence_summary["quantitative_confidence"],
            "exposure_context": _exposure_context_confidence(context),
        }
        confidence["overall"] = _overall_confidence(
            confidence["pathway"],
            confidence["chemical_specific"],
            confidence["quantitative"],
            confidence["exposure_context"],
        )
        uncertainties, gaps = _build_uncertainties_and_gaps(detail, confidence, coverage, context)
        recommendations = _recommend_next_tests(detail, coverage, gaps)
        assessments.append({
            "hazard_hypothesis": _hazard_hypothesis(detail, chemical or query, ref["matched_by"], confidence),
            "confidence": confidence,
            "evidence_summary": evidence_summary,
            "nam_coverage": coverage,
            "uncertainties": uncertainties,
            "critical_data_gaps": gaps,
            "recommended_next_tests": recommendations,
            "regulatory_conclusion": _regulatory_conclusion(confidence, gaps),
        })

    assessments.sort(key=lambda item: (
        {"high": 3, "moderate": 2, "low": 1, "very low": 0}.get(item["confidence"]["overall"], 0),
        item["evidence_summary"]["total_kers"],
    ), reverse=True)

    best = assessments[0] if assessments else None
    return {
        "chemical": chemical or query,
        "assessment_context": context,
        "hazard_hypotheses": [a["hazard_hypothesis"] for a in assessments],
        "confidence": best["confidence"] if best else {"overall": "very low"},
        "uncertainties": best["uncertainties"] if best else [],
        "critical_data_gaps": best["critical_data_gaps"] if best else [],
        "recommended_next_tests": best["recommended_next_tests"] if best else [],
        "regulatory_summary": best["regulatory_conclusion"] if best else "No assessment could be generated.",
        "candidate_aops": assessments,
    }



# ---------------------------------------------------------------------------
# Quantitative AOP / exposure-aware risk module
# ---------------------------------------------------------------------------

CONCENTRATION_FACTORS_TO_UM = {
    "um": 1.0,
    "µm": 1.0,
    "μm": 1.0,
    "micromolar": 1.0,
    "nm": 0.001,
    "nanomolar": 0.001,
    "mm": 1000.0,
    "millimolar": 1000.0,
    "pm": 0.000001,
    "picomolar": 0.000001,
}

DOSE_FACTORS_TO_MG_KG_DAY = {
    "mg/kg/day": 1.0,
    "mg/kg-d": 1.0,
    "mg/kg bw/day": 1.0,
    "ug/kg/day": 0.001,
    "µg/kg/day": 0.001,
    "μg/kg/day": 0.001,
    "ng/kg/day": 0.000001,
}

PREFERRED_POD_ORDER = {"bmc": 0, "bmcl": 0, "lec": 1, "ac50": 2, "ec50": 2, "ic50": 2, "loaec": 3}


def _normalize_unit(unit: Any) -> str:
    return str(unit or "").strip().lower().replace(" ", " ")


def _safe_float(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _convert_value(value: float, unit: str) -> tuple[Optional[float], Optional[str]]:
    """Normalize common concentration or administered-dose units for margin calculations."""
    normalized = _normalize_unit(unit).replace(" ", "")
    normalized = normalized.replace("μ", "µ")
    if normalized in CONCENTRATION_FACTORS_TO_UM:
        return value * CONCENTRATION_FACTORS_TO_UM[normalized], "uM"
    if normalized in DOSE_FACTORS_TO_MG_KG_DAY:
        return value * DOSE_FACTORS_TO_MG_KG_DAY[normalized], "mg/kg/day"
    if "plasmaequivalent" in normalized and normalized.startswith(("um", "µm")):
        return value, "uM"
    if "plasmaequivalent" in normalized and normalized.startswith("nm"):
        return value * 0.001, "uM"
    return None, None


def _event_lookup(detail: dict) -> dict[int, dict[str, Any]]:
    return {ev.get("event_id"): ev for ev in detail.get("events", []) if ev.get("event_id") is not None}


def _normalize_nam_result(record: dict[str, Any], event_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    pod_value = _safe_float(record.get("pod_value"))
    pod_unit = record.get("pod_unit")
    normalized_value, normalized_unit = (None, None)
    if pod_value is not None:
        normalized_value, normalized_unit = _convert_value(pod_value, pod_unit)

    mapped_event_id = _safe_int(record.get("mapped_event_id") or record.get("event_id"))
    event = event_by_id.get(mapped_event_id, {})
    return {
        "assay": record.get("assay") or record.get("endpoint") or "Unspecified NAM assay",
        "mapped_event_id": mapped_event_id,
        "mapped_event_name": event.get("event_name"),
        "mapped_event_type": event.get("event_type"),
        "pod_type": str(record.get("pod_type") or "POD").upper(),
        "pod_value": pod_value,
        "pod_unit": pod_unit,
        "normalized_pod_value": normalized_value,
        "normalized_pod_unit": normalized_unit,
        "ivive": record.get("ivive") or {},
        "raw": record,
    }


def _apply_ivive_if_available(nam: dict[str, Any]) -> dict[str, Any]:
    """Apply a simple user-supplied IVIVE conversion factor when provided.

    Expected shape: {"conversion_factor": 10, "output_unit": "mg/kg/day"}; the
    converted POD equals normalized_pod_value * conversion_factor. More complex
    toxicokinetic models should be run upstream and submitted as converted PODs.
    """
    ivive = nam.get("ivive") or {}
    factor = _safe_float(ivive.get("conversion_factor"))
    output_unit = ivive.get("output_unit")
    if factor is None or not output_unit or nam.get("normalized_pod_value") is None:
        return nam
    nam = dict(nam)
    nam["ivive_pod_value"] = nam["normalized_pod_value"] * factor
    nam["ivive_pod_unit"] = output_unit
    return nam


def _normalize_exposure(exposure: dict[str, Any]) -> dict[str, Any]:
    value = _safe_float(exposure.get("value")) if isinstance(exposure, dict) else None
    unit = exposure.get("unit") if isinstance(exposure, dict) else None
    normalized_value, normalized_unit = (None, None)
    if value is not None:
        normalized_value, normalized_unit = _convert_value(value, unit)
    return {
        "value": value,
        "unit": unit,
        "normalized_value": normalized_value,
        "normalized_unit": normalized_unit,
    }


def _margin_for_nam(nam: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
    exposure_value = exposure.get("normalized_value")
    exposure_unit = exposure.get("normalized_unit")
    pod_value = nam.get("ivive_pod_value", nam.get("normalized_pod_value"))
    pod_unit = nam.get("ivive_pod_unit", nam.get("normalized_pod_unit"))

    comparable = bool(pod_value is not None and exposure_value and pod_unit == exposure_unit)
    if not comparable:
        return {"comparable": False, "reason": "POD and exposure units are missing or not directly comparable."}

    ber = pod_value / exposure_value
    return {
        "comparable": True,
        "assay": nam.get("assay"),
        "mapped_event_id": nam.get("mapped_event_id"),
        "mapped_event_name": nam.get("mapped_event_name"),
        "mapped_event_type": nam.get("mapped_event_type"),
        "pod_type": nam.get("pod_type"),
        "pod_value": pod_value,
        "pod_unit": pod_unit,
        "exposure_value": exposure_value,
        "exposure_unit": exposure_unit,
        "bioactivity_exposure_ratio": round(ber, 4),
        "margin_of_exposure": round(ber, 4),
        "hazard_quotient": round(1 / ber, 6) if ber else None,
    }


def _select_most_sensitive_ke(normalized_nams: list[dict[str, Any]]) -> dict[str, Any]:
    comparable_nams = [n for n in normalized_nams if n.get("normalized_pod_value") is not None]
    if not comparable_nams:
        return {}
    comparable_nams.sort(key=lambda n: (
        n.get("normalized_pod_unit") or "",
        n["normalized_pod_value"],
        PREFERRED_POD_ORDER.get(str(n.get("pod_type", "")).lower(), 99),
    ))
    best = comparable_nams[0]
    return {
        "assay": best.get("assay"),
        "mapped_event_id": best.get("mapped_event_id"),
        "mapped_event_name": best.get("mapped_event_name"),
        "mapped_event_type": best.get("mapped_event_type"),
        "pod_type": best.get("pod_type"),
        "pod_value": best.get("pod_value"),
        "pod_unit": best.get("pod_unit"),
        "normalized_pod_value": best.get("normalized_pod_value"),
        "normalized_pod_unit": best.get("normalized_pod_unit"),
    }


def _quantitative_confidence(normalized_nams: list[dict[str, Any]], comparable_margins: list[dict[str, Any]], detail: dict) -> str:
    mapped_event_ids = {n.get("mapped_event_id") for n in normalized_nams if n.get("mapped_event_id")}
    has_mie = any(
        ev.get("event_id") in mapped_event_ids and ev.get("event_type") == "MolecularInitiatingEvent"
        for ev in detail.get("events", [])
    )
    has_downstream = len(mapped_event_ids) >= 2
    if comparable_margins and has_mie and has_downstream:
        return "quantitative screening with pathway support"
    if comparable_margins:
        return "screening only"
    if normalized_nams:
        return "qualitative AOP support only"
    return "insufficient quantitative data"


def build_quantitative_assessment(body: dict[str, Any]) -> dict[str, Any]:
    chemical = str(body.get("chemical") or "").strip()
    aop_id = _safe_int(body.get("aop_id"))
    nam_results = body.get("nam_results") or []
    exposure = body.get("exposure") or {}

    if not chemical:
        raise HTTPException(400, "chemical is required")
    if not aop_id:
        raise HTTPException(400, "aop_id is required")
    if not isinstance(nam_results, list):
        raise HTTPException(400, "nam_results must be a list")
    if not isinstance(exposure, dict):
        raise HTTPException(400, "exposure must be an object")

    detail = get_aop_detail(aop_id)
    if not detail:
        raise HTTPException(404, f"AOP {aop_id} not found")

    event_by_id = _event_lookup(detail)
    normalized_nams = [_apply_ivive_if_available(_normalize_nam_result(r, event_by_id)) for r in nam_results if isinstance(r, dict)]
    normalized_exposure = _normalize_exposure(exposure)
    margins = [_margin_for_nam(nam, normalized_exposure) for nam in normalized_nams]
    comparable_margins = [m for m in margins if m.get("comparable")]
    most_sensitive_margin = min(comparable_margins, key=lambda m: m["bioactivity_exposure_ratio"], default=None)
    most_sensitive_ke = (
        {
            "assay": most_sensitive_margin.get("assay"),
            "mapped_event_id": most_sensitive_margin.get("mapped_event_id"),
            "mapped_event_name": most_sensitive_margin.get("mapped_event_name"),
            "mapped_event_type": most_sensitive_margin.get("mapped_event_type"),
            "pod_type": most_sensitive_margin.get("pod_type"),
            "normalized_pod_value": most_sensitive_margin.get("pod_value"),
            "normalized_pod_unit": most_sensitive_margin.get("pod_unit"),
        }
        if most_sensitive_margin else _select_most_sensitive_ke(normalized_nams)
    )

    uncertainties = []
    if normalized_exposure.get("normalized_value") is None:
        uncertainties.append("Exposure value/unit could not be normalized; provide exposure in uM, nM, mg/kg/day, or compatible plasma-equivalent units.")
    if any(n.get("normalized_pod_value") is None for n in normalized_nams):
        uncertainties.append("One or more NAM PODs could not be normalized; those assays were not used in margin calculations.")
    if not comparable_margins:
        uncertainties.append("No NAM POD and exposure estimate shared comparable normalized units, so no screening margin could be calculated.")
    if not any(n.get("mapped_event_name") for n in normalized_nams):
        uncertainties.append("No NAM result mapped to a known key event in the selected AOP.")
    if any(n.get("ivive") for n in normalized_nams) and not any(n.get("ivive_pod_value") for n in normalized_nams):
        uncertainties.append("IVIVE metadata were provided but no simple conversion_factor/output_unit pair could be applied.")

    ber = most_sensitive_margin.get("bioactivity_exposure_ratio") if most_sensitive_margin else None
    hq = most_sensitive_margin.get("hazard_quotient") if most_sensitive_margin else None
    if ber is None:
        interpretation = "Quantitative readiness is limited to qualitative AOP support because comparable POD and exposure units were not available."
    elif ber >= 100:
        interpretation = "Screening margin is large (BER ≥ 100), suggesting lower near-term priority if exposure estimates are fit for purpose."
    elif ber >= 10:
        interpretation = "Screening margin is moderate (BER 10–100); retain for prioritization and refine exposure/IVIVE assumptions."
    elif ber >= 1:
        interpretation = "Screening margin is narrow (BER 1–10); prioritize for refined assessment or additional NAM confirmation."
    else:
        interpretation = "Exposure exceeds the most sensitive NAM POD (BER < 1); high priority for follow-up and uncertainty review."

    return {
        "chemical": chemical,
        "aop_id": detail["id"],
        "aop_title": detail.get("title"),
        "most_sensitive_ke": most_sensitive_ke,
        "bioactivity_exposure_ratio": ber,
        "margin_of_exposure": ber,
        "hazard_quotient": hq,
        "quantitative_confidence": _quantitative_confidence(normalized_nams, comparable_margins, detail),

        "validation_status": "prototype_screening_calculator",
        "regulatory_readiness": "screening/prioritization only; not a stand-alone regulatory conclusion",
        "data_provenance": {
            "aop_structure": "local AOP-Wiki-derived database",
            "nam_pods": "user supplied unless connected to curated source",
            "exposure": "user supplied unless connected to curated source",
            "ivive": "user supplied simple conversion factor when provided",
            "thresholds": "heuristic screening bands; not validated regulatory thresholds",
        },
        "interpretation": interpretation,
        "uncertainties": uncertainties,
        "normalized_exposure": normalized_exposure,
        "normalized_nam_results": normalized_nams,
        "margins": margins,
    }


# ---------------------------------------------------------------------------
# OpenFoodTox / IUCLID integration
# ---------------------------------------------------------------------------

OPENFOODTOX_IUCLID_BASE_URL = os.getenv("OPENFOODTOX_IUCLID_BASE_URL", "").rstrip("/")
OPENFOODTOX_IUCLID_USERNAME = os.getenv("OPENFOODTOX_IUCLID_USERNAME", "")
OPENFOODTOX_IUCLID_PASSWORD = os.getenv("OPENFOODTOX_IUCLID_PASSWORD", "")
OPENFOODTOX_SUBSTANCES_PATH = os.getenv("OPENFOODTOX_SUBSTANCES_PATH", "/api/substances")
OPENFOODTOX_DOSSIERS_PATH = os.getenv("OPENFOODTOX_DOSSIERS_PATH", "/api/dossiers")
OPENFOODTOX_DOCUMENTS_PATH_TEMPLATE = os.getenv("OPENFOODTOX_DOCUMENTS_PATH_TEMPLATE", "/api/dossiers/{dossier_uuid}/documents")
OPENFOODTOX_SQLITE_PATH = Path(os.getenv("OPENFOODTOX_SQLITE_PATH", str(DATA_DIR / "openfoodtox.db")))


def _openfoodtox_configured() -> bool:
    return bool(OPENFOODTOX_IUCLID_BASE_URL)


def _openfoodtox_sqlite_available() -> bool:
    return OPENFOODTOX_SQLITE_PATH.exists()


def openfoodtox_status() -> dict[str, Any]:
    """Return integration status without exposing credentials."""
    sqlite_available = _openfoodtox_sqlite_available()
    configured = _openfoodtox_configured() or sqlite_available
    mode = "local_iuclid_public_rest_api" if _openfoodtox_configured() else ("local_sqlite_export" if sqlite_available else "not_configured")
    return {
        "configured": configured,
        "mode": mode,
        "base_url_configured": bool(OPENFOODTOX_IUCLID_BASE_URL),
        "auth_configured": bool(OPENFOODTOX_IUCLID_USERNAME or OPENFOODTOX_IUCLID_PASSWORD),
        "sqlite_path": str(OPENFOODTOX_SQLITE_PATH),
        "sqlite_available": sqlite_available,
        "substances_path": OPENFOODTOX_SUBSTANCES_PATH,
        "dossiers_path": OPENFOODTOX_DOSSIERS_PATH,
        "documents_path_template": OPENFOODTOX_DOCUMENTS_PATH_TEMPLATE,
        "source_note": "OpenFoodTox 3.0 is EFSA chemical hazards data distributed as Excel and IUCLID 6 i6z dossier archives; KEvidence can query either a local IUCLID import or a local SQLite index built from the Excel/CSV export.",
        "license_note": "EFSA/Zenodo metadata should be retained with attribution; do not imply EFSA endorsement of KEvidence outputs.",
        "setup_steps": [
            "Regular client path: download the official EFSA/Zenodo OpenFoodTox Excel export.",
            "Run: python scripts/import_openfoodtox.py --download-latest --db data/openfoodtox.db",
            "Restart KEvidence; the OpenFoodTox tab will use local SQLite mode automatically.",
            "Institutional path: alternatively import official .i6z dossiers into IUCLID 6 and set OPENFOODTOX_IUCLID_BASE_URL.",
        ],
    }


def _openfoodtox_auth() -> tuple[str, str] | None:
    if OPENFOODTOX_IUCLID_USERNAME or OPENFOODTOX_IUCLID_PASSWORD:
        return (OPENFOODTOX_IUCLID_USERNAME, OPENFOODTOX_IUCLID_PASSWORD)
    return None


def _join_iuclid_url(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{OPENFOODTOX_IUCLID_BASE_URL}{path}"


def _items_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "content", "data", "substances", "dossiers", "documents"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    embedded = payload.get("_embedded")
    if isinstance(embedded, dict):
        for value in embedded.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return [payload]


def _first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _normalize_iuclid_substance(item: dict[str, Any]) -> dict[str, Any]:
    identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), dict) else {}
    return {
        "uuid": _first_present(item, ["uuid", "id", "key", "documentKey"]),
        "name": _first_present(item, ["name", "substanceName", "iupacName", "title", "publicName"]),
        "cas": _first_present(item, ["cas", "casNumber", "CAS number"]) or identifiers.get("cas") or identifiers.get("casNumber"),
        "ec": _first_present(item, ["ec", "ecNumber", "EC number"]) or identifiers.get("ec") or identifiers.get("ecNumber"),
        "synonyms": item.get("synonyms") if isinstance(item.get("synonyms"), list) else [],
        "raw": item,
    }


def _normalize_iuclid_record(item: dict[str, Any]) -> dict[str, Any]:
    title = _first_present(item, ["title", "name", "endpoint", "section", "documentType", "template", "uuid"])
    url = _first_present(item, ["url", "sourceUrl", "href"])
    links = item.get("links") or item.get("_links")
    if not url and isinstance(links, dict):
        self_link = links.get("self")
        if isinstance(self_link, dict):
            url = self_link.get("href")
        elif isinstance(self_link, str):
            url = self_link
    return {
        "uuid": _first_present(item, ["uuid", "id", "key", "documentKey"]),
        "title": title,
        "section": _first_present(item, ["section", "sectionName", "endpoint", "documentType", "template"]),
        "value": _first_present(item, ["value", "result", "referenceValue", "doseDescriptor", "effectLevel"]),
        "unit": _first_present(item, ["unit", "valueUnit", "doseUnit"]),
        "url": url,
        "raw": item,
    }


async def _iuclid_get(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
    response = await client.get(_join_iuclid_url(path), params=params or {})
    response.raise_for_status()
    return response.json()


def _row_has_any(row: dict[str, Any], needles: tuple[str, ...]) -> bool:
    haystack = " ".join([str(k) for k in row.keys()] + [str(v) for v in row.values()]).lower()
    return any(needle in haystack for needle in needles)


def _row_value_for(row: dict[str, Any], needles: tuple[str, ...]) -> Any:
    for key, value in row.items():
        key_l = str(key).lower()
        if any(needle in key_l for needle in needles) and value not in (None, ""):
            return value
    return None


def _normalize_local_openfoodtox_row(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uuid": _row_value_for(row, ("uuid", "iuclid", "id")),
        "name": _row_value_for(row, ("substance name", "substance", "name", "compound")),
        "cas": _row_value_for(row, ("cas",)),
        "ec": _row_value_for(row, ("ec number", "einecs", "ec no", "ec")),
        "title": _row_value_for(row, ("title", "efsa output", "opinion", "endpoint", "reference value")),
        "section": table_name,
        "value": _row_value_for(row, ("reference value", "value", "noael", "loael", "bmd", "adi", "tdi", "arfd")),
        "unit": _row_value_for(row, ("unit",)),
        "url": _row_value_for(row, ("url", "doi", "link")),
        "raw": row,
    }


def query_openfoodtox_sqlite(query: str, limit: int) -> dict[str, Any]:
    pattern = f"%{query.lower()}%"
    conn = sqlite3.connect(str(OPENFOODTOX_SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name, row_json FROM oft_rows WHERE row_text LIKE ? LIMIT ?",
        (pattern, max(limit * 20, 100)),
    )
    rows = cur.fetchall()
    metadata = {}
    try:
        cur.execute("SELECT key, value FROM oft_metadata")
        metadata = {r["key"]: r["value"] for r in cur.fetchall()}
    except sqlite3.Error:
        metadata = {}
    conn.close()

    substances = []
    toxicological_values = []
    publications = []
    seen_substances = set()
    tox_needles = ("toxic", "reference value", "reference point", "endpoint", "study", "noael", "loael", "bmd", "adi", "tdi", "arfd", "dose")
    publication_needles = ("publication", "efsa output", "opinion", "journal", "doi", "url", "link", "reference")

    for db_row in rows:
        row = json.loads(db_row["row_json"])
        table_name = db_row["table_name"]
        normalized = _normalize_local_openfoodtox_row(table_name, row)
        normalized["source_table"] = table_name
        normalized["source_mode"] = "local_sqlite_export"

        substance_key = (normalized.get("name"), normalized.get("cas"), normalized.get("ec"))
        if _row_has_any(row, ("substance", "cas", "ec number", "compound")) and substance_key not in seen_substances:
            substances.append(normalized)
            seen_substances.add(substance_key)

        if _row_has_any(row, tox_needles) or _row_has_any({"table": table_name}, tox_needles):
            toxicological_values.append(normalized)

        if _row_has_any(row, publication_needles) or _row_has_any({"table": table_name}, publication_needles):
            publications.append(normalized)

    related_aops = semantic_aop_context(query, limit=5)
    summary = f"Found {len(substances[:limit])} candidate substance record(s), {len(toxicological_values[:limit])} toxicological value/study record(s), and {len(publications[:limit])} publication/link record(s) in the local OpenFoodTox SQLite index."
    if not rows and related_aops:
        summary += f" No local OpenFoodTox rows matched, but KEvidence found {len(related_aops)} related AOP-Wiki pathway(s) for this query."
    return {
        "query": query,
        "configured": True,
        "status": openfoodtox_status(),
        "source_mode": "local_sqlite_export",
        "metadata": metadata,
        "substances": substances[:limit],
        "dossiers": [],
        "toxicological_values": toxicological_values[:limit],
        "publications": publications[:limit],
        "related_aops": related_aops,
        "summary": summary,
    }


async def query_openfoodtox(body: dict[str, Any]) -> dict[str, Any]:
    """Query EFSA OpenFoodTox dossiers imported into a local IUCLID 6 instance.

    The exact IUCLID endpoint paths can vary by deployment/version, so paths are
    configurable with environment variables. When the integration is not
    configured, return actionable setup guidance rather than pretending data were
    queried.
    """
    query = str(body.get("query") or body.get("q") or "").strip()
    limit = min(max(_safe_int(body.get("limit")) or 10, 1), 25)
    include_documents = bool(body.get("include_documents", True))
    include_dossiers = bool(body.get("include_dossiers", True))

    if not query:
        raise HTTPException(400, "query is required")

    status = openfoodtox_status()
    if not _openfoodtox_configured() and _openfoodtox_sqlite_available():
        return query_openfoodtox_sqlite(query, limit)
    if not status["configured"]:
        related_aops = semantic_aop_context(query, limit=5)
        summary = "OpenFoodTox content is not indexed yet. Zenodo provides a REST API to retrieve/download the OpenFoodTox files, and KEvidence can use scripts/import_openfoodtox.py --download-latest --db data/openfoodtox.db to download and index them locally."
        if related_aops:
            summary += f" Meanwhile, KEvidence found {len(related_aops)} related AOP-Wiki pathway(s) for this query, so the chemical does not lead to an empty result."
        return {
            "query": query,
            "configured": False,
            "status": status,
            "substances": [],
            "toxicological_values": [],
            "publications": [],
            "related_aops": related_aops,
            "summary": summary,
        }

    params = {"q": query, "search": query, "limit": limit, "include": "identifiers,synonyms,dossiers"}
    auth = _openfoodtox_auth()
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
        try:
            substance_payload = await _iuclid_get(client, OPENFOODTOX_SUBSTANCES_PATH, params=params)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, f"IUCLID substance query failed: {exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"IUCLID substance query failed: {exc}") from exc

        substances = [_normalize_iuclid_substance(item) for item in _items_from_payload(substance_payload)[:limit]]
        dossiers: list[dict[str, Any]] = []
        documents: list[dict[str, Any]] = []

        if include_dossiers:
            for substance in substances[:5]:
                uuid = substance.get("uuid")
                if not uuid:
                    continue
                try:
                    dossier_payload = await _iuclid_get(client, OPENFOODTOX_DOSSIERS_PATH, params={"substance": uuid, "q": query, "limit": 10})
                    for item in _items_from_payload(dossier_payload)[:10]:
                        record = _normalize_iuclid_record(item)
                        record["substance_uuid"] = uuid
                        dossiers.append(record)
                except httpx.HTTPError:
                    continue

        if include_documents:
            for dossier in dossiers[:5]:
                dossier_uuid = dossier.get("uuid")
                if not dossier_uuid:
                    continue
                path = OPENFOODTOX_DOCUMENTS_PATH_TEMPLATE.format(dossier_uuid=dossier_uuid)
                for section, bucket in (("toxicological_information", "tox"), ("literature_references", "pub")):
                    try:
                        doc_payload = await _iuclid_get(client, path, params={"section": section, "q": query, "limit": 25})
                    except httpx.HTTPError:
                        continue
                    for item in _items_from_payload(doc_payload)[:25]:
                        record = _normalize_iuclid_record(item)
                        record["dossier_uuid"] = dossier_uuid
                        record["record_group"] = bucket
                        documents.append(record)

    toxicological_values = [d for d in documents if d.get("record_group") == "tox"]
    publications = [d for d in documents if d.get("record_group") == "pub" or d.get("url")]
    related_aops = semantic_aop_context(query, limit=5)
    return {
        "query": query,
        "configured": True,
        "status": status,
        "source_mode": "local_iuclid_public_rest_api",
        "substances": substances,
        "dossiers": dossiers,
        "toxicological_values": toxicological_values,
        "publications": publications,
        "related_aops": related_aops,
        "summary": f"Found {len(substances)} candidate substance record(s), {len(toxicological_values)} toxicological value/study record(s), and {len(publications)} publication/link record(s) from the configured local IUCLID integration.",
    }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "aops": len(get_all_aops())}


@app.get("/api/aops")
async def list_aops(search: Optional[str] = None, limit: int = 100):
    if search:
        # AOP discovery needs chemical/stressor lookup as well as title/event text
        # search. Chemicals such as rotenone may appear as prototypical stressors
        # rather than in an AOP title or key-event name, so text-only search can
        # incorrectly return no results.
        results = []
        seen_ids = set()

        for match in find_aops_by_chemical(search):
            detail = get_aop_detail(match["aop_id"])
            if not detail or detail["id"] in seen_ids:
                continue
            seen_ids.add(detail["id"])
            results.append({
                "id": detail["id"],
                "title": detail.get("title", match.get("aop_title", "")),
                "mie": detail.get("mie"),
                "ao": detail.get("ao"),
                "match_basis": "chemical/stressor index",
                "matched_stressor": match.get("stressor"),
            })

        for result in search_aops_text(search, limit):
            if result["id"] in seen_ids:
                continue
            result = dict(result)
            result["match_basis"] = "AOP/event text search"
            seen_ids.add(result["id"])
            results.append(result)
            if len(results) >= limit:
                break

        return {"results": results[:limit], "count": len(results[:limit])}
    aops = get_all_aops()
    return {"results": aops[:limit], "count": len(aops)}


@app.get("/api/aops/{aop_id}")
async def get_aop(aop_id: int):
    detail = get_aop_detail(aop_id)
    if not detail:
        raise HTTPException(404, f"AOP {aop_id} not found")
    # Enrich with computed fields
    detail["evidence_summary"] = {}
    for ker in detail.get("kers", []):
        ev = ker.get("evidence")
        if ev:
            label = evidence_label(ev)
            detail["evidence_summary"][label] = detail["evidence_summary"].get(label, 0) + 1
    return detail


@app.post("/api/chat")
async def chat(body: dict):
    """Main chat endpoint — accepts user query, returns LLM answer grounded in AOP data."""
    query = body.get("message", "").strip()
    if not query:
        raise HTTPException(400, "message is required")

    workbench_context = body.get("context") if isinstance(body.get("context"), dict) else {}
    selected_aop_id = _safe_int(
        workbench_context.get("selected_aop_id")
        or workbench_context.get("aop_id")
        or body.get("selected_aop_id")
        or body.get("aop_id")
    )
    context_lines = []
    chemical_context = str(workbench_context.get("chemical") or "").strip()
    if chemical_context:
        context_lines.append(f"Current chemical/stressor: {chemical_context}")
    if workbench_context.get("use_case"):
        context_lines.append(f"Assessment use case: {workbench_context.get('use_case')}")
    if workbench_context.get("route"):
        context_lines.append(f"Exposure route/context: {workbench_context.get('route')}")
    if workbench_context.get("population"):
        context_lines.append(f"Population/species: {workbench_context.get('population')}")

    # HARD FUNNEL step 1: Build context from the explicit workbench selection first.
    # The workflow UI may ask short prompts such as "Explain AOP". Those prompts
    # are only meaningful together with the selected chemical/AOP state, so use the
    # structured state rather than relying on the free-text prompt to rediscover it.
    context = ""
    selected_detail = get_aop_detail(selected_aop_id) if selected_aop_id else None
    if selected_detail:
        context = _format_aop_detail(selected_detail, include_all_kers=True, include_all_events=True)
        context_lines.append(f"Selected AOP: AOP {selected_detail['id']} - {selected_detail.get('title', '')}")
    else:
        # If the workbench has a chemical but no selected AOP yet, search the
        # chemical/stressor directly before blending it with the user's prompt.
        # This preserves cases such as rotenone, where the useful lookup term is
        # the workflow chemical rather than the short assistant prompt text.
        if chemical_context:
            context = build_context_for_query(chemical_context)
        if not context:
            context_query_parts = [query, chemical_context]
            if selected_aop_id:
                context_query_parts.append(f"AOP {selected_aop_id}")
            # HARD FUNNEL step 1 fallback: Build context from the query plus any
            # chemical context available from the workbench.
            context = build_context_for_query(" ".join(part for part in context_query_parts if part))
    aop_count = len(get_all_aops())

    # HARD FUNNEL step 2: Extract meaningful search terms from user query
    search_terms = set(re.findall(r"[a-zA-Z]{4,}", f"{query} {chemical_context}".lower()))
    stopwords_chat = {"what", "does", "that", "this", "with", "have", "from", "they", "them",
                      "when", "where", "will", "would", "could", "should", "about", "there",
                      "their", "your", "which", "peach", "bits", "apple", "seed", "food",
                      "tell", "show", "find", "list", "give", "know", "need", "want",
                      "associated", "related", "involve", "involves", "involving",
                      "cause", "caused", "causes", "causing", "lead", "leads", "leading",
                      "affect", "affects", "affected", "called", "known", "also",
                      "some", "any", "many", "much", "most", "more", "very", "just",
                      "look", "like", "used", "using", "help", "still", "even",
                      "thing", "things", "really", "actually", "basically", "usually",
                      "another", "other", "every", "each", "both", "than", "then","else",
                      "after", "before", "first", "last", "next", "able", "sure","possible"}
    meaningful_terms = [t for t in search_terms if t not in stopwords_chat]

    # HARD FUNNEL step 3: If no context yet, try each meaningful term individually
    if not context:
        for t in meaningful_terms:
            context = build_context_for_query(t)
            if context:
                break

    # HARD FUNNEL step 4: RELEVANCE CHECK — verify found AOP data actually
    # relates to what the user asked about
    if context and meaningful_terms and not selected_detail and not chemical_context:
        # Extract AOP IDs from the context
        found_aop_ids = set(re.findall(r"AOP (\d+)", context))
        if found_aop_ids:
            conn_rel = sqlite3.connect(str(DB_PATH))
            cur_rel = conn_rel.cursor()
            context_relevant = False
            for tid in found_aop_ids:
                for term in meaningful_terms:
                    # Check title + events with WORD BOUNDARY
                    cur_rel.execute(
                        "SELECT 1 FROM aops WHERE id = ? AND "
                        "(LOWER(title) = ? OR LOWER(title) LIKE ? OR LOWER(title) LIKE ?) "
                        "UNION SELECT 1 FROM events WHERE aop_id = ? AND "
                        "(LOWER(event_name) = ? OR LOWER(event_name) LIKE ? OR LOWER(event_name) LIKE ?) "
                        "LIMIT 1",
                        (tid, term, f"{term} %", f"% {term}",
                         tid, term, f"{term} %", f"% {term}"),
                    )
                    if cur_rel.fetchone():
                        context_relevant = True
                        break
                    # Also check scraped text (chemical names live in abstract, not events)
                    fpath = AOP_CACHE_DIR / f"aop_{tid}.txt"
                    if fpath.exists():
                        text = fpath.read_text().lower()
                        if term in text:
                            context_relevant = True
                            break
                if context_relevant:
                    break
            conn_rel.close()

            if not context_relevant:
                # Context found but unrelated to query — discard
                context = ""

    # HARD FUNNEL step 5: QUERY DECOMPOSITION — ask the LLM to suggest AOP-relevant
    # entities the query might relate to, then VERIFY each against the database.
    # This enables "peach pits → amygdalin → cyanide → AOP"-type reasoning
    # WITHOUT letting the LLM fabricate AOP data.
    if not context:
        decomposition_result = _decompose_with_verification(query, aop_count)
        if decomposition_result:
            return decomposition_result

    if not context:
        return {
            "answer": "I couldn't find any matching AOPs in the OECD AOP-Wiki database for your query. "
                      "KEvidence answers questions grounded in the AOP-Wiki. "
                      "Try asking about a specific chemical or adverse outcome — for example: "
                      "'What AOPs involve rotenone?', 'Weight of evidence for AOP 3', or 'AOPs for liver steatosis'.",
            "sources": [],
            "no_data": True,
        }

    system = SYSTEM_PROMPT.format(aop_count=aop_count)

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Here is relevant AOP data from the database:\n\n{context}\n\n---\n\nCurrent workbench context:\n{chr(10).join(context_lines) if context_lines else 'No structured workbench context supplied.'}\n\n---\n\nUser question: {query}",
        },
    ]

    try:
        resp = llm.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )
        answer = resp.choices[0].message.content
    except Exception as e:
        return {"answer": f"I encountered an error querying the LLM: {str(e)}", "sources": []}

    # Extract AOP references from the answer for source citation
    refs = re.findall(r"AOP\s+(\d+)", answer)
    source_aops = []
    for rid in refs[:5]:
        detail = get_aop_detail(int(rid))
        if detail:
            source_aops.append({"id": detail["id"], "title": detail["title"]})

    return {"answer": answer, "sources": source_aops}


@app.get("/api/openfoodtox/status")
async def api_openfoodtox_status():
    return openfoodtox_status()


@app.post("/api/openfoodtox/query")
async def api_openfoodtox_query(body: dict):
    return await query_openfoodtox(body)


@app.post("/api/assess")
async def evidence_to_decision_assessment(body: dict):
    """Evidence-to-decision assessment workspace.

    Builds structured regulatory risk-assessment outputs from AOP evidence:
    hazard hypotheses, confidence, uncertainty, data gaps, and targeted next
    NAM/data-generation recommendations.
    """
    return build_evidence_to_decision_assessment(body)


@app.post("/api/quantitative-assessment")
async def quantitative_assessment(body: dict):
    """Quantitative AOP / exposure-aware risk module.

    Compares NAM concentration-response points of departure with exposure
    estimates, applies simple user-supplied IVIVE factors when provided, and
    returns screening margins plus quantitative-readiness interpretation.
    """
    return build_quantitative_assessment(body)


@app.get("/api/woe")
async def weight_of_evidence(chemical: str, aop_id: Optional[int] = None):
    """Weight of Evidence endpoint.
    Given a chemical name, finds associated AOPs and returns structured WoE.
    Optionally filter by specific AOP ID.
    """
    aops = find_aops_by_chemical(chemical)
    if not aops:
        return {"chemical": chemical, "aops": [], "summary": "No AOPs found for this chemical."}

    if aop_id:
        aops = [a for a in aops if a["aop_id"] == aop_id]

    detailed_aops = []
    for aop_match in aops:
        detail = get_aop_detail(aop_match["aop_id"])
        if not detail:
            continue

        # Count evidence levels across KERs
        evidence_counts = {"High": 0, "Moderate": 0, "Low": 0, "Not Specified": 0}
        quant_counts = {"High": 0, "Moderate": 0, "Low": 0, "Not Specified": 0}
        ker_details = []
        for ker in detail.get("kers", []):
            ev_label = evidence_label(ker.get("evidence"))
            quant_label = evidence_label(ker.get("quantitative"))
            evidence_counts[ev_label] = evidence_counts.get(ev_label, 0) + 1
            quant_counts[quant_label] = quant_counts.get(quant_label, 0) + 1
            ker_details.append({
                "upstream_event_id": ker["upstream_event_id"],
                "downstream_event_id": ker["downstream_event_id"],
                "relationship_type": ker["rel_type"],
                "evidence": ev_label,
                "quantitative_understanding": quant_label,
            })

        # Build pathway string
        events = detail.get("events", [])
        pathway_events = []
        for ev in events:
            pathway_events.append({
                "event_id": ev["event_id"],
                "event_name": ev["event_name"],
                "event_type": ev["event_type"],
            })

        detailed_aops.append({
            "aop_id": detail["id"],
            "title": detail["title"],
            "mie": detail.get("mie", ""),
            "ao": detail.get("ao", ""),
            "oecd_status": detail.get("oecd_status", "Unknown"),
            "stressors": [s for s in aop_match.get("stressor", "").split(",") if s],
            "evidence_summary": evidence_counts,
            "quantitative_summary": quant_counts,
            "total_kers": len(ker_details),
            "ker_details": ker_details,
            "pathway_events": pathway_events,
        })

    return {
        "chemical": chemical,
        "aops": detailed_aops,
        "summary": f"Found {len(detailed_aops)} AOPs associated with '{chemical}'.",
    }


# Serve frontend
@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/{path:path}")
async def serve_static(path: str):
    file_path = STATIC_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3457)
