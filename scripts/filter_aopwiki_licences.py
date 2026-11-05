#!/usr/bin/env python3
"""Keep only AOP-Wiki content that may be redistributed (CC BY-SA).

The AOP-Wiki export tags every AOP with a licence (<wiki-license>): "BY-SA", "All rights reserved"
(reuse needs the authors' written permission) or "Open for adoption" (no licence granted). KEvidence
redistributes and displays the export, so only BY-SA AOPs are kept. The script removes the other AOPs
from the bundled XML, the three TSVs and the cached AOP texts, drops key events and relationships used
only by them, and records what was removed in data/aopwiki_licence_filter.json. It is idempotent: run it
again after replacing data/ with a fresh export.

    python scripts/filter_aopwiki_licences.py [--data data]
"""

import argparse
import gzip
import json
import re
from pathlib import Path

ALLOWED = {"BY-SA"}
AOP_RE = re.compile(r'^  <aop id="([^"]+)">\n.*?^  </aop>\n', re.M | re.S)
BLOCK_RE = r'^  <{tag} id="([^"]+)">\n.*?^  </{tag}>\n'


def aop_licences(xml: str) -> dict[str, dict]:
    """{aop uuid: {"licence", "wiki_id", "title"}} from the export."""
    wiki_ids = dict(re.findall(r'<aop-reference id="([^"]+)" aop-wiki-id="(\d+)"/>', xml))
    out = {}
    for m in AOP_RE.finditer(xml):
        body = m.group(0)
        lic = re.search(r"<wiki-license>([^<]*)</wiki-license>", body)
        title = re.search(r"<title>([^<]*)</title>", body)
        out[m.group(1)] = {"licence": lic.group(1).strip() if lic else "not stated",
                           "wiki_id": int(wiki_ids[m.group(1)]) if m.group(1) in wiki_ids else None,
                           "title": title.group(1) if title else ""}
    return out


def filter_export(data: Path) -> dict:
    xml_path = data / "aop-wiki-xml.gz"
    xml = gzip.decompress(xml_path.read_bytes()).decode("utf-8")
    lic = aop_licences(xml)
    removed = {u: v for u, v in lic.items() if v["licence"] not in ALLOWED}
    record_path = data / "aopwiki_licence_filter.json"
    previous = json.loads(record_path.read_text()) if record_path.exists() else {"removed_aops": []}

    kept_refs, removed_refs = set(), set()
    for m in AOP_RE.finditer(xml):
        refs = set(re.findall(r'(?:key-event-id|relationship id)="([^"]+)"', m.group(0)))
        (removed_refs if m.group(1) in removed else kept_refs).update(refs)
    orphan = removed_refs - kept_refs
    drop = set(removed) | orphan

    xml = AOP_RE.sub(lambda m: "" if m.group(1) in removed else m.group(0), xml)
    for tag in ("key-event", "key-event-relationship"):
        xml = re.sub(BLOCK_RE.format(tag=tag), lambda m: "" if m.group(1) in orphan else m.group(0), xml, flags=re.M | re.S)
    xml = re.sub(r'^\s*<[a-z-]+-reference id="([^"]+)"[^>]*/>\n', lambda m: "" if m.group(1) in drop else m.group(0), xml, flags=re.M)
    if removed or orphan:
        xml_path.write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))

    wiki_ids = {v["wiki_id"] for v in removed.values() if v["wiki_id"] is not None}
    wiki_ids |= {r["wiki_id"] for r in previous.get("removed_aops", []) if r.get("wiki_id") is not None}
    for tsv in ("aop_ke_mie_ao.tsv", "aop_ke_ker.tsv", "aop_ke_ec.tsv"):
        p = data / tsv
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        keep = [ln for ln in lines if not (m := re.match(r"Aop:(\d+)\t", ln)) or int(m.group(1)) not in wiki_ids]
        if len(keep) != len(lines):
            p.write_text("".join(keep), encoding="utf-8")
    for wid in wiki_ids:
        (data / "aops" / f"aop_{wid}.txt").unlink(missing_ok=True)

    version = re.search(r'<vendor-specific [^>]*version="([^"]+)"', xml)
    merged = {r["wiki_id"]: r for r in previous.get("removed_aops", [])}
    merged.update({v["wiki_id"]: {"wiki_id": v["wiki_id"], "licence": v["licence"], "title": v["title"]} for v in removed.values()})
    record = {
        "source": "AOP-Wiki XML export (https://aopwiki.org/downloads)",
        "export_version": version.group(1) if version else "unknown",
        "kept_licences": sorted(ALLOWED),
        "kept_aops": sum(1 for v in lic.values() if v["licence"] in ALLOWED),
        "removed_aops": sorted(merged.values(), key=lambda r: r["wiki_id"] or 0),
        "removed_orphan_key_events_and_relationships": len(orphan) + previous.get("removed_orphan_key_events_and_relationships", 0),
    }
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[1] / "data"))
    rec = filter_export(Path(ap.parse_args().data))
    print(f"Kept {rec['kept_aops']} BY-SA AOPs; removed {len(rec['removed_aops'])} AOPs "
          f"and {rec['removed_orphan_key_events_and_relationships']} key events/relationships used only by them.")
