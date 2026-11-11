# KEvidence

**An open-source prototype workbench for food and feed safety risk assessment, built in the open for public administrations and risk assessors to test, challenge and build on. Grounded in European public regulations and standards.**

> Independent prototype, developed without the endorsement of any public administration or institution. Not a source of regulatory conclusions.

KEvidence follows a regulatory scientific assessment from dossier to publication. A scientific officer uploads the applicant's documents and KEvidence:

0. **checks the dossier on receipt** — completeness, structure, study notifications under the Transparency Regulation, the confidentiality request and personal data — and drafts the request for missing information;
1. **characterises the substance or product** against the applicable guidance, citing document and page for every value and listing data gaps;
2. **structures hazard and exposure evidence** along the four Codex risk-assessment steps (Adverse Outcome Pathways, OpenFoodTox reference points, NAM points of departure, exposure estimates, screening margins);
3. **drafts the uncertainty analysis and the scientific opinion** for expert refinement;
4. **prepares documents for publication** under the Transparency Regulation, masking confidential information and personal data according to the published practical arrangements.

**Grounded, not generative.** Every requirement KEvidence checks is quoted verbatim from official guidance bundled with the code, and the tests fail if a quote or page reference drifts from the source PDF. The assistant answers only from that guidance and says so when it cannot. Extraction runs locally. AI features use each user's own provider and key (OpenAI, Anthropic, Mistral AI in the EU, DeepSeek, Fireworks AI, OpenRouter or an on-premises model), are off until the user configures one, and send dossier content only when ticked for that run.

**It assists experts; it does not decide.** Adequacy, safety conclusions and confidentiality decisions stay with the risk assessor and the competent authority.

**Status:** prototype. KEvidence works from European public regulations and standards — EU food and feed law, the Transparency Regulation and the published scientific and administrative guidance that implements them — across twelve regulated areas (feed additives, food additives, flavourings, enzymes, food contact materials, novel foods, GMOs, pesticides, contaminants, biological hazards, NAMs/AOPs, other); every one gets the risk-assessment workflow and publication. Guidance-grounded tools cover **feed additives** (intake completeness, and identity and characterisation from the FEEDAP guidance with consumer, target-species, environment, microorganism, renewal, QPS/WGS and VICH sources) and **food enzymes** (intake suitability checklist) today. The sanitisation step covers all sectors of the transparency rules (General Food Law, GMOs, feed additives, smoke flavourings, food contact materials, food improvement agents, plant protection products, novel foods).

## Contribute — public administrations and risk assessment experts welcome

KEvidence is meant to become a shared, inspectable tool rather than one more closed system. Contributions are especially welcome from:

- **Food and feed safety agencies and competent authorities** (EU, Member States and beyond): try it on demo or non-confidential dossiers, tell us where it misreads a document or a requirement, and propose the guidance your assessments rely on.
- **Risk assessment experts:** review the requirement catalogues, the gap rules, the uncertainty and screening logic, and the sanitisation rules; point out where the tool oversteps expert judgement.
- **New domains:** food additives, enzymes, flavourings, novel foods, pesticides, food contact materials... A domain is a folder of guidance PDFs plus a catalogue that quotes them verbatim (see *Domains* below); no code change is needed to add one.
- **Developers:** OCR for scanned dossiers, importers for official data releases, tests, accessibility and UI work.

