#!/usr/bin/env python3
"""Build the fictional demo study report used to try the sanitisation step.

Every name, address, number and company in it is invented. It contains the things a non-confidential
version must not show (names of study personnel, e-mail, phone, signature, a comment by a reviewer,
author metadata) and passages an applicant might claim under the Annex (manufacturing process,
quantitative composition, sourcing), plus a reference list whose authors must stay public.

    python scripts/make_sanitisation_demo.py            # writes static/samples/sanitisation_demo_study_report.pdf
"""

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "samples" / "sanitisation_demo_study_report.pdf"

APPLICANT = "Demo Feed Additives S.A."
APPLICANT_ADDRESS = "Rue de l'Exemple 12, 1000 Bruxelles, Belgium"

PAGE1 = f"""TOLERANCE STUDY OF DEMOVAN 99 IN CHICKENS FOR FATTENING
Final report - Study code FICT-2025-017 (fictional demonstration document)

Sponsor / applicant: {APPLICANT}, {APPLICANT_ADDRESS}
Test facility: Fictional Animal Research Laboratory GmbH, Musterstraße 5, 12345 Musterstadt, Germany

Study Director: Dr. Jane Exampleton, PhD
Pathologist: Dr. Paul Specimen
Quality assurance manager: Anna Testwoman
Contact: jane.exampleton@fictional-lab.example
Tel: +49 30 1234 5678

The study was conducted in compliance with the OECD Principles of Good Laboratory Practice (GLP).
Day-old chickens (Ross 308, 240 birds) received DemoVan 99 in feed at 0, 125, 250 and 1250 mg/kg feed for 35 days.

Signature of the Study Director:"""

PAGE2 = """1. Identity and production of the test item

The manufacturing process consists of the oxidation of guaiacol-derived intermediates followed by
recrystallisation from ethanol at 45 °C for 6 hours and drying under vacuum at 30 mbar.
Quantitative composition of the product: vanillin 99.6 % w/w, silicon dioxide 0.4 % w/w.
The raw material guaiacol is sourced from Fictional Chemicals Ltd under an exclusive supply agreement.
The applicant expects a market share of 12 % of the EU flavouring premix market by 2028.

2. Results

No treatment-related effects on mortality, body weight gain or feed intake were observed.
Haematology and blood biochemistry were within the historical control range of the test facility.
The highest dose (1250 mg/kg feed) was well tolerated."""

PAGE3 = """3. Discussion

The results are consistent with published data on vanillin in poultry (Smith and Jones, 2019; Rossi et al., 2021).

References

Smith J, Jones K, 2019. Vanillin in broiler diets. Journal of Fictional Poultry Science 12, 1-10.
Rossi M, Bianchi L, Verdi G, 2021. Flavouring compounds in poultry nutrition. Fictional Animal Feed Reviews 4, 22-35."""


def _signature_png() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 40), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    for x in range(10, 150):  # a scribble
        y = int(20 + 12 * ((x // 9) % 2 * 2 - 1) * ((x % 9) / 9))
        for dy in range(-1, 2):
            pix.set_pixel(x, max(0, min(39, y + dy)), (20, 20, 120))
    return pix.tobytes("png")


def build_demo_pdf() -> bytes:
    doc = pymupdf.open()
    for i, text in enumerate((PAGE1, PAGE2, PAGE3)):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(56, 56, 540, 800), text, fontsize=10, fontname="helv")
        if i == 0:
            page.insert_image(pymupdf.Rect(230, 395, 390, 435), stream=_signature_png())
            page.add_text_annot((480, 80), "Reviewer comment: check with Anna Testwoman").set_info(title="Paul Specimen")
            page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(56, 170, 300, 182),
                              "uri": "mailto:jane.exampleton@fictional-lab.example"})
    doc.set_metadata({"author": "Jane Exampleton", "title": "FICT-2025-017 final report", "creator": "Demo word processor"})
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


if __name__ == "__main__":
    OUT.write_bytes(build_demo_pdf())
    print(f"Wrote {OUT.relative_to(ROOT)}")
