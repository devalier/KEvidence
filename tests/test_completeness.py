"""Intake: completeness check grounded in EFSA's feed administrative guidance (checklist) and the pre-submission
practical arrangements (study notifications), plus personal-data screening."""

import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import characterisation as c  # noqa: E402
import completeness as cm  # noqa: E402
from make_completeness_demo import build_demo_zip  # noqa: E402

DEMO_ZIP = ROOT / "static" / "samples" / "completeness_demo_dossier.zip"


@pytest.fixture(scope="module")
def rules():
    return cm.load_rules()


@pytest.fixture(scope="module")
def demo(rules):
    return cm.check_dossier([("demo.zip", build_demo_zip())], rules, domain="feed", application_type="new",
                            applicant="Demo Feed Additives S.A.", notified_study_ids=["STUDY-DEMO-0042", "STUDY-DEMO-0099"],
                            dossier_ref="FAD-DEMO-0001")


def _compact(t):
    return c._compact(c._fix_ligatures(t))[0]


def _failing(result, severity):
    return {r["title"] for r in result["results"] if r["status"] == "fail" and r["severity"] == severity}


# --- Grounding ---------------------------------------------------------------

@pytest.mark.parametrize("index", [0, 1])
def test_every_rule_is_anchored_and_verbatim_on_cited_page(rules, index):
    src = rules["sources"][index]
    g = src["catalogue"]["guidance"]
    assert len(src["pages"]) == g["expected_pages"]
    assert _compact(g["title_check_phrase"]) in _compact(" ".join(src["pages"]))
    anchors = c.anchor_requirements(src["catalogue"], src["pages"])
    assert not {k: v["anchors_missing"] for k, v in anchors.items() if v["status"] != "anchored_in_guidance_text"}
    for e in src["catalogue"]["entries"]:
        page = _compact(src["pages"][e["guidance_page"] - 1])
        for part in e["quote"].split("[...]"):
            assert _compact(part.strip(" .")) in page, (e["id"], part[:50])


def test_every_check_in_the_code_cites_a_known_rule(demo, rules):
    assert {r["rule_id"] for r in demo["results"]} <= set(rules["by_id"])
    assert all(r["citation"]["quote"] for r in demo["results"])


# --- The demo dossier: every planted problem is found, nothing else fails -------------------

def test_demo_blocking_findings(demo):
    assert demo["verdict"] == "incomplete"
    assert _failing(demo, "blocking") == {
        "Completeness checklist", "Public summary free of confidential information", "Section IV: efficacy",
        "Study notification — Annex_III_1_tolerance_study.pdf", "All notified studies included, no unnotified studies"}


def test_demo_warnings(demo):
    assert _failing(demo, "warning") == {
        "Word-searchable, copyable PDF", "No special characters in file names", "Precise identification of the masked parts",
        "2.4 Physico-chemical and technological properties", "No personal data in non-confidential versions"}


def test_demo_justified_omissions_are_not_contagious(demo):
    justified = {r["title"] for r in demo["results"] if r["status"] == "justified"}
    assert justified == {"3.4 Safety for the environment", "5 Proposal for post-market monitoring"}


def test_demo_study_notifications(demo):
    by_file = {s["file"].rsplit("/", 1)[-1]: s for s in demo["studies"]}
    assert set(by_file) == {"Annex_III_1_tolerance_study.pdf", "Annex_III_2_genotoxicity_2019.pdf", "Annex_III_3_palatability_2022.pdf"}
    assert by_file["Annex_III_1_tolerance_study.pdf"]["status"] == "fail" and by_file["Annex_III_1_tolerance_study.pdf"]["start"] == "2023-03-14"
    assert by_file["Annex_III_2_genotoxicity_2019.pdf"]["status"] == "ok"  # before 27 March 2021
    assert by_file["Annex_III_3_palatability_2022.pdf"]["study_ids"] == ["STUDY-DEMO-0042"]


def test_demo_inventory_and_personal_data(demo):
    roles = {f["name"]: (f["part"], f["role"]) for f in demo["files"]}
    assert roles["EFSA_letter.pdf"] == ("administrative", "cover_letter")
    assert roles["ConfInfo.pdf"] == ("technical", "confinfo")
    assert roles["Sect_II_Identity_Conf.pdf"][0] == "confidential"
    flagged = {p["file"].rsplit("/", 1)[-1] for p in demo["personal_data"]}
    assert flagged == {"Annex_III_1_tolerance_study.pdf", "Annex_III_2_genotoxicity_2019.pdf"}  # Contact.pdf is not published


