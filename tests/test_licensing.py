"""Licensing guards: KEvidence is AGPL-3.0 and offers its source; only CC BY-SA AOP-Wiki content is bundled or shown."""

import gzip
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KEVIDENCE_HOME", str(ROOT))


def test_license_is_agpl_and_ui_links_source():
    assert (ROOT / "LICENSE").read_text().lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    html = (ROOT / "static" / "index.html").read_text()
    assert re.search(r'<footer[\s\S]*Source code[\s\S]*CC BY-SA 4\.0[\s\S]*</footer>', html)


def test_bundled_aopwiki_export_is_by_sa_only():
    xml = gzip.decompress((DATA / "aop-wiki-xml.gz").read_bytes()).decode()
    licences = set(re.findall(r"<wiki-license>([^<]*)</wiki-license>", xml))
    assert licences == {"BY-SA"}
    assert xml.count("<aop id=") == len(re.findall(r"<wiki-license>", xml))


def test_removed_aops_are_absent_everywhere():
    record = json.loads((DATA / "aopwiki_licence_filter.json").read_text())
    removed = {r["wiki_id"] for r in record["removed_aops"]}
    assert removed and all(r["licence"] != "BY-SA" for r in record["removed_aops"])
    for tsv in ("aop_ke_mie_ao.tsv", "aop_ke_ker.tsv", "aop_ke_ec.tsv"):
        ids = {int(m) for m in re.findall(r"^Aop:(\d+)\t", (DATA / tsv).read_text(), re.M)}
        assert not ids & removed, tsv
    assert not {int(p.stem[4:]) for p in (DATA / "aops").glob("aop_*.txt")} & removed


def test_server_excludes_non_by_sa_and_tags_db():
    import server
    assert server.AOPWIKI_EXCLUDED_IDS == set()
    with sqlite3.connect(str(server.DB_PATH)) as c:
        assert c.execute("SELECT value FROM meta WHERE key='data_tag'").fetchone()[0] == server.DB_DATA_TAG
        removed = [r["wiki_id"] for r in json.loads((DATA / "aopwiki_licence_filter.json").read_text())["removed_aops"]]
        q = f"SELECT COUNT(*) FROM aops WHERE id IN ({','.join('?' * len(removed))})"
        assert c.execute(q, removed).fetchone()[0] == 0


def test_filter_script_on_a_fresh_export(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from filter_aopwiki_licences import filter_export
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<data xmlns="http://www.aopkb.org/aop-xml">
  <key-event id="ke-shared">
  </key-event>
  <key-event id="ke-only-arr">
  </key-event>
  <aop id="a1">
    <title>Open AOP</title>
    <status>
      <wiki-license>BY-SA</wiki-license>
    </status>
    <key-event key-event-id="ke-shared"/>
  </aop>
  <aop id="a2">
    <title>Closed AOP</title>
    <status>
      <wiki-license>All rights reserved</wiki-license>
    </status>
    <key-event key-event-id="ke-shared"/>
    <key-event key-event-id="ke-only-arr"/>
  </aop>
  <vendor-specific id="v" name="AopWiki" version="test">
    <aop-reference id="a1" aop-wiki-id="1"/>
    <aop-reference id="a2" aop-wiki-id="2"/>
    <key-event-reference id="ke-only-arr" aop-wiki-id="9"/>
  </vendor-specific>
</data>
"""
    (tmp_path / "aops").mkdir()
    (tmp_path / "aops" / "aop_2.txt").write_text("closed")
    (tmp_path / "aop-wiki-xml.gz").write_bytes(gzip.compress(xml.encode()))
    for tsv in ("aop_ke_mie_ao.tsv", "aop_ke_ker.tsv", "aop_ke_ec.tsv"):
        (tmp_path / tsv).write_text("Aop:1\tEvent:1\tx\n" "Aop:2\tEvent:2\tx\n")
    rec = filter_export(tmp_path)
    out = gzip.decompress((tmp_path / "aop-wiki-xml.gz").read_bytes()).decode()
    assert [r["wiki_id"] for r in rec["removed_aops"]] == [2]
    assert 'id="a2"' not in out and "ke-only-arr" not in out and 'id="ke-shared"' in out and 'id="a1"' in out
    assert (tmp_path / "aop_ke_ker.tsv").read_text() == "Aop:1\tEvent:1\tx\n"
    assert not (tmp_path / "aops" / "aop_2.txt").exists()
