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
from typing import Optional

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

app = FastAPI(title="kevidence — AOP Regulatory Chatbot")
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
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "aops": len(get_all_aops())}


@app.get("/api/aops")
async def list_aops(search: Optional[str] = None, limit: int = 100):
    if search:
        results = search_aops_text(search, limit)
        return {"results": results, "count": len(results)}
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

    # HARD FUNNEL step 1: Build context from the query
    context = build_context_for_query(query)
    aop_count = len(get_all_aops())

    # HARD FUNNEL step 2: Extract meaningful search terms from user query
    search_terms = set(re.findall(r"[a-zA-Z]{4,}", query.lower()))
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
    if context and meaningful_terms:
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
            "content": f"Here is relevant AOP data from the database:\n\n{context}\n\n---\n\nUser question: {query}",
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
