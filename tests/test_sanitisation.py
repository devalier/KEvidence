"""Tests for the sanitisation step (Transparency Regulation, EFSA practical arrangements).

Grounding: every rule quotes the bundled EFSA decision verbatim on the page it cites, and every anchor is found.
Behaviour: personal data are proposed and selected, the applicant and reference-list authors are not, Annex items
are proposed but not selected, AI findings are accepted only if they name an applicable rule and exist on the page,
and the output PDF no longer contains the masked text, metadata, comments or mailto links.
"""

import base64
import json
import os
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("KEVIDENCE_HOME", str(ROOT))

import characterisation as c  # noqa: E402
import sanitisation as s  # noqa: E402
from make_sanitisation_demo import APPLICANT, APPLICANT_ADDRESS, build_demo_pdf  # noqa: E402

SAMPLE = ROOT / "static" / "samples" / "sanitisation_demo_study_report.pdf"


@pytest.fixture(scope="module")
def rules():
    return s.load_rules()


@pytest.fixture(scope="module")
def demo():
    return build_demo_pdf()


def _compact(text):
    return c._compact(c._fix_ligatures(text))[0]


def _propose(rules, demo, **kw):
    kw.setdefault("applicant", APPLICANT)
    kw.setdefault("applicant_address", APPLICANT_ADDRESS)
    kw.setdefault("previews", False)
    return s.propose(demo, rules, "c", **kw)


def _texts(result, **filters):
    return [p["text"] for p in result["proposals"] if all(p.get(k) == v for k, v in filters.items())]


# --- Grounding ---------------------------------------------------------------

def test_bundled_decision_is_the_practical_arrangements(rules):
    g = rules["catalogue"]["guidance"]
    assert len(rules["pages"]) == g["expected_pages"]
    assert _compact(g["title_check_phrase"]) in _compact(" ".join(rules["pages"]))


def test_every_rule_is_anchored_and_verbatim_on_cited_page(rules):
    anchors = c.anchor_requirements(rules["catalogue"], rules["pages"])
    assert not {rid: a["anchors_missing"] for rid, a in anchors.items() if a["status"] != "anchored_in_guidance_text"}
    problems = []
    for entry in rules["catalogue"]["entries"]:
        page = _compact(rules["pages"][entry["guidance_page"] - 1])
        for part in entry["quote"].split("[...]"):
            if part.strip() and _compact(part.strip(" .")) not in page:
                problems.append((entry["id"], entry["guidance_page"], part[:60]))
    assert not problems


def test_annex_items_follow_the_sector_lists(rules):
    feed = {e["id"] for e in s.rules_for_sector(rules, "c")}
    assert {"PA-ANX-FEED-18-3-A-EFFICACY-PLAN", "PA-ANX-FEED-18-3-B-IMPURITY-SPECS", "PA-ANX-39-2-D-QUANT-COMPOSITION",
            "PA-ANX-39E-1-PERSONAL-DATA", "PA-ANX-39E-2-TESTING-PERSONNEL"} <= feed
    assert not any("GMO" in i or "PPP" in i for i in feed)
    # The GMO list (Annex b) has no quantitative-composition item.
    assert "PA-ANX-39-2-D-QUANT-COMPOSITION" not in {e["id"] for e in s.rules_for_sector(rules, "b")}
    with pytest.raises(s.SanitisationError):
        s.rules_for_sector(rules, "z")


def test_rules_status_reports_all_anchored(rules):
    st = s.rules_status(rules, "c")
    assert st["guidance_text_loaded"] and not st["broken"]
    assert st["verification_counts"] == {"anchored_in_guidance_text": len(rules["catalogue"]["entries"])}


# --- Proposals ---------------------------------------------------------------

def test_personal_data_proposed_and_selected(rules, demo):
    r = _propose(rules, demo)
    selected = _texts(r, selected=True)
    for t in ("Dr. Jane Exampleton", "Dr. Paul Specimen", "Anna Testwoman", "jane.exampleton@fictional-lab.example", "+49 30 1234 5678"):
        assert t in selected, t
    assert any(p["category"] == "signature" and p["selected"] for p in r["proposals"])
    # GLP study with animals: study personnel fall under Art. 39e(2).
    assert next(p for p in r["proposals"] if p["text"] == "Anna Testwoman")["rule_id"] == s.TESTING_RULE


def test_exceptions_applicant_and_published_authors_not_proposed(rules, demo):
    r = _propose(rules, demo)
    joined = " ".join(p["text"] for p in r["proposals"])
    assert "Exemple" not in joined and "Demo Feed Additives" not in joined
    assert "Smith" not in joined and "Rossi" not in joined
    assert r["notes"]["skipped_exceptions"]["applicant"] >= 1
    assert r["notes"]["reference_pages"] == [3]