Open an issue or discussion on [GitHub](https://github.com/devalier/KEvidence), or write to <kevidence@devalier.com>. KEvidence is licensed under the **AGPL-3.0** (compatible with the EUPL): anyone may use, study, adapt and deploy it, and improvements made by any administration or company stay open for all.

## Quick start

```bash
git clone https://github.com/devalier/KEvidence.git && cd KEvidence
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
KEVIDENCE_HOME=$PWD python server.py      # http://127.0.0.1:3457
```

Open the page and sign in with any email address: without a mail transport configured, the one-time sign-in link is printed in the server console. Optionally add your own AI provider and key in *AI configuration*. Then try the fictional demo material (also linked from *Guide & samples*):

- **Characterisation:** choose *Feed additives* in *Mandate & question*, then upload `static/samples/characterisation_demo_dossier.md` in *Identity & characterisation* and click *Characterise from documents*.
- **Sanitisation:** upload `static/samples/sanitisation_demo_study_report.pdf` in *Publication*, applicant `Demo Feed Additives S.A.`, and click *Propose redactions*.
- **Completeness check:** upload `static/samples/completeness_demo_dossier.zip` in *Completeness & sanitisation*, applicant `Demo Feed Additives S.A.`, notified study IDs `STUDY-DEMO-0042, STUDY-DEMO-0099`, and click *Check completeness*.

---

## How the workflow is organised

**Risk analysis** is the whole governance cycle — risk assessment, risk management, and risk communication (EU General Food Law, Regulation (EC) No 178/2002). KEvidence supports the scientific **risk assessment** part, which Codex defines as four steps. The workbench follows that structure, with problem formulation as the practical framing step:

- **Intake — completeness check & sanitisation** — what EFSA's front desk (FDP unit) does on receipt, before any assessment: completeness, structure, study notifications, confidentiality request, personal data; outcome within 30 working days.
- **Problem formulation** — define the substance/stressor, product domain, use scenario, endpoint of concern, and decision context. Not one of the four formal Codex steps, but it frames all of them.
- **Identity & characterisation** (dossier evaluation; guidance-grounded for feed additives) — establish exactly what is being assessed: identity and composition of the additive and of *each component* of a product, mixture or formulation, impurities, physical properties, manufacturing, stability, homogeneity, conditions of use and methods of analysis, grounded in the EFSA FEEDAP *Guidance on the identity, characterisation and conditions of use of feed additives* (EFSA Journal 2017;15(10):5023). The MVP covers chemical characterisation.
1. **Hazard identification** — *can this agent cause harm?* Search and select candidate AOPs by chemical, stressor, key event, adverse outcome, or AOP ID.
2. **Hazard characterisation** — *what is the nature and severity of the harm, and at what dose?* Review MIEs, key events, KERs, weight of evidence, and quantitative understanding; pull reference points and health-based guidance values from OpenFoodTox; and set a dose-response point of departure (POD) from NAM data (optionally browsing locally indexed EPA ToxCast/Tox21/ToxRefDB-style exports).
3. **Exposure assessment** — *who is exposed, how much, how often, and by which route?* Record concentration in food/feed × consumption × population × use conditions, and the resulting exposure estimate.
4. **Risk characterisation** — *given hazard and exposure, what is the risk?* Integrate the POD with the exposure estimate to calculate screening margins (BER/MOE) and a hazard-quotient-style ratio.

The workbench then supports **uncertainty analysis** (confidence summaries, key uncertainties, critical data gaps, recommended next data) and a **scientific opinion draft** that can be refined with the Evidence Assistant and handed to risk managers.

At the end, **publication — sanitisation** prepares documents for publication under the Transparency Regulation: confidential information and personal data are masked according to EFSA's practical arrangements concerning transparency and confidentiality.

> **Hazard is not risk.** Hazard is the intrinsic potential for harm; risk is that hazard under actual exposure conditions. KEvidence keeps the two separate and does not make risk-management decisions.

---

## Key features

### Intake — completeness check & sanitisation

Mirrors EFSA's front desk (FDP unit), which checks every application on receipt and either asks the applicant for missing information or declares it valid. EFSA aims to communicate the outcome within 30 working days.

- **Input:** the dossier as files, as its folder (the browser keeps the folder structure) or as a ZIP (expanded in memory; size, count and path limits). Also the application type (new, modification, renewal), the applicant (stays public), and optionally the pre-application ID(s) and the study IDs notified in EFSA's database.
- **Rules** (`data/guidance/intake/`, quoted verbatim and anchored like every other catalogue):
  - EFSA's administrative guidance for feed additive applications with its **Appendix B completeness checklist**. The current version (EFSA Supporting Publication 2021:EN-6508, updated 2025) could not be downloaded for bundling, so this is the 2018 public-consultation draft from efsa.europa.eu. It is labelled as such: confirm file naming and structure against the current version.
  - EFSA's **suitability checklist for food enzyme applications** (Appendix A to EFSA Supporting Publication 2021:EN-6509). Each row quotes the section of the CEP *Scientific Guidance for the submission of dossiers on Food Enzymes* it implements. The bundled copy is the 2021 public-consultation draft hosted by EFSA, because neither Appendix A nor the adopted guidance (EFSA Journal 2021;19(10):6851) could be downloaded for bundling. Part A (new food enzyme, by microbial, plant or animal source) and Part B (modification or extension of use) are checked separately.
  - EFSA's **practical arrangements on pre-submission and study notification**: Art. 19 (studies from 27 March 2021), Art. 21 (pre-application and study IDs, justifications), Art. 22(3) (all notified studies, and only those), Art. 23 (consequences).
  - The **transparency arrangements** (Art. 4(5) personal data, Art. 10(a) precise confidentiality list).
- **Checks.** Each has a severity, as in IUCLID's Validation Assistant: **blocking** (prevents validity; goes into the request for missing information), **warning** (quality; worth raising) or **info**.
  - **Structure and format:** three parts; one file per section; searchable PDF; 30 MB; no security settings; file names; English.
  - **Administrative documents:** cover letter, application form, completeness checklist, contact details.
  - **Section I:** public, scientific and document-list summaries. The public summary is checked against the confidential copies (shared 10-word passages). Renewals: previous authorisation.
  - **Sections II–V:** the section and each checklist heading (2.1–2.6, 3.1–3.4, 4.1, post-market monitoring). Justified omissions are flagged for review.
  - **Study notifications:** study reports are recognised, their start date read, and any report from 27 March 2021 needs a study ID or a justification. Notified IDs missing from the dossier are flagged, and the pre-application ID is checked.
  - **Confidentiality:** list of confidential parts with page references, and `_Conf` copies.
  - **Personal data:** the sanitisation detectors run on every non-confidential PDF (contact details excluded).
- **Output:** a verdict (incomplete / complete with warnings / complete), checks grouped by category with evidence (file and page) and the rule behind each, and a file inventory with what each file was recognised as. Downloads: a check report and a draft **request for missing information** (Markdown). *Sanitise* opens a file in Publication with the applicant filled in.
- **The applicant's own checklist:** if the dossier contains its filled-in completeness or suitability checklist, the ticks are read (by position in PDFs). The tool lists the rows declared *not provided* (each needs a justification) and *not relevant*, and flags declarations it can disprove, e.g. copies of references declared provided when only a list is present.
- **Scope:** the feed checklist applies to the *Feed additives* domain and the suitability checklist to *Food enzymes* (Part A/B from the application type, source detected or chosen). Other domains get the format, study-notification, confidentiality and personal-data checks, with the sector checks marked not applicable. Files are recognised by the guidance's file names (e.g. `PubSum`, `Sect_III_Safety`, `Annex_III_1_…`, `_Conf`), then by folder, then by content.

### Identity & characterisation — feed additives (chemical MVP)

Assists scientific officers with the characterisation section of a feed additive assessment.

- **Input:** confidential applicant documents — uploads (PDF, DOCX, XLSX, CSV/TSV, TXT/MD, JSON, HTML) and/or URLs (a PDF/DOCX/XLSX link, or an HTML page whose linked documents are followed). Product form, routes of administration, production type, additive type, current authorisation, preparations/formulations under application, and each component (name, CAS, role).
- **Output (on screen, as Markdown and as a Word file):** the *Download Word (.docx)* button converts exactly the Markdown on screen (`docx_export.py`, `POST /api/characterisation/export.docx`; nothing is stored), so the two cannot differ. Tables keep their header rows across pages and have content-based column widths; footnotes appear as numbered notes under their table; the page header marks it as a draft for scientific-officer verification. Content:
  1. a draft of the opinion's characterisation section in the FEEDAP opinion layout: §1.1.1 *Characterisation of the additive* with the specifications, **Table 1** (product/active substance) and, when preparations are listed, **Table 2** (one column per preparation) — batch-to-batch variation as average (range) [number of batches], substance-related impurities and residual solvents as ranges, `<` below the LOQ, `-` not analysed, footnotes naming the source documents — followed by facts located for the scientific officer's conclusion (e.g. "3/3 batch values meet the specification ≥ 99.5 %") and, for fermentation products, the viable-cell and DNA fields; **Appendix A** with other impurities and physico-chemical/technological properties; §1.1.2 (production microorganism) as an out-of-scope stub;
  2. the data-gap analysis;
  3. an evidence map against Section 2 of the guidance (2.1 Identity … 2.6 Methods of analysis).

  KEvidence never writes the Panel's conclusions; it leaves an explicit placeholder for the scientific officer. The public template (`data/guidance/feed/characterisation_template.md`) reproduces only the layout conventions visible in published FEEDAP opinions. An institution can use its own internal template by saving it as `data/guidance/feed/local/characterisation_template.md` (git-ignored) or by setting `KEVIDENCE_CHARACTERISATION_TEMPLATE`; the available placeholders are documented at the top of the public template.
- **Data-gap analysis:** each of 27 guidance requirements is marked *evidence located*, *partially addressed*, *not located*, *applicability to confirm*, *scientific-officer review* or *not applicable*. Quantitative checks come straight from the guidance: ≥ 5 batches for the specification and ≥ 3 for impurities (§2.1.3, §2.1.4), analyses within the last 5 years, statements of compliance flagged (not sufficient on their own), dusting potential in ≥ 3 batches (§2.1.5), shelf life in ≥ 3 batches (§2.4.1.1), premixture ≥ 6 months and feed ≥ 3 months (§2.4.1.2), water ≥ 48 h (§2.4.1.3), homogeneity ≥ 10 subsamples (§2.4.2). The minimum impurity set depends on production type (chemical synthesis, fermentation, plant-derived, animal-derived, mineral; §2.1.4). Exemptions (flavouring compounds, silage additives, colourants, mineral-based additives) are applied where the guidance gives them. Applicant justifications for omissions are surfaced (guidance p.5: reasons should be given for any omission).
- **Grounding:** the requirement catalogue (`data/guidance/feed/feedap_2017_5023_chemical_requirements.json`) cites the guidance section and page and quotes it verbatim for every requirement. The guidance PDF is bundled unmodified (CC BY-ND 4.0) and every requirement is re-anchored against its text at start-up; the UI shows how many are anchored and the PDF is served at `/api/characterisation/guidance.pdf`. `tests/test_characterisation.py` fails if any quote, page reference or anchor drifts from the guidance. In this tool the Evidence Assistant answers only from the guidance entries and refuses questions it cannot ground.
- **Domains:** `data/guidance/domains.json` registers twelve areas, chosen in *Mandate & question* (the header chip shows the current one). Every domain gets the workflow, the AOP/NAM tools and publication (its Annex sector of the EFSA confidentiality rules is set by `transparency_sector`). A domain is **grounded** when it also has a `directory` and a `primary` catalogue; only grounded domains (today *Feed additives*) get this characterisation tool and the guidance-only assistant, and the backend loads their catalogues, PDFs and template from `data/guidance/<domain>/`. A workflow-only domain gets an explanation instead (HTTP 400 with the reason), and an unknown domain is rejected; the backend never falls back to another domain's guidance. To ground a domain: create `data/guidance/<domain>/` with a primary catalogue quoting its guidance verbatim, the PDFs and a template, and add `directory` and `primary` to its entry in `domains.json`. No code change is needed.
- **Supporting sources:** besides the primary catalogue that drives the gap analysis, a domain lists supporting catalogues (`entries` with the same verbatim-quote and page-anchor checks) that ground the assistant. Each entry is tagged with the workflow step it informs (`steps`: `characterisation` by default, `hazard-char`, `exposure`, `risk-char`); the assistant in a step answers only from that step's entries and tells the user which step holds the answer otherwise. Feed has nine, listed in the order of the project's reference list: EFSA 2024 WGS statement (e8912; reporting expectations, not assessment criteria); BIOHAZ 2023 QPS AMR statement (8323, revised 2025); BIOHAZ 2026 QPS list (e9823; principles and qualifications); FEEDAP 2017 consumer safety (5022; characterisation items, safe dose, consumption, residues, exposure method, MOS, MRLs); FEEDAP 2017 target species (5021; presumed safety, safe feed concentration, default feed intakes, TTC, tolerance-study test item); FEEDAP 2018 microorganisms (5206); FEEDAP 2019 environment (5648; Phase I screen and triggers, Phase II logic, physico-chemical data); FEEDAP 2021 renewal (6340); VICH GL18(R2) residual solvents. Not yet bundled: DECOS 2010 (endotoxins), FEEDAP 2023 user safety, FEEDAP 2024 efficacy, the 2025 Scientific Committee microorganism guidance.
- **Structured datasets** (`domains.json` → `datasets`), each extracted from the bundled PDFs and checked against them by the tests: QPS cycle assessments (Tables 6 and 7 of the 2026 opinion; **partial**, 31 units assessed October 2022 to September 2025 plus the excluded groups; it is not the QPS list, and a missing species means nothing; `GET /api/qps`); FEEDAP 2018 MIC cut-offs (Table 2); VICH GL18(R2) solvent limits (Tables 1-4). Reported residual-solvent values in the dossier are compared with the VICH Option 1 limits (10 g/day basis) and shown as facts in the characterisation, never as a conclusion.
- **Traceability:** extraction is deterministic (pattern-based); every value carries a `D<n> p.<page>` citation. Statuses say whether evidence was *located*, not whether it is adequate — adequacy stays with the scientific officer.
- **Confidentiality:** documents are processed in memory for one request and are not stored. Extraction and gap analysis run locally. Optional LLM drafting of section narratives sends extracted excerpts to the user's own AI provider and is **off unless ticked per request**; every number in an LLM narrative is checked against the dossier excerpts and untraced numbers are flagged.
- **Limits:** scanned PDFs need OCR first; dossier portals rendered by JavaScript (e.g. Open EFSA) cannot be read by URL — download and upload the documents. Production-strain characterisation (§2.2.1.2, §2.2.2.2; FEEDAP microorganism guidance, EFSA Journal 2018;16(3):5206) is out of scope; fermentation-related impurity requirements of §2.1.4 are included.

A fictional, deliberately incomplete demo dossier is provided at `static/samples/characterisation_demo_dossier.md` (also linked from the in-app *Guide & samples* tab).

### Publication — sanitisation under the Transparency Regulation

Regulation (EU) 2019/1381 amended the General Food Law (Regulation (EC) No 178/2002, Art. 38-39e): EFSA proactively publishes the documents supporting its scientific outputs, with confidential information and personal data masked. KEvidence prepares the non-confidential version of a PDF.

- **Rules:** EFSA's *Decision of the Executive Director laying down practical arrangements concerning transparency and confidentiality* (ver. 2, 18.01.2021, applicable from 27 March 2021), bundled unmodified at `data/guidance/transparency/` and served at `/api/sanitisation/rules.pdf`. The catalogue (`efsa_2021_pa_transparency_confidentiality_rules.json`) encodes the definition of sanitisation (Art. 3(1)(c)), the personal-data rule for non-confidential versions (Art. 4(5)), publication of updated versions (Art. 6), the closed list and minimum content of requests (Art. 9(4), 10), blackening (Art. 13(2)), review where foreseeable health effects are concerned (Art. 14) and non-disclosure pending decisions (Art. 16(3)), plus the **Annex closed list by sector**: (a) General Food Law, (b) GM food/feed, (c) feed additives, (d) smoke flavourings, (e) food contact materials, (f) food additives/enzymes/flavourings, (g) plant protection products, (h) novel foods. Every rule quotes the decision verbatim; `tests/test_sanitisation.py` fails if a quote, page or anchor drifts. The sector defaults from the domain (`transparency_sector` in `domains.json`; feed → (c)).
- **Input:** one PDF (confidential), the sector, the applicant's name and address (public under Art. 39e(1)(a)), and optionally the items of the confidentiality request or decision, one per line (`text | legal basis`).
- **Proposals** (each with its rule, legal basis, reason and boxes on the page):
  - *personal data*, selected by default — names with study roles or titles, e-mails, phone numbers, signature images; study personnel of GLP/animal studies under Art. 39e(2), others under Art. 39e(1)/Art. 4(5); street addresses proposed but not selected (personal or organisational?);
  - *request/decision items*, located verbatim and selected;
  - *Annex candidates* — sentences matching an Annex item of the sector (manufacturing process, commercial links, sourcing/market share, quantitative composition, efficacy study plan, impurity specifications, ...) — **not** selected: they are masked only if claimed or granted, and never if relevant to the safety assessment.
  - Exceptions are applied: the applicant's name and address and authors in reference lists are never proposed.
- **AI review (optional, per request):** sends the page text to the user's own AI provider to find personal data and Annex items the rules miss and to locate request items described in words. Every AI finding must name a rule that applies to the sector and its text must be found on the cited page; otherwise it is rejected and counted. Findings the AI marks as relevant to the safety assessment are flagged and left unselected. Off unless ticked.
- **Review:** page previews with the boxes overlaid and a list; click to toggle; bulk actions; "mask more text" finds every occurrence of a string.
- **Output:** true redaction with PyMuPDF (the text, image pixels and links under each box are removed from the file, not covered), optional legal-basis label in each box; all comments, form fields, mailto links, attachments, JavaScript, document metadata and XMP removed; the file is rewritten (no incremental update). The output is re-read to **verify** that the masked text is gone from the pages where it was masked, and copies left elsewhere are reported. A sanitisation record (Markdown) lists every masked item with its legal basis — it contains the masked text and is confidential.
- **Limits:** pages without a text layer (scans) cannot be analysed — OCR first; text in images other than signatures is not detected; the decision on confidentiality stays with EFSA (Art. 11 of the arrangements). PyMuPDF is AGPL-3.0, like KEvidence.
- A fictional demo study report is at `static/samples/sanitisation_demo_study_report.pdf` (generated by `scripts/make_sanitisation_demo.py`).

### AOP-Wiki knowledge base

KEvidence builds a local SQLite database from bundled AOP-Wiki-derived TSV and XML data. The local database includes:

- AOP IDs, titles, molecular initiating events, adverse outcomes, and OECD status where available.
- Key events and event types.
- Key Event Relationships (KERs).
- KER-level evidence and quantitative understanding codes.
- Event components and ontology identifiers.
- Chemical/stressor mappings extracted from the bundled AOP-Wiki XML file.

### Risk assessment workbench UI

The frontend is a single page (no frameworks, no CDN). The left pane groups the steps by phase, the way a mandate runs; only the four Codex steps are numbered:

```text
ASSESSMENT          Mandate & question (domain, problem formulation)
INTAKE              Completeness & sanitisation
DOSSIER EVALUATION  Identity & characterisation
RISK ASSESSMENT     1 Hazard identification · 2 Hazard characterisation · 3 Exposure assessment
                    4 Risk characterisation · Uncertainty analysis
OUTPUT              Scientific opinion · Publication (sanitisation)
──────────────────  AI configuration · Activity log · Guide & samples
```

The header shows the current domain, the signed-in user and *Sign out*. The Evidence Assistant sits beside every step except characterisation.

### Evidence-to-decision assessment

The `/api/assess` endpoint produces structured assessment outputs for a chemical or stressor, including:

- Candidate AOPs.
- Hazard hypotheses.
- Confidence summaries.
- Uncertainties.
- Critical data gaps.
- Recommended next tests or NAMs.
- Regulatory summary language.

### Quantitative AOP / exposure-aware screening (risk characterisation)

The `/api/quantitative-assessment` endpoint performs the risk-characterisation integration: it accepts hazard-side NAM PODs, mapped AOP events, exposure-side values, and optional simple IVIVE conversion factors. It returns:

- Most sensitive measured key event.
- Bioactivity-exposure ratio (BER).
- Margin of exposure (MOE).
- Hazard quotient-style screening metric.
- Quantitative confidence.
- Interpretation and uncertainties.
- Provenance and validation caveats.

> **Important:** the quantitative module is a screening calculator shell. It does not include validated regulatory thresholds, curated assay PODs, exposure values, PBPK/HTTK models, or validated IVIVE workflows by default. Users must provide or configure scientifically appropriate data.

### OpenFoodTox integration

KEvidence supports two OpenFoodTox access modes:

1. **Regular client mode:** build a local SQLite index from EFSA OpenFoodTox Excel/CSV exports.
2. **Institutional mode:** query a local IUCLID 6 instance after OpenFoodTox `.i6z` dossiers have been imported.

The importer can download the OpenFoodTox export from Zenodo or ingest local files.

### EPA ToxCast/Tox21/ToxRefDB-style bioactivity browser

KEvidence includes a generic importer for EPA/CompTox exports. It can index CSV, TSV, XLSX, or a directory of exported files into `data/bioactivity.db`.

The workbench can then search candidate AC50/POD records for the current chemical and rank records higher when assay or endpoint text overlaps selected AOP key events.

### Contextual Evidence Assistant

The Evidence Assistant uses the signed-in user's own AI configuration (see *Accounts and AI configuration*); without one it says so and points to *AI configuration*. It uses structured workbench context when answering questions. In the guidance-grounded steps (0. characterisation, 2-4 where the domain has entries for them, and publication: sanitisation) it answers **only** from the bundled guidance entries supplied to it, cites document, section and page, and refuses or redirects to the right step when no entry matches. In the AOP steps, a short prompt such as “Explain AOP” is answered with the current chemical, selected AOP, use case, route, population, OpenFoodTox summary and quantitative context.

---

## Repository structure

```text
.
├── server.py                          # FastAPI backend: AOP knowledge base, assessment logic, all API routes
├── accounts.py                        # Email sign-in, sessions, rate limits, activity log (SQLite in data/state/)
├── ai.py                              # Per-user AI configuration (encrypted keys), provider calls, llm_chat()
├── netguard.py                        # SSRF guard for user-supplied URLs (address checks, DNS pinning)
├── limits.py                          # Request-size limits, rate limits, cap on concurrent document jobs
├── completeness.py                    # Intake: completeness check, study notifications, personal-data screening, missing-information letter
├── characterisation.py                # Identity & characterisation: document ingestion, guidance-grounded characterisation and gap analysis
├── docx_export.py                     # Markdown → Word (.docx) for the characterisation output
├── sanitisation.py                    # Publication: redaction proposals, true redaction and verification
├── static/
│   ├── index.html                     # Single-page workbench UI
│   └── samples/                       # Fictional demo dossier and study report, CSV templates
├── scripts/
│   ├── import_openfoodtox.py          # EFSA OpenFoodTox Excel/CSV/XLSX importer
│   ├── import_epa_bioactivity.py      # EPA ToxCast/Tox21/ToxRefDB-style importer
│   ├── filter_aopwiki_licences.py     # Keeps only CC BY-SA AOP-Wiki content in data/
│   ├── make_sanitisation_demo.py      # Builds the fictional sanitisation demo PDF
│   └── make_completeness_demo.py      # Builds the fictional, deliberately incomplete demo dossier (ZIP)
├── data/
│   ├── guidance/
│   │   ├── domains.json               # Domain registry (id, label, directory, sources, datasets, sanitisation sector)
│   │   ├── feed/                      # Feed-additive domain: guidance PDFs (unmodified) + verbatim-quoted catalogues,
│   │   │                              #   structured datasets (QPS cycle, MIC cut-offs, VICH solvents), output template,
│   │   │                              #   local/ (git-ignored) for an institution's own template
│   │   ├── intake/                    # Completeness rules: feed administrative guidance + checklist (2018 draft), pre-submission arrangements
│   │   └── transparency/              # EFSA practical arrangements on transparency & confidentiality (PDF + rules catalogue)
│   ├── aop-wiki-xml.gz                # AOP-Wiki export (CC BY-SA AOPs only)
│   ├── aop_ke_mie_ao.tsv, aop_ke_ker.tsv, aop_ke_ec.tsv   # AOP events, KERs, event components
│   ├── aopwiki_licence_filter.json    # Record of AOP-Wiki content removed for licence reasons
│   └── aops/                          # Cached AOP text excerpts
├── tests/                             # Grounding guards, characterisation, sanitisation, accounts, AI configuration, licensing, Word export, HTTP security, hardening
├── .github/workflows/                 # pytest and pip-audit on every push
├── requirements.in, requirements-dev.in   # Direct dependencies (edit these)
├── requirements.txt, requirements-dev.txt # Generated locks: every package pinned with hashes
└── LICENSE                            # AGPL-3.0
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/devalier/KEvidence.git
cd KEvidence
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Run the application

```bash
KEVIDENCE_HOME=$PWD python server.py
```

It listens on `http://127.0.0.1:3457`. In development the sign-in link is printed in this console.

### 5. AI (optional, per user)

There is no server-wide AI key. Each user opens *AI configuration* and adds their own models (OpenAI, Anthropic, Mistral AI, DeepSeek, Fireworks AI, OpenRouter, or an on-premises OpenAI-compatible endpoint) and selects the one in use. Keys are encrypted with `KEVIDENCE_SECRET_KEY`.

---

## Deployment security

To report a vulnerability, see [SECURITY.md](SECURITY.md).

- **Authentication:** every page and API route requires a signed-in session, except the sign-in flow, `/api/health` and `/robots.txt` (see *Accounts and AI configuration*). Serve over HTTPS only; over https the server sends `Strict-Transport-Security`.
- **Cross-site requests:** state-changing requests whose `Origin` is not the site's own are refused (403), as are those a browser marks `Sec-Fetch-Site: cross-site` or `same-site`. In production only the origin of `APP_URL` is accepted. Session cookies are `HttpOnly`, `SameSite=Lax` and, over https, `__Host-` prefixed and `Secure`.
- **CORS:** off by default (the UI is same-origin). To allow other origins, set `KEVIDENCE_CORS_ORIGINS` to a comma-separated list.
- **Outbound requests (SSRF):** the two URLs a user can make the server fetch, dossier URLs and custom AI endpoints, go through `netguard.py`. Loopback, link-local (cloud metadata), private, carrier-grade NAT and reserved addresses are refused, including IPv4 addresses hidden in IPv6 ones; every redirect hop is checked again; and the connection goes to the address that was checked, so a DNS answer that changes between check and connection (DNS rebinding) cannot reach an internal service. Set `KEVIDENCE_FETCH_PORTS` (e.g. `80,443`) to restrict the ports. Behind an outbound proxy (`HTTPS_PROXY`) the proxy resolves names, so restrict internal destinations there too.
- **Request size:** bodies over the limit of their route are refused with 413 before they are buffered: 16 MB by default (`KEVIDENCE_MAX_BODY_MB`), one PDF of 25 MB for sanitisation, 200 MB per characterisation (`KEVIDENCE_MAX_TOTAL_BYTES`, uploads plus URLs), 400 MB per dossier for intake. Set the reverse proxy's limit to match what you want to allow.
- **Rate limits:** per signed-in user (per address before sign-in; per /64 for IPv6): 600 requests a minute overall, 60 document jobs and 120 assistant questions per 10 minutes, 30 calls per 10 minutes that contact a user-supplied AI endpoint. At most 2 document jobs run at once per user and 6 overall (`KEVIDENCE_HEAVY_PER_USER`, `KEVIDENCE_HEAVY_TOTAL`). Over the limit the answer is 429 with `Retry-After`. Override with `KEVIDENCE_RATE_GENERAL`, `_HEAVY`, `_AI`, `_OUTBOUND` as `requests/seconds`; `KEVIDENCE_RATE_LIMIT=off` disables them. Limits are in memory and per process: they stop one abusive client, not a distributed flood. Put a WAF or the proxy's own limits in front for that.
- **Hostile documents:** uploads are parsed in memory and never written to the application's directories. DOCX, XLSX and ZIP files that would expand beyond their limits (decompression bombs) are refused; PDFs are capped in pages; page previews are capped in pixels; spreadsheet XML is parsed with `defusedxml`. The PDF libraries (PyMuPDF, pypdf) parse untrusted input in the server process: keep them updated (Dependabot and `pip-audit` are configured) and run the service as an unprivileged user with a memory limit (systemd `MemoryMax=`, or a container limit), so a parser bug or an oversized job ends that process instead of the host.
- **Static files:** only files inside `static/` are served; absolute paths, `..` traversal (including percent-encoded), symlinks leading out and dotfiles are refused (`tests/test_server_security.py`).
- **Headers:** `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy: same-origin` on every response (URLs, including sign-in links, never leave the site); `Cache-Control: no-store` on API and sign-in responses. The interactive API docs (`/docs`, `/openapi.json`) are disabled. The policy still allows inline scripts, because the single-page UI uses them; the UI therefore escapes everything it renders, including AI answers and document text.
- **Paths:** `KEVIDENCE_HOME` (default `/var/www/kevidence`) sets where `data/` and `static/` are read from; `KEVIDENCE_STATE_DIR` (default `$KEVIDENCE_HOME/data/state`) holds `accounts.db` (users, sessions, activity, encrypted AI keys). The directory is created readable by the service user only. Back it up; never commit it. API answers do not reveal server paths.

### Reverse proxy

Pass **every** path to KEvidence: the page, `/auth/`, `/api/` and the static files. Do not let the web server serve `static/index.html` or `static/` itself. That would bypass sign-in, and the page would loop between itself and the sign-in page. Example for nginx at the root of a host:

```nginx
location / {
    proxy_pass http://127.0.0.1:3457;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 30m;   # raise it to upload whole dossiers for intake (the application accepts up to 400 MB)
}
```

Set `APP_URL` to exactly the address in the browser (e.g. `https://kevidence.example.org`, or `https://example.org/kevidence` with `location /kevidence/ { proxy_pass http://127.0.0.1:3457/; ... }`) and `TRUST_PROXY=1`. If `APP_URL` names another host, or says `https://` while the site is served over http, the session cookie never comes back and sign-in cannot complete.

### Accounts and AI configuration

**Sign-in** works like YachtPlan's email sign-in. A user enters any email address and receives a one-time link (valid 15 minutes, usable once, at most 5 per address per hour, 20 attempts per IP per 15 minutes). Opening the link shows a *Sign in* button, so mail scanners that prefetch links cannot use it up. The session lasts 14 days. Only SHA-256 digests of tokens are stored, and *Sign out* deletes the session on the server.

**Activity log:** each user sees their own sign-ins, analyses, exports, AI calls and configuration changes. Administrators listed in `KEVIDENCE_ADMIN_EMAILS` can see everyone's. Document content, questions and keys are never logged.

**AI configuration** works like ICDT_AISH's model targets. Each user saves one or more models: provider (OpenAI, Anthropic, Mistral AI, DeepSeek, Fireworks AI, OpenRouter, or an on-premises OpenAI-compatible endpoint), model identifier, optional endpoint and key. The saved models are listed with their URL and key hint, plus *Use*, *Test* and *Delete* buttons. The model marked *In use* serves every AI feature, so switching lets you compare answers, and the activity log records which model answered each call. A key is entered once per provider: leave it blank when adding another model of the same provider and the saved key is reused. Keys are encrypted with AES-256-GCM, bound to the user, and shown only as `****abcd`. *Load models* lists what the key can use (Fireworks' model list may not be available; type the id). User-supplied endpoints are checked against SSRF (see *Deployment security*): loopback, link-local, metadata and (unless allowed) private addresses are refused. OpenRouter forwards your text to the provider of the chosen model.

