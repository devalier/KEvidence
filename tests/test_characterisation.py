"""Tests for step 0 (feed additive characterisation).

The first group guards grounding: every requirement in the catalogue must quote
the FEEDAP (2017) guidance verbatim, on the page it cites, and every anchor
phrase must be found in the bundled guidance PDF. If the catalogue drifts from
the guidance, these tests fail.
"""

import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import characterisation as c  # noqa: E402

DEMO = ROOT / "static" / "samples" / "characterisation_demo_dossier.md"
DEMO_META = {
    "product_name": "DemoVan 99",
    "product_form": "solid",
    "routes": ["premixture", "feed"],
    "production_types": ["chemical_synthesis"],
    "additive_type": "flavouring_compound",
    "components": [{"name": "vanillin", "cas": "121-33-5", "role": "Active substance"}],
}


@pytest.fixture(scope="module")
def catalogue():
    return c.load_catalogue()


@pytest.fixture(scope="module")
def guidance_pages():
    pages = c.load_guidance_pages()
    assert pages, "bundled guidance PDF missing or unreadable"
    return pages


def _compact(text):
    return c._compact(c._fix_ligatures(text))[0]


def _demo(meta=None, catalogue=None, pages=None):
    doc = c.extract_document(DEMO.name, DEMO.read_bytes(), "D1")
    return c.analyse_dossier([doc], meta or DEMO_META, catalogue, pages)


def _by_id(result, req_id):
    for res in result["requirements"]:
        if res["id"] == req_id:
            return res
    for comp in result["components"]:
        for res in comp["requirements"]:
            if res["id"] == req_id:
                return res
    raise KeyError(req_id)


# --- Grounding ---------------------------------------------------------------

def test_bundled_guidance_is_the_feedap_identity_guidance(catalogue, guidance_pages):
    assert len(guidance_pages) == 12
    text = _compact(" ".join(guidance_pages))
    assert _compact(catalogue["guidance"]["title_check_phrase"]) in text
    assert _compact("doi: 10.2903/j.efsa.2017.5023") in text


def test_every_anchor_is_found_in_guidance(catalogue, guidance_pages):
    anchors = c.anchor_requirements(catalogue, guidance_pages)
    not_anchored = {rid: a.get("anchors_missing") for rid, a in anchors.items() if a["status"] != "anchored_in_guidance_text"}
    assert not not_anchored


def test_every_quote_is_verbatim_on_cited_page(catalogue, guidance_pages):
    problems = []
    for req in catalogue["requirements"]:
        page = _compact(guidance_pages[req["guidance_page"] - 1])
        for part in req["quote"].split("[...]"):
            if part.strip() and _compact(part.strip(" .")) not in page:
                problems.append((req["id"], req["guidance_page"], part[:60]))
    for principle in catalogue["guidance"]["general_principles"]:
        if _compact(principle["quote"]) not in _compact(guidance_pages[principle["page"] - 1]):
            problems.append(("general", principle["page"], principle["quote"][:60]))
    assert not problems


def test_cited_sections_exist_in_guidance(catalogue, guidance_pages):
    toc = _compact(guidance_pages[2])  # table of contents
    for req in catalogue["requirements"]:
        assert _compact(req["guidance_section"] + ".") in toc or _compact(req["guidance_section"]) in toc, req["id"]


def test_catalogue_rejects_requirement_without_quote(tmp_path, catalogue):
    import json
    broken = json.loads(json.dumps(catalogue))
    broken["requirements"][0]["quote"] = ""
    path = tmp_path / "cat.json"
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError):
        c.load_catalogue(path)


# --- Identifiers ---------------------------------------------------------------

@pytest.mark.parametrize("cas,ok", [("121-33-5", True), ("7732-18-5", True), ("61-90-5", True), ("121-33-4", False), ("12-3", False)])
def test_cas_checksum(cas, ok):
    assert c.cas_checksum_ok(cas) is ok