def test_annex_items_proposed_but_not_selected(rules, demo):
    r = _propose(rules, demo)
    cues = {p["rule_id"]: p for p in r["proposals"] if p["category"] == "cue"}
    assert {"PA-ANX-39-2-A-PROCESS", "PA-ANX-39-2-D-QUANT-COMPOSITION", "PA-ANX-39-2-C-SOURCING"} <= set(cues)
    assert not any(p["selected"] for p in cues.values())
    # Whole sentence, across the line break.
    assert cues["PA-ANX-39-2-A-PROCESS"]["text"].endswith("30 mbar.") and len(cues["PA-ANX-39-2-A-PROCESS"]["rects"]) == 2


def test_request_items_are_located_and_selected(rules, demo):
    r = _propose(rules, demo, requests_raw="recrystallisation from ethanol at 45 °C for 6 hours | Art. 39(2)(a) GFL\nnot in the document at all")
    req = next(p for p in r["proposals"] if "request" in p["sources"])
    assert req["selected"] and req["rule_id"] == "PA-ANX-39-2-A-PROCESS"
    assert [u["text"] for u in r["unlocated_requests"]] == ["not in the document at all"]


def test_ai_findings_are_validated(rules, demo):
    def fake(system, user):
        assert "PA-ANX-39E-2-TESTING-PERSONNEL" in system and "Page 2" in user
        return json.dumps({"findings": [
            {"page": 2, "text": "Fictional Chemicals Ltd", "rule_id": "PA-ANX-39-2-C-SOURCING", "reason": "supplier", "confidence": "high"},
            {"page": 2, "text": "vanillin 99.6 % w/w, silicon dioxide 0.4 % w/w", "rule_id": "PA-ANX-39-2-D-QUANT-COMPOSITION",
             "reason": "composition", "safety_relevant": True},
            {"page": 1, "text": "Dr. Jane Exampleton", "rule_id": "PA-ANX-39E-2-TESTING-PERSONNEL", "reason": "study director"},
            {"page": 1, "text": "Someone Invented", "rule_id": "PA-ANX-39E-1-PERSONAL-DATA", "reason": "hallucinated"},
            {"page": 1, "text": "Ross 308", "rule_id": "PA-ANX-PPP-63-2-D-COMPLETE-COMPOSITION", "reason": "wrong sector"},
            {"page": 1, "text": "Demo Feed Additives S.A.", "rule_id": "PA-ANX-39E-1-PERSONAL-DATA", "reason": "applicant"},
        ]})
    r = _propose(rules, demo, complete=fake)
    ai = r["ai"]
    assert ai["used"] and ai["accepted"] == 3
    assert ai["rejected"]["not_on_page"] == 1 and ai["rejected"]["unknown_rule"] == 1 and ai["rejected"]["exception"] == 1
    supplier = next(p for p in r["proposals"] if p["text"] == "Fictional Chemicals Ltd")
    assert supplier["sources"] == ["ai"] and not supplier["selected"]
    comp = next(p for p in r["proposals"] if p["text"].startswith("vanillin 99.6"))
    assert "safety_relevant" in comp["flags"] and not comp["selected"]
    jane = next(p for p in r["proposals"] if p["text"] == "Dr. Jane Exampleton")
    assert set(jane["sources"]) == {"rule", "ai"} and jane["selected"]


