<!--
KEvidence step 0 output template.
Placeholders ({{NAME}}) are filled by characterisation.render_markdown():
  PRODUCT_NAME, HEADER, DETECTED (what was identified from the documents), OPINION_111 (characterisation of the additive: specifications, Table 1/Table 2, facts for the
  conclusion, production-strain paragraphs for fermentation products), APPENDIX_A (other impurities, physico-chemical and
  technological properties), OPINION_112 (production microorganism; outside the MVP), GAP_ANALYSIS, DOCUMENT_REGISTER,
  S2_1 ... S2_6 (evidence map against guidance Sections 2.1-2.6), GROUNDING, CAVEATS.
The layout follows the characterisation section of FEEDAP scientific opinions. An institution can use its own internal
template by saving it as data/guidance/local/characterisation_template.md (git-ignored) or by setting
KEVIDENCE_CHARACTERISATION_TEMPLATE to its path; it may use any subset of the placeholders above.
-->
# Characterisation of the additive — {{PRODUCT_NAME}}

{{HEADER}}

## Identified from the uploaded documents

{{DETECTED}}

## 1.1.1 Characterisation of the additive

{{OPINION_111}}

## 1.1.2 Characterisation of the active agent/production microorganism

{{OPINION_112}}

## Appendix A — Other impurities and physico-chemical and technological properties

{{APPENDIX_A}}

---

## Data-gap analysis against the guidance

{{GAP_ANALYSIS}}

---

# Annex — Evidence map against the FEEDAP (2017) guidance, Section 2

Each requirement of the Guidance on the identity, characterisation and conditions of use of feed additives (EFSA Journal 2017;15(10):5023) with the evidence located in the dossier. The numbering mirrors Section 2 of Annex II of Regulation (EC) No 429/2008.

## Documents assessed

{{DOCUMENT_REGISTER}}

## 2.1 Identity of the additive

{{S2_1}}

## 2.2 Characterisation of the active substance(s)

{{S2_2}}

## 2.3 Manufacturing process, including any specific processing procedures

{{S2_3}}

## 2.4 Physical–chemical and technological properties of the additive

{{S2_4}}

## 2.5 Conditions of use of the additive

{{S2_5}}

## 2.6 Methods of analysis and reference samples

{{S2_6}}

## Guidance grounding and provenance

{{GROUNDING}}

{{CAVEATS}}