def test_letter_and_report(demo):
    letter = demo["letter_markdown"]
    assert "FAD-DEMO-0001" in letter and "Dear Demo Feed Additives S.A." in letter and "within 30 days" in letter
    assert "1. **Completeness checklist**" in letter and "STUDY-DEMO-0099" in letter
    assert "INCOMPLETE" in demo["report_markdown"] and "File inventory" in demo["report_markdown"]


def test_bundled_demo_matches_generator():
    a, b = zipfile.ZipFile(DEMO_ZIP), zipfile.ZipFile(io.BytesIO(build_demo_zip()))
    assert a.namelist() == b.namelist()


# --- Other domains, renewals ---------------------------------------------------------------

def test_other_domain_gets_generic_checks_only(rules):
    r = cm.check_dossier([("demo.zip", build_demo_zip())], rules, domain="food-enzymes", application_type="new")
    by_rule = {}
    for item in r["results"]:
        by_rule.setdefault(item["rule_id"], []).append(item["status"])
    assert by_rule["CC-ADMIN-DOCUMENTS"] == ["not_applicable"] and by_rule["CC-SECTION-IV"] == ["not_applicable"]
    assert "fail" in by_rule["CC-FORMAT-SEARCHABLE"] and "fail" in by_rule["PS-ART19-1-SCOPE"]
    assert by_rule["PA-ART10-A-PRECISE-SCOPE"] == ["fail"]  # transparency rule applies everywhere


def test_renewal_softens_missing_efficacy_and_asks_for_previous_authorisation(rules):
    r = cm.check_dossier([("demo.zip", build_demo_zip())], rules, domain="feed", application_type="renewal")
    iv = next(i for i in r["results"] if i["rule_id"] == "CC-SECTION-IV")
    assert iv["status"] == "fail" and iv["severity"] == "warning"
    assert next(i for i in r["results"] if i["rule_id"] == "CC-RENEWAL-PREVIOUS-AUTH")["status"] == "fail"


# --- Parsing and safety ---------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Study start date: 14 March 2023", date(2023, 3, 14)),
    ("Experimental start date: 2022-09-01", date(2022, 9, 1)),
    ("Study initiation date: 05.02.2019", date(2019, 2, 5)),
    ("Date of study initiation: March 3, 2021", date(2021, 3, 3)),
])
def test_study_start_dates(text, expected):
    assert cm.study_start_date(text)[0] == expected


def test_zip_paths_are_normalised_and_limits_enforced(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/evil.txt", "hello world")
        zf.writestr("__MACOSX/._x", "junk")
        zf.writestr(".DS_Store", "junk")
    files, _ = cm.read_upload([("d.zip", buf.getvalue())])
    assert [f.path for f in files] == ["etc/evil.txt"]
    monkeypatch.setattr(cm, "MAX_TOTAL_BYTES", 5)
    with pytest.raises(cm.CompletenessError, match="too large"):
        cm.read_upload([("d.zip", buf.getvalue())])
    with pytest.raises(cm.CompletenessError):
        cm.read_upload([("d.zip", b"PK\x03\x04 not a zip")])


def test_roles_recognised_from_content_when_names_are_not_conventional():
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "Public summary\nDemoVan 99 is a flavouring.")
    files, _ = cm.read_upload([("summary-v3-final.pdf", doc.tobytes())])
    assert files[0].role == "pubsum" and files[0].part == "technical"


# --- API ---------------------------------------------------------------------------------------

def test_api_check_file_and_rules(client):
    data = DEMO_ZIP.read_bytes()
    r = client.post("/api/completeness/check", files={"files": ("demo.zip", data, "application/zip")},
                    data={"domain": "feed", "application_type": "new", "notified_study_ids": "STUDY-DEMO-0042, STUDY-DEMO-0099"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "incomplete" and body["counts"]["blocking"] == 5
    path = next(f["path"] for f in body["files"] if f["name"] == "Annex_III_1_tolerance_study.pdf")
    f = client.post("/api/completeness/file", files={"files": ("demo.zip", data, "application/zip")}, data={"path": path})
    assert f.status_code == 200 and f.content[:5] == b"%PDF-"
    assert client.post("/api/completeness/file", files={"files": ("demo.zip", data, "application/zip")}, data={"path": "nope.pdf"}).status_code == 404
    assert client.post("/api/completeness/check", files={"files": ("demo.zip", data, "application/zip")},
                       data={"application_type": "bogus"}).status_code == 400
    sources = client.get("/api/completeness/rules").json()["sources"]
    assert all(not s["broken"] for s in sources) and len(sources) == 3
    events = [e["event"] for e in client.get("/api/activity").json()["events"]]
    assert "completeness.checked" in events


def test_assistant_refuses_unrelated_questions(client):
    r = client.post("/api/chat", json={"message": "Who won the football?", "context": {"workflow_step": "completeness"}}).json()
    assert r["no_data"]