def test_ai_led_review_applies_both_redaction_types_by_the_rules(rules, demo):
    """Personal data is masked; confidential information only when claimed and not relevant to safety (Art. 9(4), 16(3) PA)."""
    seen = {}

    def fake(system, user):
        seen["system"], seen["user"] = system, user
        return json.dumps({"findings": [
            {"page": 1, "text": "Anna Testwoman", "type": "personal_data", "rule_id": "PA-ANX-39E-2-TESTING-PERSONNEL",
             "reason": "QA manager, Art. 39e(2)", "confidence": "high"},
            {"page": 2, "text": "recrystallisation from ethanol at 45 °C for 6 hours", "type": "confidential_information",
             "rule_id": "PA-ANX-39-2-A-PROCESS", "claim": "R1", "reason": "process, Art. 39(2)(a)"},
            {"page": 2, "text": "Fictional Chemicals Ltd", "type": "confidential_information", "rule_id": "PA-ANX-39-2-B-COMMERCIAL-LINKS",
             "claim": None, "reason": "supplier, not claimed"},
            {"page": 2, "text": "vanillin 99.6 % w/w, silicon dioxide 0.4 % w/w", "type": "confidential_information",
             "rule_id": "PA-ANX-39-2-D-QUANT-COMPOSITION", "claim": "R2", "safety_relevant": True, "reason": "needed for exposure"},
            {"page": 2, "text": "12 %", "type": "confidential_information", "rule_id": "REQUEST", "claim": None, "reason": "no claim"},
        ]})
    r = _propose(rules, demo, complete=fake,
                 requests_raw="process conditions of the recrystallisation step | Art. 39(2)(a) GFL\nquantitative composition")
    assert "PERSONAL DATA" in seen["system"] and "CONFIDENTIAL INFORMATION" in seen["system"]
    assert "Claimed items are not disclosed pending the decision" in seen["system"]  # Art. 16(3), verbatim block
    assert "R1: process conditions" in seen["user"] and "R2: quantitative composition" in seen["user"]
    ai = r["ai"]
    assert ai["mode"] == "ai-led" and ai["by_type"] == {"personal_data": 1, "confidential_information": 3}
    assert ai["rejected"]["unknown_rule"] == 1  # REQUEST without a claim
    by = {p["text"]: p for p in r["proposals"]}
    assert by["Anna Testwoman"]["selected"] and by["Anna Testwoman"]["redaction_type"] == "personal_data"
    process = by["recrystallisation from ethanol at 45 °C for 6 hours"]
    assert process["selected"] and process["group"] == "request" and process["redaction_type"] == "confidential_information"
    assert not by["Fictional Chemicals Ltd"]["selected"] and "stays public" in by["Fictional Chemicals Ltd"]["reason"]
    comp = by["vanillin 99.6 % w/w, silicon dioxide 0.4 % w/w"]
    assert not comp["selected"] and "safety_relevant" in comp["flags"]
    assert r["unlocated_requests"] == []  # both claims were located by the AI
    # The AI's precise span replaces the rule-based whole sentence around it (Art. 10(a) PA).
    assert not any(p["category"] == "cue" and "recrystallisation" in p["text"] for p in r["proposals"])
    # Rule findings the AI did not confirm are flagged for a closer look, not dropped.
    assert any("not_confirmed_by_ai" in p["flags"] for p in r["proposals"])
    assert not any("Rule-based fallback" in w for w in r["warnings"])


def test_rules_only_fallback_carries_the_ai_recommendation(rules, demo):
    r = _propose(rules, demo)
    assert r["ai"]["mode"] == "rules-only"
    assert any(w.startswith("Rule-based fallback only") and "sovereign, domain-specific language model" in w for w in r["warnings"])
    assert r["ai"]["recommendation"] == s.AI_RECOMMENDATION


def test_ai_failure_is_reported_not_fatal(rules, demo):
    r = _propose(rules, demo, complete=lambda system, user: "not json")
    assert not r["ai"]["used"] and r["ai"]["errors"]
    assert _texts(r, selected=True)


def test_previews_and_view_rects(rules, demo):
    r = _propose(rules, demo, previews=True)
    assert len(r["previews"]) == 3 and r["previews"][0]["image"].startswith("data:image/jpeg;base64,")
    assert all(p["view_rects"] for p in r["proposals"])


def test_rejects_non_pdf_and_encrypted(rules):
    with pytest.raises(s.SanitisationError):
        s.propose(b"hello", rules, "c")
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret")
    enc = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(s.SanitisationError, match="password"):
        s.propose(enc, rules, "c")


# --- Applying ----------------------------------------------------------------

