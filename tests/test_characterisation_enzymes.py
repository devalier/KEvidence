"""Tests for identity & characterisation of food enzymes (CEP 2021 guidance, EFSA Journal 2021;19(10):6851).

The first group guards grounding: every requirement quotes the guidance verbatim on the page it cites, every anchor phrase
is found in the bundled PDF, and the stored page numbers match the PDF (scripts/assign_guidance_pages.py --check).
The second group checks which requirements apply for each source and production-strain type, and the third runs the
demo food-enzyme dossier.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import characterisation as c  # noqa: E402

DEMO_ZIP = ROOT / "docs" / "demo" / "Demo_Synthetic_Dossier.zip"


@pytest.fixture(scope="module")
def bundle():
    return c.load_domain_bundle("food-enzymes")


@pytest.fixture(scope="module")
def catalogue(bundle):
    return bundle["primary"]["catalogue"]


@pytest.fixture(scope="module")
def pages(bundle):
    p = bundle["primary"]["pages"]
    assert p, "bundled food enzyme guidance PDF missing or unreadable"
    return p


def _compact(text):
    return c._compact(c._fix_ligatures(text))[0]


@pytest.fixture(scope="module")
def demo_docs():
    z = zipfile.ZipFile(DEMO_ZIP)
    names = [n for n in z.namelist() if n.endswith(".pdf") and "Suitability" not in n]
    return [c.extract_document(n, z.read(n), f"D{i}") for i, n in enumerate(names, start=1)]


# --- Grounding ---------------------------------------------------------------

def test_bundled_guidance_is_the_food_enzyme_guidance(catalogue, pages):
    assert _compact(catalogue["guidance"]["title_check_phrase"]) in _compact(" ".join(pages[:2]))
    assert catalogue["guidance"]["doi"] == "10.2903/j.efsa.2021.6851"


def test_every_quote_is_verbatim_on_cited_page(catalogue, pages):
    problems = []
    for req in catalogue["requirements"]:
        here = _compact(pages[req["guidance_page"] - 1] + (pages[req["guidance_page"]] if req["guidance_page"] < len(pages) else ""))
        if _compact(req["quote"]) not in here:
            problems.append((req["id"], req["guidance_page"], req["quote"][:60]))
    for principle in catalogue["guidance"]["general_principles"]:
        if _compact(principle["quote"]) not in _compact(pages[principle["page"] - 1]):
            problems.append(("general", principle["page"], principle["quote"][:60]))
    assert not problems


def test_every_anchor_is_found_in_guidance(catalogue, pages):
    anchors = c.anchor_requirements(catalogue, pages)
    missing = {k: v["anchors_missing"] for k, v in anchors.items() if v["status"] != "anchored_in_guidance_text"}
    assert not missing


def test_stored_pages_match_the_bundled_pdf():
    path = ROOT / "data" / "guidance" / "food-enzymes" / "cep_2021_6851_requirements.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "assign_guidance_pages.py"), str(path), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_catalogue_covers_every_part_a_section(catalogue):
    sections = {r["guidance_section"] for r in catalogue["requirements"]}
    for s in ("Part A", "1.1.7", "1.1.11", "1.2", "1.3.2", "1.3.3", "1.3.4.1", "1.3.4.2", "2.1", "2.3.3", "3.1", "3.3.3",
              "4.3", "4.4", "4.5", "5.1", "5.4"):
        assert s in sections, s
    assert {r["template_section"] for r in catalogue["requirements"]} == {t["token"] for t in catalogue["template_sections"]}


def test_supporting_sources_reuse_feed_pdfs(bundle):
    for src in bundle["sources"]:
        assert src["pdf_path"].exists(), src["pdf_path"]
        assert src["pages"]


# --- Applicability -----------------------------------------------------------

def _statuses(catalogue, meta, docs=None):
    doc = docs or [c.extract_document("empty.txt", b"Food enzyme dossier.", "D1")]
    res = c.analyse_dossier(doc, meta, catalogue)
    return {r["id"]: r for r in res["requirements"]}, res


def test_gm_non_qps_bacterium_needs_viable_cells_dna_and_amr(catalogue):
    r, _ = _statuses(catalogue, {"production_types": ["microbial"], "attributes": ["bacteria", "gm", "non_qps"]})
    assert r["FE-1.3.4.1-VIABLE"]["applicability"] == "yes"
    assert r["FE-1.3.4.2-DNA"]["applicability"] == "yes"
    assert r["FE-1.1.9-AMR"]["applicability"] == "yes"
    assert r["FE-1.1.11-GM"]["applicability"] == "yes"
    assert r["FE-1.1.10.1-QPS"]["status"] == "not_applicable"
    assert r["FE-1.1.10.2-NONQPS"]["applicability"] == "yes"
    assert all(r[k]["status"] == "not_applicable" for k in r if k.startswith(("FE-2.", "FE-3.")))


def test_non_gm_qps_strain_is_exempt_from_viable_cells_and_dna(catalogue):
    r, _ = _statuses(catalogue, {"production_types": ["microbial"], "attributes": ["filamentous_fungi", "non_gm", "qps"]})
    assert r["FE-1.3.4.1-VIABLE"]["status"] == "not_applicable"
    assert r["FE-1.3.4.2-DNA"]["status"] == "not_applicable"
    assert r["FE-1.1.9-AMR"]["status"] == "not_applicable"      # bacteria only
    assert r["FE-1.1.11-GM"]["status"] == "not_applicable"


def test_plant_enzyme_uses_section_2_only(catalogue):
    r, _ = _statuses(catalogue, {"production_types": ["plant"]})
    assert r["FE-2.1-SOURCE"]["applicability"] == "yes" and r["FE-2.3.3-PURITY"]["applicability"] == "yes"
    assert all(r[k]["status"] == "not_applicable" for k in r if k.startswith(("FE-1.", "FE-3.")))
    assert r["FE-4.5-ALLERGEN"]["applicability"] == "yes"


def test_unknown_source_keeps_requirements_to_confirm(catalogue):
    r, res = _statuses(catalogue, {})
    assert r["FE-1.1.7-IDENTITY"]["applicability"] == "unknown"
    assert any("Source of the enzyme not identified" in f["flag"] for f in res["scope_flags"])


# --- Demo dossier --------------------------------------------------------------

def test_demo_dossier_identity_is_detected_with_citations(catalogue, demo_docs):
    _, res = _statuses(catalogue, {}, demo_docs)
    det = res["detected"]["all"]
    assert det["ec_number"]["value"] == "3.2.1.1"
    assert det["enzyme_name"]["value"] == "alpha-amylase"
    assert det["organism"]["value"] == "Bacillus licheniformis"
    assert det["strain"]["value"].endswith("NZYM-KE")
    attrs = {a["value"] for a in det["attributes"]}
    assert {"bacteria", "bacillus", "gm", "qps"} <= attrs and "non_qps" not in attrs
    assert res["meta"]["production_types"] == ["microbial"]
    assert all(a["citation"] for a in det["attributes"])


def test_demo_dossier_gap_analysis(catalogue, demo_docs, bundle):
    r, res = _statuses(catalogue, {}, demo_docs)
    # A use-extension package: strain characterisation and absence of DNA are not in it.
    assert r["FE-1.3.4.2-DNA"]["status"] == "gap"
    assert r["FE-1.1.1-WGS"]["status"] in ("gap", "partial")
    assert r["FE-5.1-USE"]["status"] == "evidence_located"
    assert r["FE-5.4-EXPOSURE"]["status"] == "evidence_located"
    assert r["FE-1.1.10.1-QPS"]["applicability"] == "yes"
    md = c.render_markdown(res, catalogue, bundle["template"])
    for heading in ("# Food enzyme — alpha-amylase (EC 3.2.1.1)", "## 1. Source of the food enzyme", "## 5. Dietary exposure",
                    "EFSA Journal 2021;19(10):6851"):
        assert heading in md
    assert "FEEDAP" not in md
    assert "{{" not in md


def test_entered_values_override_detection(catalogue, demo_docs):
    r, res = _statuses(catalogue, {"production_types": ["microbial"], "attributes": ["bacteria", "non_gm", "qps"]}, demo_docs)
    assert r["FE-1.3.4.2-DNA"]["status"] == "not_applicable"
    assert "attributes" not in res["detected"]["inferred_and_used"]


def test_dossier_intake_characterises_food_enzyme_without_the_checklist(client):
    r = client.post("/api/dossier/intake", files=[("files", (DEMO_ZIP.name, DEMO_ZIP.read_bytes(), "application/zip"))])
    assert r.status_code == 200
    d = r.json()
    assert d["domain"]["id"] == "food-enzymes" and d["domain"]["grounded"]
    ch = d["characterisation"]
    assert ch["profile"] == "food_enzyme" and ch["domain"]["id"] == "food-enzymes"
    assert not any("Suitability" in doc["name"] for doc in ch["documents"])
    assert ch["markdown"].startswith("# Food enzyme")