| Variable | Needed | Purpose |
|---|---|---|
| `KEVIDENCE_ENV=production` | production | Refuses to start unless the three settings below are safe. |
| `APP_URL` | production | Public `https://` URL, including any path prefix. Links and redirects are built from it, never from the `Host` header. |
| `KEVIDENCE_SECRET_KEY` | production | Long random string (32 characters or more; `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Encrypts stored AI keys and keys the IP hashes in the activity log. In development a random key is generated in the state directory. |
| `RESEND_API_KEY` (+ `MAIL_FROM`) | one mail transport | Send sign-in links through Resend. |
| `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS` (`starttls`/`ssl`/`none`) (+ `MAIL_FROM`) | one mail transport | Send through an SMTP server, e.g. an institutional relay. Used when `RESEND_API_KEY` is not set. |
| `KEVIDENCE_ADMIN_EMAILS` | optional | Comma-separated administrator emails (activity of all users). |
| `TRUST_PROXY=1` | behind a reverse proxy | Take the client IP from the last `X-Forwarded-For` hop. |
| `KEVIDENCE_ALLOW_PRIVATE_ENDPOINTS=1` | on-premises models | Allow AI endpoints on private networks (and plain http). |
| `KEVIDENCE_AI_TIMEOUT` | optional | Seconds per AI call (default 90). |
- **Dependencies:** no frontend frameworks or CDN scripts. Every Python package, transitive ones included, is pinned with its hash (`requirements.txt`), so an install cannot pull in anything that was not reviewed; CI actions are pinned to commits. `pip-audit` checks the lock on every push and weekly. See *Dependencies* below before accepting any update.

## Dependencies

`requirements.in` and `requirements-dev.in` list the direct dependencies. `requirements.txt` and `requirements-dev.txt` are generated from them and pin **every** package, transitive ones included, with hashes; `pip install -r requirements.txt` therefore installs exactly the reviewed set or fails. Upgrading an existing server with it also moves already-installed transitive packages (Starlette, h11, AnyIO, certifi…) to their reviewed versions.

Before accepting an update, Dependabot's or anyone's:

1. **Advisories for the new version and the old one.** Check the GitHub Advisory Database (`affects:<package>`) *and* the project's own *Security* tab: some projects publish repository advisories that never reach PyPI or `pip-audit` (pydantic GHSA-3r8g-cqwr-jr29 and GHSA-qpmf-fgh3-ff25 did not). Take the first release that fixes every advisory, not necessarily the one proposed.
2. **Changelog between the two versions**, for security fixes that have no advisory yet (pypdf, for one, publishes advisories days after the fix release).
3. **Release age and origin.** Prefer releases at least 7 days old. For a younger one (taken only for a security fix), check on PyPI that it carries a provenance attestation from the project's own repository, or that the project never had one.
4. **Transitive changes.** Regenerate the lock and read its diff: every new or changed package gets steps 1–3.

Regenerate the locks (Python 3.12, as CI):

```bash
pip install pip-tools
```

```bash
pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url -o requirements.txt requirements.in
```

```bash
pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url -o requirements-dev.txt requirements-dev.in
```

Pin a transitive package in `requirements.in` only to hold it back, with the reason and date in a comment. Do not install `httpx2` (Starlette's test client suggests it): it had four advisories in September 2026, and KEvidence does not need it.

## Optional data imports

KEvidence works with the bundled AOP-Wiki-derived data out of the box. OpenFoodTox and EPA bioactivity browsing require optional local indexes.

### Import OpenFoodTox

Download and index the latest OpenFoodTox Excel export from Zenodo:

```bash
python scripts/import_openfoodtox.py --download-latest --db data/openfoodtox.db
```

Or index a local export:

```bash
python scripts/import_openfoodtox.py --input /path/to/openfoodtox.xlsx --db data/openfoodtox.db
```

Custom path:

```bash
export OPENFOODTOX_SQLITE_PATH="/path/to/openfoodtox.db"
```

### Configure institutional IUCLID access for OpenFoodTox

If your organization imports OpenFoodTox `.i6z` dossiers into a local IUCLID 6 instance, configure:

```bash
export OPENFOODTOX_IUCLID_BASE_URL="https://your-iuclid-host.example/iuclid6"
export OPENFOODTOX_IUCLID_USERNAME="api-user"
export OPENFOODTOX_IUCLID_PASSWORD="api-password"
```

Optional deployment-specific paths:

```bash
export OPENFOODTOX_SUBSTANCES_PATH="/api/substances"
export OPENFOODTOX_DOSSIERS_PATH="/api/dossiers"
export OPENFOODTOX_DOCUMENTS_PATH_TEMPLATE="/api/dossiers/{dossier_uuid}/documents"
```

### Import EPA ToxCast/Tox21/ToxRefDB-style exports

Index an EPA/CompTox CSV, TSV, XLSX, or directory of exported files:

```bash
python scripts/import_epa_bioactivity.py --input /path/to/toxcast_or_toxrefdb_export.csv --db data/bioactivity.db
```

Custom path:

```bash
export BIOACTIVITY_SQLITE_PATH="/path/to/bioactivity.db"
```

---

## API endpoints

| Endpoint | Method | Purpose |
|---|---:|---|
| `/auth/signin`, `/auth/email`, `/auth/verify`, `/auth/logout` | GET/POST | Email sign-in flow and sign-out (HTML forms). |
| `/api/health` | GET | Health check and AOP count (no sign-in needed). |
| `/api/me` | GET | Signed-in user, administrator flag, their AI configuration (without key). |
| `/api/activity?scope=mine\|all` | GET | Activity log (own; `all` for administrators). |
| `/api/ai/providers`; `/api/ai/configs` (GET list, POST add and use); `/api/ai/configs/{id}/select`, `/test` (POST); `/api/ai/configs/{id}` (DELETE); `/api/ai/models` (POST) | GET/POST/DELETE | Per-user saved models, the one in use, connection test, provider model list. |
| `/api/aops` | GET | List or search AOPs by text, chemical, stressor, event, or adverse outcome. |
| `/api/aops/{aop_id}` | GET | Retrieve full AOP details, events, KERs, components, and evidence summary. |
| `/api/chat` | POST | Contextual Evidence Assistant grounded in AOP data and workbench state. |
| `/api/assess` | POST | Evidence-to-decision assessment for a chemical/stressor and context. |
| `/api/quantitative-assessment` | POST | Screening BER/MOE/HQ calculation from NAM POD and exposure inputs. |
| `/api/woe` | GET | Structured weight-of-evidence summary for a chemical and optional AOP ID. |
| `/api/openfoodtox/status` | GET | OpenFoodTox integration status and setup guidance. |
| `/api/openfoodtox/query` | POST | Query local OpenFoodTox SQLite index or configured IUCLID instance. |
| `/api/bioactivity/status` | GET | EPA bioactivity index status and setup guidance. |
| `/api/bioactivity/search` | POST | Search locally indexed ToxCast/Tox21/ToxRefDB-style AC50/POD records. |
| `/api/domains` | GET | Registered domains, whether each is grounded, its guidance sources and sanitisation sector. |
| `/api/qps?domain=&q=` | GET | Taxa named in `q` that appear in the bundled (partial) QPS cycle dataset. |
| `/api/characterisation/export.docx` | POST | JSON `{markdown, product_name}` → Word file of that Markdown (max 3 M characters). |
| `/api/characterisation/guidance?domain=` | GET | Characterisation requirement catalogue and grounding status against the guidance text, for the domain and each of its sources. |
| `/api/characterisation/guidance.pdf?domain=&source=` | GET | A bundled guidance PDF of the domain (`source` = catalogue id; default the primary). |
| `/api/characterisation/guidance.pdf` | GET | The bundled FEEDAP guidance PDF (unmodified). |
| `/api/characterisation/analyse` | POST | Multipart: `files` (repeatable), `urls` (newline-separated), `meta` (JSON: `product_name`, `applicant`, `dossier_ref`, `authorisation`, `product_form`, `routes`, `production_types`, `additive_type`, `formulations`, `components`), `allow_external_llm`, `domain`. Returns requirement evaluations, gap summary and `markdown`. |
| `/api/completeness/rules` | GET | Sources of the completeness check and their anchoring status; application types. |
| `/api/completeness/check` | POST | Multipart: `files` (repeatable; files or a ZIP), `domain`, `application_type` (`new`/`modification`/`renewal`), `applicant`, `dossier_ref`, `pre_application_ids`, `notified_study_ids`. Returns verdict, checks with citations, studies, personal-data hits, file inventory, `report_markdown`, `letter_markdown`. |
| `/api/completeness/file` | POST | Multipart: the same `files` and a `path`. Returns that file of the dossier (used to open it in Publication). |
| `/api/sanitisation/rules?sector=&domain=` | GET | Rules of EFSA's practical arrangements, their grounding status, and which apply to the sector (Annex a-h). |
| `/api/sanitisation/rules.pdf` | GET | The bundled EFSA decision (unmodified). |
| `/api/sanitisation/analyse` | POST | Multipart: `file` (PDF), `sector`, `domain`, `applicant`, `applicant_address`, `requests` (lines `text \| basis`), `allow_external_llm`. Returns proposals with rule, legal basis and boxes, page previews, warnings. |
| `/api/sanitisation/locate` | POST | Multipart: `file`, `text`, `basis`, `sector`. Every occurrence of a text, as proposals. |
| `/api/sanitisation/apply` | POST | Multipart: `file`, `redactions` (JSON list of `{page, rects, text, label, ...}`), `label_boxes`, `sector`. Returns the sanitised PDF (base64), the verification report and the sanitisation record. |

---

## Example quantitative request

```json
POST /api/quantitative-assessment
{
  "chemical": "rotenone",
  "aop_id": 3,
  "nam_results": [
    {
      "assay": "complex I inhibition assay",
      "mapped_event_id": 887,
      "pod_type": "AC50",
      "pod_value": 0.3,
      "pod_unit": "uM"
    }
  ],
  "exposure": {
    "value": 0.01,
    "unit": "uM plasma equivalent"
  }
}
```

Example output fields include:

```json
{
  "bioactivity_exposure_ratio": 30,
  "margin_of_exposure": 30,
  "hazard_quotient": 0.0333,
  "quantitative_confidence": "screening only",
  "validation_status": "prototype_screening_calculator"
}
```

---

## Scientific and regulatory caveats

KEvidence is an independent prototype decision-support workbench, developed without the endorsement of any public administration or institution. It should not be used as a stand-alone regulatory conclusion engine.

Important limitations:

- AOP-Wiki evidence is used to structure biological plausibility, not to prove risk by itself.
- Quantitative screening outputs depend entirely on the quality and relevance of submitted PODs, exposure estimates, IVIVE assumptions, and selected units.
- The default BER/MOE/HQ interpretation is heuristic and not a validated regulatory threshold framework.
- Imported OpenFoodTox, ToxCast/Tox21, and ToxRefDB records require source review, provenance tracking, assay-quality checks, and expert interpretation.
- NAM-to-key-event mapping by text overlap is a prioritization aid, not a validated mechanistic mapping.
- The Evidence Assistant can draft and explain but should not be treated as a source of regulatory truth.
- Characterisation locates evidence; it does not judge adequacy or compliance. "Not located" can reflect extraction limits (scanned PDFs, images, unusual tables) as well as true data gaps.
- Sanitisation proposes what to mask; whether information is confidential is decided by EFSA (Art. 11 of its practical arrangements). Pages without a text layer and text inside images (other than signatures) are not analysed. Check every sanitised PDF before publication.

---

## Data provenance and attribution

- **AOP-Wiki** ([aopwiki.org](https://aopwiki.org), OECD AOP Knowledge Base): the bundled export (`data/aop-wiki-xml.gz`, the `aop_ke_*.tsv` tables) and cached AOP texts (`data/aops/`) are AOP-Wiki content by the respective AOP authors, licensed **CC BY-SA 4.0** (<https://creativecommons.org/licenses/by-sa/4.0/>). Changes: converted into KEvidence's tables, and AOPs not licensed BY-SA removed. Only BY-SA AOPs are redistributed or shown: AOPs marked "All rights reserved" (reuse needs the authors' written permission) or "Open for adoption" are removed by `scripts/filter_aopwiki_licences.py` (record in `data/aopwiki_licence_filter.json`), and the server also excludes them from any freshly downloaded export. Content derived from AOP-Wiki text must be shared under CC BY-SA.
- OpenFoodTox content, when imported, should be attributed to EFSA and the source export package.
- EPA ToxCast/Tox21/ToxRefDB-style content, when imported, should retain the original source, export version, and retrieval date.
- Generated KEvidence outputs should clearly distinguish source data, user-supplied values, heuristic calculations, and LLM-generated summaries.

---

## Development notes

Recommended checks before opening a pull request:

```bash
python -m py_compile server.py accounts.py ai.py netguard.py limits.py completeness.py characterisation.py sanitisation.py scripts/import_openfoodtox.py scripts/import_epa_bioactivity.py scripts/make_sanitisation_demo.py scripts/make_completeness_demo.py scripts/filter_aopwiki_licences.py
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

Extract and syntax-check the embedded frontend script if Node.js is available:

```bash
python - <<'PY' > /tmp/kevidence-index.js
from pathlib import Path
s = Path('static/index.html').read_text()
start = s.index('<script>') + len('<script>')
end = s.index('</script>', start)
print(s[start:end])
PY
node --check /tmp/kevidence-index.js
```

Check whitespace:

```bash
git diff --check
```

---

## Roadmap ideas

Potential future improvements include:

- Curated NAM-to-key-event mapping tables.
- Direct integration with validated IVIVE/HTTK or PBPK workflows.
- Source-specific parsers for official ToxCast/Tox21 and ToxRefDB release formats.
- Configurable regulatory thresholds by jurisdiction, endpoint, and use case.
- Word/PDF export of the full assessment (characterisation already exports to Markdown and Word).
- More domains (food additives, enzymes, novel foods, pesticides) and production-strain characterisation for microbial feed additives.
- OCR for scanned dossiers.
- User authentication and assessment-session persistence.
- Tests for backend scoring, importers, and frontend workflow behaviour (grounding, characterisation, sanitisation, accounts, AI configuration, licensing and HTTP security are covered).

---

## Contributing

See *Contribute* at the top for who we are looking for. Useful contributions include:

- Bug reports and reproducible examples.
- Improved importers for specific official data releases.
- Tests for backend assessment and quantitative functions.
- UI/UX improvements for regulatory workflows.
- Documentation and example datasets.
- Scientific review of scoring logic, uncertainty labels, and NAM/AOP mapping assumptions.
- New guidance domains: guidance PDFs plus a catalogue quoting them verbatim, registered in `data/guidance/domains.json`.

Before contributing, please open an issue or discussion describing the proposed change, especially for scientific scoring, regulatory interpretation, or data-source integrations.

Feature requests can also be submitted from the in-app **Guide & samples** tab, by opening the GitHub repository at <https://github.com/devalier/KEvidence>, or by emailing <kevidence@devalier.com>.

---

## License

KEvidence is licensed under the **GNU Affero General Public License v3.0** ([`LICENSE`](LICENSE)). If you run a modified version as a network service, you must offer its users the complete corresponding source code (AGPL §13); the app shows a *Source code* link in its footer for this. Releases before this change were published under GPL-3.0. Dependencies keep their own licences (PyMuPDF: AGPL-3.0).

Third-party datasets retain their own attribution and reuse requirements. Always preserve source attribution and do not imply endorsement by OECD, EFSA, EPA, ECHA, or other organizations unless explicitly authorized.