@pytest.mark.parametrize("ec,ok", [("204-465-2", True), ("231-791-2", True), ("204-465-3", False)])
def test_ec_checksum(ec, ok):
    assert c.ec_checksum_ok(ec) is ok


# --- Analysis of the fictional demo dossier ------------------------------------------

def test_demo_identity_extraction(catalogue):
    result = _demo(catalogue=catalogue)
    ident = result["components"][0]["identity"]
    assert ident["cas"]["value"] == "121-33-5"
    assert ident["ec"]["value"] == "204-465-2"
    assert ident["molecular_formula"]["value"] == "C8H8O3"
    assert ident["molecular_weight"]["value"].startswith("152.15")
    assert ident["iupac_name"]["value"].startswith("4-hydroxy-3-methoxybenzaldehyde")
    assert ident["cas"]["citation"] == "D1 p.1"
    assert result["components"][0]["cas_check"] == "CAS check digit valid"


def test_demo_batch_minimum_and_compliance_flag(catalogue):
    spec = _by_id(_demo(catalogue=catalogue), "G2.1.3-SPEC")
    assert spec["status"] == "partial"
    assert spec["batch_check"]["required_min"] == 5
    assert spec["batch_check"]["detected"] == 3
    assert set(spec["batch_check"]["batch_ids"]) >= {"DV2501", "DV2502", "DV2503"}
    assert any("statements of compliance alone" in f["message"] for f in spec["flags"])


def test_demo_gaps_and_exemptions(catalogue):
    result = _demo(catalogue=catalogue)
    assert _by_id(result, "G2.5.2.1-USER")["status"] == "gap"  # no safety data sheet
    gen = _by_id(result, "G2.1.4-GEN")
    assert any(m.startswith("Residual solvents") for m in gen["missing"])
    # Flavouring compounds: no stability-in-feed or homogeneity studies required (§2.4.1.2, §2.4.2)
    assert _by_id(result, "G2.4.1.2-FEED")["status"] == "not_applicable"
    assert _by_id(result, "G2.4.1.2-PREMIX")["status"] == "not_applicable"
    assert _by_id(result, "G2.4.2-HOMOG")["status"] == "not_applicable"
    assert _by_id(result, "G2.1.5-LIQUID")["status"] == "not_applicable"
    # Chemical synthesis: residual synthesis chemicals were reported
    assert _by_id(result, "G2.1.4-MIN")["status"] == "evidence_located"
    assert _by_id(result, "G2.4.1.1-SHELF")["status"] == "evidence_located"


def test_unknown_product_attributes_give_conditional_status(catalogue):
    meta = {"components": DEMO_META["components"]}
    result = _demo(meta, catalogue)
    assert _by_id(result, "G2.1.4-MIN")["status"] == "conditional"
    assert any("Production type not entered" in m for m in _by_id(result, "G2.1.4-MIN")["missing"])


def test_fermentation_adds_fermentation_impurity_requirements(catalogue):
    meta = dict(DEMO_META, production_types=["fermentation"])
    res = _by_id(_demo(meta, catalogue), "G2.1.4-MIN")
    labels = {s["label"] for s in res["sub_items"]}
    assert "Extent of spent growth medium in the final product" in labels
    assert "Absence of the production organism (viable cells)" in labels
    assert res["status"] in ("partial", "gap")


def test_markdown_follows_guidance_structure(catalogue, guidance_pages):
    md = _demo(catalogue=catalogue, pages=guidance_pages)["markdown"]
    assert "{{" not in md
    for heading in ("## 2.1 Identity of the additive", "## 2.2 Characterisation of the active substance(s)",
                    "## 2.3 Manufacturing process", "## 2.4 Physical–chemical and technological properties",
                    "## 2.5 Conditions of use", "## 2.6 Methods of analysis", "## Data-gap analysis against the guidance"):
        assert heading in md
    assert "anchored in guidance text (p.5)" in md
    assert "EFSA Journal 2017;15(10):5023" in md


# --- Durations, subsamples ---------------------------------------------------------

