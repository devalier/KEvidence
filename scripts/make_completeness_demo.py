#!/usr/bin/env python3
"""Build the fictional feed-additive dossier used to try the completeness check.

Everything in it is invented. It is deliberately incomplete so that every kind of finding shows up:
no completeness checklist and no Section IV (blocking), a public summary repeating confidential text (blocking),
a post-2021 study report with no study ID (blocking), a confidentiality list without page references, a scanned
annex, a file name with '#', a missing Section II heading, a justified omission, and personal data in a study report.

    python scripts/make_completeness_demo.py     # writes static/samples/completeness_demo_dossier.zip
"""

import io
import zipfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "samples" / "completeness_demo_dossier.zip"
CONFIDENTIAL_SENTENCE = ("The additive is produced by fermentation of the fictional strain followed by crystallisation at 4 degrees "
                         "for 48 hours in a proprietary vessel.")


def pdf(*pages: str, image_only_page: bool = False) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(56, 56, 540, 800), text, fontsize=10, fontname="helv")
    if image_only_page:  # a scanned page: an image, no text layer
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 100), False)
        pix.set_rect(pix.irect, (200,))
        doc.new_page(width=595, height=842).insert_image(pymupdf.Rect(56, 56, 456, 256), stream=pix.tobytes("png"))
    data = doc.tobytes(garbage=3, deflate=True, no_new_id=True)
    doc.close()
    return data


FILES = {
    "ADMINISTRATIVE DOCUMENTS/EFSA_letter.pdf": pdf(
        "Subject: Application for the authorisation of DemoVan 99 as a feed additive (fictional)\n\n"
        "Dear Sir or Madam,\n\nPlease find enclosed the dossier for DemoVan 99, a sensory additive for chickens for fattening.\n"
        "Pre-application ID: PAI-DEMO-0001\n\nYours faithfully,\nDemo Feed Additives S.A."),
    "ADMINISTRATIVE DOCUMENTS/Annex_I.pdf": pdf(
        "APPLICATION FOR THE AUTHORISATION OF A FEED ADDITIVE under Regulation (EC) No 1831/2003\n\n"
        "Applicant: Demo Feed Additives S.A., Rue de l'Exemple 12, 1000 Bruxelles, Belgium\n"
        "Additive: DemoVan 99\nCategory: sensory additives; functional group: flavouring compounds\nTarget species: chickens for fattening"),
    "ADMINISTRATIVE DOCUMENTS/Contact.pdf": pdf(
        "Contact details\n\nRegulatory contact: Dr. Marie Fictive\nE-mail: marie.fictive@demo-feed.example\nTel: +32 2 123 45 67"),
    "TECHNICAL DOSSIER/SECTION I/PubSum.pdf": pdf(
        "1.1 Public summary\n\n(a) Applicant: Demo Feed Additives S.A.\n(b) DemoVan 99, sensory additive for chickens for fattening.\n"
        "(c) Method of production: " + CONFIDENTIAL_SENTENCE + "\n(d) The additive is safe and efficacious at the proposed use level."),
    "TECHNICAL DOSSIER/SECTION I/ScSum.pdf": pdf("1.2 Scientific summary\n\nDemoVan 99 is vanillin of high purity (at least 99.5 %)."),
    "TECHNICAL DOSSIER/SECTION I/ListDoc.pdf": pdf(
        "1.3 List of documents and other particulars\n\nSect_II_Identity, Annex_II_1, Sect_III_Safety, Annex_III_1 to Annex_III_3, "
        "Sect_IV_Efficacy, Sect_V_Post_Mark"),
    "TECHNICAL DOSSIER/SECTION I/ConfInfo.pdf": pdf(
        "1.4 List of parts requested to be treated as confidential\n\n- Description of the manufacturing process\n- Quantitative composition"),
    "TECHNICAL DOSSIER/SECTION II/Sect_II_Identity.pdf": pdf(
        "SECTION II Identity, characterisation and conditions of use of the additive; methods of analysis\n\n"
        "2.1 Identity of the additive\nDemoVan 99 contains vanillin (CAS 121-33-5).\n\n"
        "2.2 Characterisation of the active substance\nVanillin, C8H8O3.\n\n"
        "2.3 Manufacturing process\n" + CONFIDENTIAL_SENTENCE + "\n\n"
        "2.5 Conditions of use\nUp to 125 mg/kg complete feed.\n\n"
        "2.6 Methods of analysis and reference samples\nHPLC-UV."),
    "TECHNICAL DOSSIER/SECTION II/Annex_II_1_CoA#batches.pdf": pdf("Certificates of analysis, batches 1-3 (fictional).", image_only_page=True),
    "TECHNICAL DOSSIER/SECTION III/Sect_III_Safety.pdf": pdf(
        "SECTION III Safety of the additive\n\n3.1 Safety for the target animals\nSee Annex_III_1.\n\n"
        "3.2 Safety for consumers\nSee Annex_III_2.\n\n3.3 Safety for users/workers\nNo irritation.\n\n"
        "3.4 Safety for the environment\nNot required: the additive is a substance occurring in nature and its use does not increase "
        "its concentration in the environment (justification for the omission of Phase II)."),
    "TECHNICAL DOSSIER/SECTION III/Annex_III_1_tolerance_study.pdf": pdf(
        "FINAL STUDY REPORT - Tolerance study of DemoVan 99 in chickens for fattening (fictional)\n\n"
        "Test facility: Fictional Animal Research Laboratory GmbH\nStudy Director: Dr. Jane Exampleton\n"
        "Study start date: 14 March 2023\nStudy completion date: 30 June 2023\n\n"
        "The study was conducted in compliance with Good Laboratory Practice (GLP)."),
    "TECHNICAL DOSSIER/SECTION III/Annex_III_2_genotoxicity_2019.pdf": pdf(
        "FINAL STUDY REPORT - Bacterial reverse mutation test with vanillin (fictional)\n\n"
        "Test facility: Fictional Genetox Lab\nStudy Director: Dr. Paul Specimen\nStudy initiation date: 05.02.2019\n\nGLP compliant."),
    "TECHNICAL DOSSIER/SECTION III/Annex_III_3_palatability_2022.pdf": pdf(
        "FINAL STUDY REPORT - Palatability study (fictional)\n\nTest facility: Fictional Feed Trials Ltd\n"
        "EFSA study ID: STUDY-DEMO-0042\nExperimental start date: 2022-09-01\n\nThe study plan was notified before the start."),
    "TECHNICAL DOSSIER/SECTION V/Sect_V_Post_Mark.pdf": pdf(
        "SECTION V Post-market monitoring\n\nProposal for post-market monitoring: not required for sensory additives (justified)."),
    "CONFIDENTIAL PARTS/Sect_II_Identity_Conf.pdf": pdf("2.3 Manufacturing process (confidential)\n\n" + CONFIDENTIAL_SENTENCE),
}


def build_demo_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in FILES.items():
            info = zipfile.ZipInfo(f"FAD-DEMO-0001/{path}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


if __name__ == "__main__":
    OUT.write_bytes(build_demo_zip())
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(FILES)} files)")