def test_apply_removes_text_and_identifying_data(rules, demo):
    r = _propose(rules, demo)
    chosen = [p for p in r["proposals"] if p["selected"] or p["category"] == "cue"]
    out, report = s.apply(demo, chosen, label_boxes=True)
    assert report["verification"]["passed"], report
    doc = pymupdf.open(stream=out, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    for gone in ("Exampleton", "Specimen", "Testwoman", "1234 5678", "guaiacol", "market share", "99.6"):
        assert gone not in text, gone
    # Kept: applicant, published authors, results, labels with the legal basis.
    for kept in (APPLICANT, "Smith J, Jones K", "No treatment-related effects", "Art. 39e(2) GFL"):
        assert kept in text, kept
    assert not doc.metadata["author"] and not doc.metadata["creator"]
    assert sum(1 for p in doc for _ in p.annots()) == 0
    assert not any(link.get("uri", "").startswith("mailto:") for p in doc for link in p.get_links())
    assert report["annotations_removed"] == 1 and report["links_removed"] == 1
    # The signature image itself is altered, not just covered: no scribble pixel (20, 20, 120) is left in it.
    for img in doc[0].get_images(full=True):
        pix = pymupdf.Pixmap(doc, img[0])
        samples = pix.samples
        n = pix.n
        assert not any(samples[i:i + 3] == bytes((20, 20, 120)) for i in range(0, len(samples), n))


def test_verification_flags_unselected_copies(rules, demo):
    # Mask the e-mail only where it is a word, but it also survives in nothing else: craft a second copy.
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page().insert_text((50, 80), "Contact: John Doeman, john.doeman@example.org")
    pdf = doc.tobytes()
    r = s.propose(pdf, rules, "c", previews=False)
    first_page_only = [p for p in r["proposals"] if p["page"] == 1 and p["category"] == "email"]
    _, report = s.apply(pdf, first_page_only)
    v = report["verification"]
    assert v["passed"] and v["residual"] and v["residual"][0]["still_on_pages"] == [2]


def test_apply_rejects_bad_input(rules, demo):
    with pytest.raises(s.SanitisationError):
        s.apply(demo, [])
    with pytest.raises(s.SanitisationError):
        s.apply(demo, [{"page": 9, "rects": [[0, 0, 10, 10]]}])


def test_log_marks_itself_confidential(rules, demo):
    r = _propose(rules, demo)
    chosen = [p for p in r["proposals"] if p["selected"]]
    _, report = s.apply(demo, chosen)
    md = s.log_markdown("demo.pdf", r["sector"], chosen, report, rules)
    assert "CONFIDENTIAL" in md and "PASSED" in md and "Art. 39e(2) GFL" in md


def test_bundled_sample_matches_generator():
    assert SAMPLE.exists()
    a, b = pymupdf.open(SAMPLE), pymupdf.open(stream=build_demo_pdf(), filetype="pdf")
    assert [p.get_text() for p in a] == [p.get_text() for p in b]


# --- API ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server
    from conftest import sign_in
    c = TestClient(server.app)
    sign_in(c)
    return c


def test_api_rules_and_pdf(client):
    r = client.get("/api/sanitisation/rules?domain=feed")
    assert r.status_code == 200 and r.json()["sector"] == "c"
    assert any(e["applies"] for e in r.json()["entries"])
    assert client.get("/api/sanitisation/rules?sector=q").status_code == 400
    pdf = client.get("/api/sanitisation/rules.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get("/api/domains").json()["domains"][0]["transparency_sector"] == "c"


def test_api_analyse_and_apply_roundtrip(client, demo):
    files = {"file": ("report.pdf", demo, "application/pdf")}
    r = client.post("/api/sanitisation/analyse", files=files, data={"sector": "c", "applicant": APPLICANT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["selected"] > 0 and not body["ai"]["requested"]
    chosen = [p for p in body["proposals"] if p["selected"]]
    a = client.post("/api/sanitisation/apply", files={"file": ("report.pdf", demo, "application/pdf")},
                    data={"redactions": json.dumps(chosen), "sector": "c"})
    assert a.status_code == 200, a.text
    out = a.json()
    assert out["filename"] == "report_sanitised.pdf" and out["report"]["verification"]["passed"]
    text = "".join(p.get_text() for p in pymupdf.open(stream=base64.b64decode(out["pdf_base64"]), filetype="pdf"))
    assert "Exampleton" not in text
    assert client.post("/api/sanitisation/analyse", files={"file": ("x.txt", b"plain text", "text/plain")}).status_code == 400


def test_api_chat_refuses_ungrounded_questions(client):
    r = client.post("/api/chat", json={"message": "Who won the football?", "context": {"workflow_step": "sanitisation"}})
    assert r.json().get("no_data")


def test_assistant_context_finds_the_personal_data_rule(rules):
    ctx, ids = c.domain_context_for_question("Can the names of the study director be published?", rules, step=s.STEP)
    assert "PA-ANX-39E-2-TESTING-PERSONNEL" in ids


def test_manual_text_is_located_everywhere(rules, demo):
    items = s.locate_text(demo, rules, "c", "DemoVan 99", "PA-ANX-39-2-C-SOURCING")
    assert {i["page"] for i in items} == {1} and all(i["selected"] and i["sources"] == ["manual"] for i in items)
    with pytest.raises(s.SanitisationError):
        s.locate_text(demo, rules, "c", "DemoVan 99", "PA-ANX-PPP-63-2-D-COMPLETE-COMPOSITION")


def test_api_locate(client, demo):
    r = client.post("/api/sanitisation/locate", files={"file": ("r.pdf", demo, "application/pdf")}, data={"text": "Ross 308", "sector": "c"})
    assert r.status_code == 200 and r.json()["proposals"][0]["page"] == 1


def test_request_items_are_grouped_as_requests_and_applicant_line_address_kept(rules, demo):
    r = s.propose(demo, rules, "c", applicant=APPLICANT, previews=False,
                  requests_raw="recrystallisation from ethanol at 45 °C for 6 hours | Art. 39(2)(a) GFL")
    assert r["summary"].get("request") == 1
    assert not any("Exemple" in p["text"] for p in r["proposals"])  # address on the applicant's line, no address given
