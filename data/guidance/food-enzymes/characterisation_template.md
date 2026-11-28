<!--
KEvidence identity & characterisation template for food enzymes.
Placeholders ({{NAME}}) are filled by characterisation.render_markdown():
  PRODUCT_NAME, HEADER, ENZYME_IDENTITY (enzyme, EC number, source, production organism and strain properties identified from
  the documents), ENZYME_BATCHES (activity, TOS, water, ash and protein as stated), GAP_ANALYSIS, DOCUMENT_REGISTER,
  S0 ... S5 (evidence map against the CEP 2021 guidance, Part A), GROUNDING, CAVEATS.
The layout follows the structure of EFSA CEP Panel opinions on food enzymes (source, production, characteristics, toxicological
data, dietary exposure). An institution can use its own template by saving it as data/guidance/food-enzymes/local/
characterisation_template.md (git-ignored) or by setting KEVIDENCE_CHARACTERISATION_TEMPLATE; it may use any subset of the
placeholders above.
-->
# Food enzyme — {{PRODUCT_NAME}}

{{HEADER}}

## Identified from the uploaded documents

{{ENZYME_IDENTITY}}

## Characteristics of the food enzyme — batch data as stated

{{ENZYME_BATCHES}}

---

## Data-gap analysis against the guidance

{{GAP_ANALYSIS}}

---

# Annex — Evidence map against the CEP (2021) food enzyme guidance, Part A

Each requirement of the Scientific Guidance for the submission of dossiers on Food Enzymes (EFSA Journal 2021;19(10):6851) with the evidence located in the dossier. The sections follow the structure of EFSA opinions on food enzymes.

## Documents assessed

{{DOCUMENT_REGISTER}}

## Identity of the food enzyme

{{S0}}

## 1. Source of the food enzyme

{{S1}}

## 2. Production of the food enzyme

{{S2}}

## 3. Characteristics of the food enzyme

{{S3}}

## 4. Toxicological data

{{S4}}

## 5. Dietary exposure

{{S5}}

## Guidance grounding and provenance

{{GROUNDING}}

{{CAVEATS}}