def test_premixture_duration_below_minimum(catalogue):
    text = ("Stability in premixture: the additive was tested in a premixture containing trace elements "
            "(composition given in Annex 2). Recovery after 3 months at 25 °C was 98 %.").encode()
    doc = c.extract_document("stab.txt", text, "D1")
    meta = {"product_form": "solid", "routes": ["premixture"], "production_types": ["chemical_synthesis"], "additive_type": "none_of_these"}
    res = _by_id(c.analyse_dossier([doc], meta, catalogue), "G2.4.1.2-PREMIX")
    assert res["status"] == "partial"
    assert any(ch["met"] is False and "6 months" in ch["label"] for ch in res["checks"])


def test_water_stability_48h(catalogue):
    text = b"Stability in water for drinking at the recommended inclusion level was tested at 25 \xc2\xb0C for 48 h."
    doc = c.extract_document("w.txt", text, "D1")
    res = _by_id(c.analyse_dossier([doc], {"routes": ["water"]}, catalogue), "G2.4.1.3-WATER")
    assert res["status"] == "evidence_located"
    assert any(ch["met"] is True for ch in res["checks"])


# --- Document ingestion ---------------------------------------------------------

def _docx(paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_extraction():
    doc = c.extract_document("spec.docx", _docx(["Certificate of analysis", "Batch No: A123", "Assay: 99.1 %"]), "D1")
    assert doc.kind == "docx"
    assert "Batch No: A123" in doc.pages[0]
    assert doc.doc_type == "Certificate of analysis"


def test_pdf_extraction_of_guidance(guidance_pages):
    assert "Identity of the additive" in c._fix_ligatures(guidance_pages[4])


def test_unsupported_file_is_reported():
    doc = c.extract_document("image.png", b"\x89PNG....", "D1")
    assert not doc.pages and doc.warnings


@pytest.mark.parametrize("url", ["http://127.0.0.1/x.pdf", "http://10.0.0.5/a", "file:///etc/passwd", "ftp://example.org/x", "http://localhost/x"])
def test_url_validation_blocks_non_public_targets(url):
    with pytest.raises(ValueError):
        c.validate_url(url)


# --- LLM drafting guard and assistant grounding ----------------------------------------

def test_narrative_flags_untraced_numbers(catalogue):
    result = _demo(catalogue=catalogue)

    def fake_llm(system, user):
        return '{"sections": {"S2_4": "Shelf life was 37 months."}}'

    narrative = c.draft_narrative(result, fake_llm)
    assert narrative["S2_4"]["grounded"] is False
    assert "37" in narrative["S2_4"]["untraced"]


def test_narrative_accepts_traced_numbers(catalogue):
    result = _demo(catalogue=catalogue)
    narrative = c.draft_narrative(result, lambda s, u: '{"sections": {"S2_4": "Three batches were stored at 25 °C for 24 months [D1 p.1]."}}')
    assert narrative["S2_4"]["grounded"] is True


def test_assistant_context_selects_relevant_requirements(catalogue, guidance_pages):
    ctx, ids = c.guidance_context_for_question("What does the guidance require for dusting potential?", catalogue, guidance_pages)
    assert "G2.1.5-SOLID" in ids
    assert "Stauber" in ctx
    ctx, ids = c.guidance_context_for_question("Explain section 2.4.2", catalogue, guidance_pages)
    assert ids[0] == "G2.4.2-HOMOG"


# --- Opinion-template layout (Table 1 / Table 2 / Appendix A) -------------------------------

def _rows_by_label(result):
    return {r["label"].lower(): r for r in result["opinion"]["all_rows"]}


def test_table1_values_follow_template_conventions(catalogue):
    result = _demo(catalogue=catalogue)
    rows = _rows_by_label(result)
    assay = rows["assay (hplc)"]
    assert assay["category"] == "batch_active"
    assert c.format_row_value(assay, average=True) == "99.8 (99.7–99.9) [3]"
    assert c.format_row_value(rows["loss on drying"], average=True) == "0.10 (0.09–0.12) [3]"
    assert rows["guaiacol"]["category"] == "substance_related"
    assert c.format_row_value(rows["glyoxylic acid"], average=False).startswith("<0.01")
    assert rows["lead"]["category"] == "other_impurities"            # Appendix A
    assert c.format_row_value(rows["lead"], average=False) == "<0.5 [3]"
    assert c.format_row_value(rows["dusting potential"], average=False) == "120–140 [3]"


def test_specifications_deduplicated_and_compliance_facts(catalogue):
    result = _demo(catalogue=catalogue)
    specs = result["opinion"]["specifications"]
    assert [(s["comparator"], s["value"]) for s in specs] == [("≥", 99.5), ("≤", 0.5)]
    facts = result["opinion"]["table1"]["compliance"]
    assert any(f.startswith("Assay (HPLC): 3/3") for f in facts)
    assert not any("Assay" in f and "≤ 0.5" in f for f in facts)


def test_opinion_section_rendered(catalogue):
    md = _demo(catalogue=catalogue)["markdown"]
    assert "## 1.1.1 Characterisation of the additive" in md
    assert "**Table 1:**" in md and "## Appendix A" in md
    assert "| Assay (HPLC) (%) | 99.8 (99.7–99.9) [3] | D1 p.1 |" in md
    assert "<: below the limit of quantification; -: not analysed." in md
    assert "[Scientific officer to conclude]" in md
    assert "[^b2b]: Batch-to-batch variation: D1" in md


def test_table2_one_column_per_preparation(catalogue):
    a = c.extract_document("a.txt", b"Product A 50%\nAppearance: beige powder\nAssay (%) | 50.1 | 50.4 | 49.8 | 50.0 | 50.2\n", "D1")
    b = c.extract_document("b.txt", b"Product B 10%\nAppearance: liquid\nAssay (%) | 10.2 | 10.1 | 9.9\nMethanol (mg/kg) | <10 | <10 | 12\n", "D2")
    meta = {"product_name": "X", "formulations": ["Product A 50%", "Product B 10%"], "components": [{"name": "X", "role": "Active substance"}]}
    result = c.analyse_dossier([a, b], meta, catalogue)
    op = result["opinion"]
    assert op["doc_formulation_map"] == {"D1": "Product A 50%", "D2": "Product B 10%"}
    assert op["table1"] is None
    md = result["markdown"]
    assert "**Table 2:**" in md
    assert "| Assay (%) | 50.1 (49.8–50.4) [5] | 10.1 (9.9–10.2) [3] |" in md
    assert "| Methanol (mg/kg) | - | <10–12 [3] |" in md


def test_fermentation_strain_paragraph_fields(catalogue):
    text = (b"The absence of viable cells of the production strain was tested in three batches analysed in triplicate "
            b"(1 gram per sample). No viable cells were detected.\n"
            b"DNA of the production strain was analysed by PCR in three batches in triplicate (1 g per sample); "
            b"primers targeted a 350 bp region; limit of detection 10 ng per gram of product. No DNA was detected.\n")
    doc = c.extract_document("strain.txt", text, "D1")
    result = c.analyse_dossier([doc], {"production_types": ["fermentation"]}, catalogue)
    ferm = result["opinion"]["fermentation"]
    assert ferm["viable_cells"]["replicates"] == "triplicate"
    assert ferm["viable_cells"]["sample_size"] == "1 gram per sample"
    assert ferm["dna"]["amplicon"] == "350 bp" and ferm["dna"]["lod"] == "10 ng per gram" and ferm["dna"]["method"] == "PCR"
    assert "Outside this chemical-characterisation MVP" in result["markdown"]


def test_local_template_override(tmp_path, catalogue):
    result = _demo(catalogue=catalogue)
    custom = tmp_path / "t.md"
    custom.write_text("<!-- note {{X}} -->\n# {{PRODUCT_NAME}}\n{{OPINION_111}}\n")
    md = c.render_markdown(result, catalogue, custom)
    assert md.startswith("# DemoVan 99") and "**Table 1:**" in md and "{{" not in md
