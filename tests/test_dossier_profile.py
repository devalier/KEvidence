"""Automatic entry path: form fields derived from the dossier, and the one-upload intake endpoint."""

import io
import zipfile
from pathlib import Path

import pytest

import characterisation as charmod
import completeness as compmod
import dossier_profile

ROOT = Path(__file__).resolve().parents[1]
FEED_ZIP = ROOT / "static/samples/completeness_demo_dossier.zip"
ENZYME_ZIP = ROOT / "docs/demo/Demo_Synthetic_Dossier.zip"
REGISTRY = charmod.load_domains()


def _profile(path, override=""):
    files, _ = compmod.read_upload([(path.name, path.read_bytes())])
    return dossier_profile.derive(files, REGISTRY, override)["fields"]


def _text_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_feed_demo_fields_are_derived_with_sources():
    f = _profile(FEED_ZIP)
    assert f["domain"]["value"] == "feed"
    assert f["application_type"]["value"] == "new"
    assert f["applicant"]["value"] == "Demo Feed Additives S.A."
    assert f["dossier_ref"]["value"] == "FAD-DEMO-0001"
    assert f["pre_application_ids"]["value"] == ["PAI-DEMO-0001"]
    assert f["substance"]["value"] == "DemoVan 99"
    assert f["population"]["value"] == "chickens for fattening"
    assert f["use_level"]["value"].startswith("Up to 125 mg/kg")
    assert f["routes"]["value"] == ["feed"]
    assert "1831/2003" in f["legal_context"]["value"]
    for key in ("domain", "applicant", "substance", "use_level"):
        assert f[key]["basis"] == "found" and f[key]["source"]["file"].startswith("FAD-DEMO-0001/")


@pytest.mark.skipif(not ENZYME_ZIP.exists(), reason="enzyme demo dossier not bundled")
def test_enzyme_demo_fields_are_derived():
    f = _profile(ENZYME_ZIP)
    assert f["domain"]["value"] == "food-enzymes"
    assert f["application_type"]["value"] == "modification"  # ticked box in the cover letter
    assert f["applicant"]["value"] == "Acme Enzymatic srl"
    assert f["substance"]["value"] == "Alpha-amylase"
    assert "Production of baked products" in f["matrix"]["value"] and "enzyme" not in f["matrix"]["value"]
    assert f["use_level"]["value"] is None  # a purity specification is not a use level
    assert f["pre_application_ids"]["value"] == []


def test_nothing_is_guessed_without_cues():
    files, _ = compmod.read_upload([("x.zip", _text_zip({"notes.txt": "Meeting notes about the weather."}))])
    p = dossier_profile.derive(files, REGISTRY)
    f = p["fields"]
    assert f["domain"]["value"] is None and f["domain"]["basis"] == "not_found"
    assert f["applicant"]["value"] is None and f["substance"]["value"] is None
    assert "notified_study_ids" in p["not_derivable"]


def test_domain_override_wins():
    f = _profile(FEED_ZIP, "food-additives")
    assert f["domain"]["value"] == "food-additives" and f["domain"]["basis"] == "chosen"


def test_intake_derives_runs_completeness_and_characterises(client):
    r = client.post("/api/dossier/intake", files={"files": ("demo.zip", FEED_ZIP.read_bytes(), "application/zip")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["domain"] == {"id": "feed", "label": "Feed additives", "grounded": True}
    assert d["completeness"]["application_type"] == "new"
    assert d["characterisation"] and d["characterisation"]["domain"]["id"] == "feed"
    assert d["characterisation"]["meta"]["routes"] == ["feed"]
    assert d["characterisation"]["meta"]["product_name"] == "DemoVan 99"
    assert d["characterisation"]["detected"]["all"]["product_name"]["citation"] == "Annex_I.pdf p.1"
    assert d["profile"]["fields"]["applicant"]["value"] == "Demo Feed Additives S.A."
    assert "dossier.intake" in [e["event"] for e in client.get("/api/activity").json()["events"]]


def test_notified_study_ids_are_never_taken_from_the_dossier(client):
    """The Art. 22(3) check compares the dossier with EFSA's notification database: deriving the IDs from the
    dossier (STUDY-DEMO-0042 is in it) would make the check pass by construction."""
    d = client.post("/api/dossier/intake", files={"files": ("demo.zip", FEED_ZIP.read_bytes(), "application/zip")}).json()
    match = next(r for r in d["completeness"]["results"] if r["rule_id"] == "PS-ART22-3-MATCH")
    assert match["status"] == "review"


def test_intake_runs_completeness_with_the_derived_fields(client):
    r = client.post("/api/dossier/intake", files={"files": ("demo.zip", FEED_ZIP.read_bytes(), "application/zip")},
                    data={"notified_study_ids": "STUDY-DEMO-0042, STUDY-DEMO-0099"})
    d = r.json()
    manual = client.post("/api/completeness/check", files={"files": ("demo.zip", FEED_ZIP.read_bytes(), "application/zip")},
                         data={"domain": "feed", "applicant": "Demo Feed Additives S.A.", "pre_application_ids": "PAI-DEMO-0001",
                               "notified_study_ids": "STUDY-DEMO-0042, STUDY-DEMO-0099"}).json()
    assert d["completeness"]["verdict"] == manual["verdict"]
    assert d["completeness"]["counts"] == manual["counts"]


def test_intake_ungrounded_or_undetected_domain_skips_characterisation(client):
    data = _text_zip({"cover.txt": "Application for authorisation of a novel food under Regulation (EU) 2015/2283.\nApplicant: Foo Bar GmbH\n"})
    d = client.post("/api/dossier/intake", files={"files": ("d.zip", data, "application/zip")}).json()
    assert d["domain"]["id"] == "novel-foods" and d["characterisation"] is None
    assert d["profile"]["fields"]["applicant"]["value"] == "Foo Bar GmbH"
    data = _text_zip({"notes.txt": "Nothing relevant here."})
    d = client.post("/api/dossier/intake", files={"files": ("d.zip", data, "application/zip")}).json()
    assert d["domain"]["id"] == "other" and d["profile"]["fields"]["domain"]["value"] is None


def test_intake_characterisation_rerun_keeps_assessor_answers(client):
    meta = '{"routes": ["water"], "additive_type": "flavouring_compound", "product_name": ""}'
    d = client.post("/api/dossier/intake", files={"files": ("demo.zip", FEED_ZIP.read_bytes(), "application/zip")},
                    data={"domain": "feed", "meta": meta, "steps": "characterisation"}).json()
    assert d["completeness"] is None
    assert d["characterisation"]["meta"]["routes"] == ["water"]  # the assessor's answer beats the derived one
    assert d["characterisation"]["meta"]["product_name"] == "DemoVan 99"  # blank entries keep the derived value
    assert d["characterisation"]["meta"]["additive_type"] == "flavouring_compound"


def test_intake_rejects_unknown_domain(client):
    r = client.post("/api/dossier/intake", files={"files": ("d.zip", _text_zip({"a.txt": "x"}), "application/zip")},
                    data={"domain": "nope"})
    assert r.status_code == 400
