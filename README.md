# KEvidence

**An open-source prototype workbench for food and feed safety risk assessment, built in the open so that public administrations and risk assessors can test it, challenge it and build on it.**

KEvidence follows a regulatory scientific assessment from dossier to publication. A scientific officer uploads the applicant's documents and KEvidence:

1. **characterises the substance or product** against the applicable guidance, citing document and page for every value and listing data gaps;
2. **structures hazard and exposure evidence** along the four Codex risk-assessment steps (Adverse Outcome Pathways, OpenFoodTox reference points, NAM points of departure, exposure estimates, screening margins);
3. **drafts the uncertainty analysis and the scientific opinion** for expert refinement;
4. **prepares documents for publication** under the Transparency Regulation, masking confidential information and personal data according to EFSA's rules.

**Grounded, not generative.** Every requirement KEvidence checks is quoted verbatim from official guidance bundled with the code, and the tests fail if a quote or page reference drifts from the source PDF. The assistant answers only from that guidance and says so when it cannot. Extraction runs locally; any use of an external LLM is opt-in per request and its output is checked against the documents.

**It assists experts; it does not decide.** Adequacy, safety conclusions and confidentiality decisions stay with the risk assessor and the competent authority.

**Status:** prototype. The most developed domain is EU **feed additives** (EFSA FEEDAP guidance: identity and characterisation, with consumer, target-species, environment, microorganism, renewal, QPS/WGS and VICH sources). The sanitisation step covers all sectors of the EFSA rules (General Food Law, GMOs, feed additives, smoke flavourings, food contact materials, food improvement agents, plant protection products, novel foods).

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
KEVIDENCE_HOME=$PWD python server.py      # http://127.0.0.1:3457 — OPENAI_API_KEY optional (assistant, opt-in AI steps)
```

Then try the fictional demo material (also linked from the *Guide & questions* tab):

- **Characterisation:** upload `static/samples/characterisation_demo_dossier.md` in *0. Substance characterisation* and click *Characterise from documents*.
- **Sanitisation:** upload `static/samples/sanitisation_demo_study_report.pdf` in *Publication: sanitisation*, applicant `Demo Feed Additives S.A.`, and click *Propose redactions*.

---

## How the workflow is organised

**Risk analysis** is the whole governance cycle — risk assessment, risk management, and risk communication (EU General Food Law, Regulation (EC) No 178/2002). KEvidence supports the scientific **risk assessment** part, which Codex defines as four steps. The workbench follows that structure, with problem formulation as the practical framing step:

- **Problem formulation** — define the substance/stressor, product domain, use scenario, endpoint of concern, and decision context. Not one of the four formal Codex steps, but it frames all of them.
0. **Substance / product characterisation** (feed additives) — establish exactly what is being assessed: identity and composition of the additive and of *each component* of a product, mixture or formulation, impurities, physical properties, manufacturing, stability, homogeneity, conditions of use and methods of analysis, grounded in the EFSA FEEDAP *Guidance on the identity, characterisation and conditions of use of feed additives* (EFSA Journal 2017;15(10):5023). The MVP covers chemical characterisation.
1. **Hazard identification** — *can this agent cause harm?* Search and select candidate AOPs by chemical, stressor, key event, adverse outcome, or AOP ID.
2. **Hazard characterisation** — *what is the nature and severity of the harm, and at what dose?* Review MIEs, key events, KERs, weight of evidence, and quantitative understanding; pull reference points and health-based guidance values from OpenFoodTox; and set a dose-response point of departure (POD) from NAM data (optionally browsing locally indexed EPA ToxCast/Tox21/ToxRefDB-style exports).
3. **Exposure assessment** — *who is exposed, how much, how often, and by which route?* Record concentration in food/feed × consumption × population × use conditions, and the resulting exposure estimate.
4. **Risk characterisation** — *given hazard and exposure, what is the risk?* Integrate the POD with the exposure estimate to calculate screening margins (BER/MOE) and a hazard-quotient-style ratio.

The workbench then supports **uncertainty analysis** (confidence summaries, key uncertainties, critical data gaps, recommended next data) and a **scientific opinion draft** that can be refined with the Evidence Assistant and handed to risk managers.

At the end, **publication — sanitisation** prepares documents for publication under the Transparency Regulation: confidential information and personal data are masked according to EFSA's practical arrangements concerning transparency and confidentiality.

> **Hazard is not risk.** Hazard is the intrinsic potential for harm; risk is that hazard under actual exposure conditions. KEvidence keeps the two separate and does not make risk-management decisions.

---

## Key features

### Step 0 — feed additive characterisation (chemical MVP)

Assists EFSA scientific officers with the characterisation section of a feed additive assessment.

- **Input:** confidential applicant documents — uploads (PDF, DOCX, XLSX, CSV/TSV, TXT/MD, JSON, HTML) and/or URLs (a PDF/DOCX/XLSX link, or an HTML page whose linked documents are followed). Product form, routes of administration, production type, additive type, current authorisation, preparations/formulations under application, and each component (name, CAS, role).
- **Output (on screen, as Markdown and as a Word file):** the *Download Word (.docx)* button converts exactly the Markdown on screen (`docx_export.py`, `POST /api/characterisation/export.docx`; nothing is stored), so the two cannot differ. Tables keep their header rows across pages and have content-based column widths; footnotes appear as numbered notes under their table; the page header marks it as a draft for scientific-officer verification. Content:
  1. a draft of the opinion's characterisation section in the FEEDAP opinion layout: §1.1.1 *Characterisation of the additive* with the specifications, **Table 1** (product/active substance) and, when preparations are listed, **Table 2** (one column per preparation) — batch-to-batch variation as average (range) [number of batches], substance-related impurities and residual solvents as ranges, `<` below the LOQ, `-` not analysed, footnotes naming the source documents — followed by facts located for the scientific officer's conclusion (e.g. "3/3 batch values meet the specification ≥ 99.5 %") and, for fermentation products, the viable-cell and DNA fields; **Appendix A** with other impurities and physico-chemical/technological properties; §1.1.2 (production microorganism) as an out-of-scope stub;
  2. the data-gap analysis;
  3. an evidence map against Section 2 of the guidance (2.1 Identity … 2.6 Methods of analysis).

  KEvidence never writes the Panel's conclusions; it leaves an explicit placeholder for the scientific officer. The public template (`data/guidance/feed/characterisation_template.md`) reproduces only the layout conventions visible in published FEEDAP opinions. An institution can use its own internal template by saving it as `data/guidance/feed/local/characterisation_template.md` (git-ignored) or by setting `KEVIDENCE_CHARACTERISATION_TEMPLATE`; the available placeholders are documented at the top of the public template.
- **Data-gap analysis:** each of 27 guidance requirements is marked *evidence located*, *partially addressed*, *not located*, *applicability to confirm*, *scientific-officer review* or *not applicable*. Quantitative checks come straight from the guidance: ≥ 5 batches for the specification and ≥ 3 for impurities (§2.1.3, §2.1.4), analyses within the last 5 years, statements of compliance flagged (not sufficient on their own), dusting potential in ≥ 3 batches (§2.1.5), shelf life in ≥ 3 batches (§2.4.1.1), premixture ≥ 6 months and feed ≥ 3 months (§2.4.1.2), water ≥ 48 h (§2.4.1.3), homogeneity ≥ 10 subsamples (§2.4.2). The minimum impurity set depends on production type (chemical synthesis, fermentation, plant-derived, animal-derived, mineral; §2.1.4). Exemptions (flavouring compounds, silage additives, colourants, mineral-based additives) are applied where the guidance gives them. Applicant justifications for omissions are surfaced (guidance p.5: reasons should be given for any omission).
- **Grounding:** the requirement catalogue (`data/guidance/feed/feedap_2017_5023_chemical_requirements.json`) cites the guidance section and page and quotes it verbatim for every requirement. The guidance PDF is bundled unmodified (CC BY-ND 4.0) and every requirement is re-anchored against its text at start-up; the UI shows how many are anchored and the PDF is served at `/api/characterisation/guidance.pdf`. `tests/test_characterisation.py` fails if any quote, page reference or anchor drifts from the guidance. In step 0 the Evidence Assistant answers only from the guidance entries and refuses questions it cannot ground.
- **Domains:** grounding is per domain. The *Domain* selector at the top of the page lists the domains registered in `data/guidance/domains.json` (today only *Feed additives*); the choice is sent with every step 0 request, and the backend loads that domain's catalogues, PDFs and template from `data/guidance/<domain>/`. An unknown or unloaded domain is rejected (HTTP 400) and the assistant refuses to answer. It never falls back to another domain's guidance. To add a domain: create `data/guidance/<domain>/` with a primary catalogue, PDFs and template, and register it in `domains.json`.
- **Supporting sources:** besides the primary catalogue that drives the gap analysis, a domain lists supporting catalogues (`entries` with the same verbatim-quote and page-anchor checks) that ground the assistant. Each entry is tagged with the workflow step it informs (`steps`: `characterisation` by default, `hazard-char`, `exposure`, `risk-char`); the assistant in a step answers only from that step's entries and tells the user which step holds the answer otherwise. Feed has nine, listed in the order of the project's reference list: EFSA 2024 WGS statement (e8912; reporting expectations, not assessment criteria); BIOHAZ 2023 QPS AMR statement (8323, revised 2025); BIOHAZ 2026 QPS list (e9823; principles and qualifications); FEEDAP 2017 consumer safety (5022; characterisation items, safe dose, consumption, residues, exposure method, MOS, MRLs); FEEDAP 2017 target species (5021; presumed safety, safe feed concentration, default feed intakes, TTC, tolerance-study test item); FEEDAP 2018 microorganisms (5206); FEEDAP 2019 environment (5648; Phase I screen and triggers, Phase II logic, physico-chemical data); FEEDAP 2021 renewal (6340); VICH GL18(R2) residual solvents. Not yet bundled: DECOS 2010 (endotoxins), FEEDAP 2023 user safety, FEEDAP 2024 efficacy, the 2025 Scientific Committee microorganism guidance.
- **Structured datasets** (`domains.json` → `datasets`), each extracted from the bundled PDFs and checked against them by the tests: QPS cycle assessments (Tables 6 and 7 of the 2026 opinion; **partial**, 31 units assessed October 2022 to September 2025 plus the excluded groups; it is not the QPS list, and a missing species means nothing; `GET /api/qps`); FEEDAP 2018 MIC cut-offs (Table 2); VICH GL18(R2) solvent limits (Tables 1-4). Reported residual-solvent values in the dossier are compared with the VICH Option 1 limits (10 g/day basis) and shown as facts in the characterisation, never as a conclusion.
- **Traceability:** extraction is deterministic (pattern-based); every value carries a `D<n> p.<page>` citation. Statuses say whether evidence was *located*, not whether it is adequate — adequacy stays with the scientific officer.
- **Confidentiality:** documents are processed in memory for one request and are not stored. Extraction and gap analysis run locally. Optional LLM drafting of section narratives sends extracted excerpts to the OpenAI API and is **off unless ticked per request**; every number in an LLM narrative is checked against the dossier excerpts and untraced numbers are flagged.
- **Limits:** scanned PDFs need OCR first; dossier portals rendered by JavaScript (e.g. Open EFSA) cannot be read by URL — download and upload the documents. Production-strain characterisation (§2.2.1.2, §2.2.2.2; FEEDAP microorganism guidance, EFSA Journal 2018;16(3):5206) is out of scope; fermentation-related impurity requirements of §2.1.4 are included.

A fictional, deliberately incomplete demo dossier is provided at `static/samples/characterisation_demo_dossier.md` (also linked from the in-app *Guide & questions* tab).

### Publication — sanitisation under the Transparency Regulation

Regulation (EU) 2019/1381 amended the General Food Law (Regulation (EC) No 178/2002, Art. 38-39e): EFSA proactively publishes the documents supporting its scientific outputs, with confidential information and personal data masked. KEvidence prepares the non-confidential version of a PDF.

- **Rules:** EFSA's *Decision of the Executive Director laying down practical arrangements concerning transparency and confidentiality* (ver. 2, 18.01.2021, applicable from 27 March 2021), bundled unmodified at `data/guidance/transparency/` and served at `/api/sanitisation/rules.pdf`. The catalogue (`efsa_2021_pa_transparency_confidentiality_rules.json`) encodes the definition of sanitisation (Art. 3(1)(c)), the personal-data rule for non-confidential versions (Art. 4(5)), publication of updated versions (Art. 6), the closed list and minimum content of requests (Art. 9(4), 10), blackening (Art. 13(2)), review where foreseeable health effects are concerned (Art. 14) and non-disclosure pending decisions (Art. 16(3)), plus the **Annex closed list by sector**: (a) General Food Law, (b) GM food/feed, (c) feed additives, (d) smoke flavourings, (e) food contact materials, (f) food additives/enzymes/flavourings, (g) plant protection products, (h) novel foods. Every rule quotes the decision verbatim; `tests/test_sanitisation.py` fails if a quote, page or anchor drifts. The sector defaults from the domain (`transparency_sector` in `domains.json`; feed → (c)).
- **Input:** one PDF (confidential), the sector, the applicant's name and address (public under Art. 39e(1)(a)), and optionally the items of the confidentiality request or decision, one per line (`text | legal basis`).
- **Proposals** (each with its rule, legal basis, reason and boxes on the page):
  - *personal data*, selected by default — names with study roles or titles, e-mails, phone numbers, signature images; study personnel of GLP/animal studies under Art. 39e(2), others under Art. 39e(1)/Art. 4(5); street addresses proposed but not selected (personal or organisational?);
  - *request/decision items*, located verbatim and selected;
  - *Annex candidates* — sentences matching an Annex item of the sector (manufacturing process, commercial links, sourcing/market share, quantitative composition, efficacy study plan, impurity specifications, ...) — **not** selected: they are masked only if claimed or granted, and never if relevant to the safety assessment.
  - Exceptions are applied: the applicant's name and address and authors in reference lists are never proposed.
- **AI review (optional, per request):** sends the page text to the OpenAI API to find personal data and Annex items the rules miss and to locate request items described in words. Every AI finding must name a rule that applies to the sector and its text must be found on the cited page; otherwise it is rejected and counted. Findings the AI marks as relevant to the safety assessment are flagged and left unselected. Off unless ticked.
- **Review:** page previews with the boxes overlaid and a list; click to toggle; bulk actions; "mask more text" finds every occurrence of a string.
- **Output:** true redaction with PyMuPDF (the text, image pixels and links under each box are removed from the file, not covered), optional legal-basis label in each box; all comments, form fields, mailto links, attachments, JavaScript, document metadata and XMP removed; the file is rewritten (no incremental update). The output is re-read to **verify** that the masked text is gone from the pages where it was masked, and copies left elsewhere are reported. A sanitisation record (Markdown) lists every masked item with its legal basis — it contains the masked text and is confidential.
- **Limits:** pages without a text layer (scans) cannot be analysed — OCR first; text in images other than signatures is not detected; the decision on confidentiality stays with EFSA (Art. 11 of the arrangements). PyMuPDF is AGPL-3.0, like KEvidence.
- A fictional demo study report is at `static/samples/sanitisation_demo_study_report.pdf` (generated by `scripts/make_sanitisation_demo.py scripts/filter_aopwiki_licences.py`).

### AOP-Wiki knowledge base

KEvidence builds a local SQLite database from bundled AOP-Wiki-derived TSV and XML data. The local database includes:

- AOP IDs, titles, molecular initiating events, adverse outcomes, and OECD status where available.
- Key events and event types.
- Key Event Relationships (KERs).
- KER-level evidence and quantitative understanding codes.
- Event components and ontology identifiers.
- Chemical/stressor mappings extracted from the bundled AOP-Wiki XML file.

### Risk assessment workbench UI

The frontend is a single page (no frameworks, no CDN) with one tab per step: problem formulation, 0. substance characterisation, the four Codex steps (hazard identification, hazard characterisation, exposure assessment, risk characterisation), uncertainty analysis, scientific opinion, publication: sanitisation, and a guide with the demo material. A domain selector in the header sets which guidance grounds the assessment, and the Evidence Assistant sits beside every step except characterisation.

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

The Evidence Assistant uses structured workbench context when answering questions. In the guidance-grounded steps (0. characterisation, 2-4 where the domain has entries for them, and publication: sanitisation) it answers **only** from the bundled guidance entries supplied to it, cites document, section and page, and refuses or redirects to the right step when no entry matches. In the AOP steps, a short prompt such as “Explain AOP” is answered with the current chemical, selected AOP, use case, route, population, OpenFoodTox summary and quantitative context.

---

## Repository structure

```text
.
├── server.py                          # FastAPI backend: AOP knowledge base, assessment logic, all API routes
├── characterisation.py                # Step 0: document ingestion, guidance-grounded characterisation and gap analysis
├── docx_export.py                     # Markdown → Word (.docx) for the step 0 output
├── sanitisation.py                    # Publication: redaction proposals, true redaction and verification
├── static/
│   ├── index.html                     # Single-page workbench UI
│   └── samples/                       # Fictional demo dossier and study report, CSV templates
├── scripts/
│   ├── import_openfoodtox.py          # EFSA OpenFoodTox Excel/CSV/XLSX importer
│   ├── import_epa_bioactivity.py      # EPA ToxCast/Tox21/ToxRefDB-style importer
│   ├── filter_aopwiki_licences.py     # Keeps only CC BY-SA AOP-Wiki content in data/
│   └── make_sanitisation_demo.py      # Builds the fictional sanitisation demo PDF
├── data/
│   ├── guidance/
│   │   ├── domains.json               # Domain registry (id, label, directory, sources, datasets, sanitisation sector)
│   │   ├── feed/                      # Feed-additive domain: guidance PDFs (unmodified) + verbatim-quoted catalogues,
│   │   │                              #   structured datasets (QPS cycle, MIC cut-offs, VICH solvents), output template,
│   │   │                              #   local/ (git-ignored) for an institution's own template
│   │   └── transparency/              # EFSA practical arrangements on transparency & confidentiality (PDF + rules catalogue)
│   ├── aop-wiki-xml.gz                # AOP-Wiki export (CC BY-SA AOPs only)
│   ├── aop_ke_mie_ao.tsv, aop_ke_ker.tsv, aop_ke_ec.tsv   # AOP events, KERs, event components
│   ├── aopwiki_licence_filter.json    # Record of AOP-Wiki content removed for licence reasons
│   └── aops/                          # Cached AOP text excerpts
├── tests/                             # Grounding guards, step 0, sanitisation, licensing, Word export, HTTP security
├── .github/workflows/                 # pytest and pip-audit on every push
├── requirements.txt, requirements-dev.txt
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

### 4. Configure OpenAI access

KEvidence uses the OpenAI API for the Evidence Assistant and for the opt-in AI steps (narrative drafting in step 0, AI review in sanitisation). Everything else runs without it.

```bash
export OPENAI_API_KEY="your-api-key"
```

Optional model override (default `gpt-4o-mini`):

```bash
export LLM_MODEL="gpt-4o-mini"
```

### 5. Run the application

```bash
python server.py
```

By default, the app runs with Uvicorn on:

```text
http://127.0.0.1:3457
```

---

## Deployment security

- **Authentication:** every endpoint is open unless you set `KEVIDENCE_AUTH_USER` and `KEVIDENCE_AUTH_PASSWORD` (HTTP Basic, checked in constant time on every route) or put an authenticating reverse proxy in front. Serve over HTTPS only. Step 0 and the sanitisation step handle confidential dossiers; do not expose them without authentication.
- **CORS:** off by default (the UI is same-origin). To allow other origins, set `KEVIDENCE_CORS_ORIGINS` to a comma-separated list.
- **Static files:** only files inside `static/` are served; absolute paths, `..` traversal (including percent-encoded), symlinks leading out and dotfiles are refused (`tests/test_server_security.py`).
- **Headers:** `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` on every response. The interactive API docs (`/docs`, `/openapi.json`) are disabled.
- **Paths:** `KEVIDENCE_HOME` (default `/var/www/kevidence`) sets where `data/` and `static/` are read from.
- **Dependencies:** no frontend frameworks or CDN scripts; Python dependencies are pinned and checked with `pip-audit` in CI.

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
| `/api/health` | GET | Health check and AOP count. |
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
| `/api/domains` | GET | Registered domains and their guidance sources. |
| `/api/qps?domain=&q=` | GET | Taxa named in `q` that appear in the bundled (partial) QPS cycle dataset. |
| `/api/characterisation/export.docx` | POST | JSON `{markdown, product_name}` → Word file of that Markdown (max 3 M characters). |
| `/api/characterisation/guidance?domain=` | GET | Step 0 requirement catalogue and grounding status against the guidance text, for the domain and each of its sources. |
| `/api/characterisation/guidance.pdf?domain=&source=` | GET | A bundled guidance PDF of the domain (`source` = catalogue id; default the primary). |
| `/api/characterisation/guidance.pdf` | GET | The bundled FEEDAP guidance PDF (unmodified). |
| `/api/characterisation/analyse` | POST | Multipart: `files` (repeatable), `urls` (newline-separated), `meta` (JSON: `product_name`, `applicant`, `dossier_ref`, `authorisation`, `product_form`, `routes`, `production_types`, `additive_type`, `formulations`, `components`), `allow_external_llm`, `domain`. Returns requirement evaluations, gap summary and `markdown`. |
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

KEvidence is a prototype decision-support workbench. It should not be used as a stand-alone regulatory conclusion engine.

Important limitations:

- AOP-Wiki evidence is used to structure biological plausibility, not to prove risk by itself.
- Quantitative screening outputs depend entirely on the quality and relevance of submitted PODs, exposure estimates, IVIVE assumptions, and selected units.
- The default BER/MOE/HQ interpretation is heuristic and not a validated regulatory threshold framework.
- Imported OpenFoodTox, ToxCast/Tox21, and ToxRefDB records require source review, provenance tracking, assay-quality checks, and expert interpretation.
- NAM-to-key-event mapping by text overlap is a prioritization aid, not a validated mechanistic mapping.
- The Evidence Assistant can draft and explain but should not be treated as a source of regulatory truth.
- Step 0 characterisation locates evidence; it does not judge adequacy or compliance. "Not located" can reflect extraction limits (scanned PDFs, images, unusual tables) as well as true data gaps.
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
python -m py_compile server.py characterisation.py sanitisation.py scripts/import_openfoodtox.py scripts/import_epa_bioactivity.py scripts/make_sanitisation_demo.py scripts/filter_aopwiki_licences.py
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
- Word/PDF export of the full assessment (step 0 already exports to Markdown and Word).
- More domains (food additives, enzymes, novel foods, pesticides) and production-strain characterisation for microbial feed additives.
- OCR for scanned dossiers.
- User authentication and assessment-session persistence.
- Tests for backend scoring, importers, and frontend workflow behaviour (grounding, step 0, sanitisation, licensing and HTTP security are covered).

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

Feature requests can also be submitted from the in-app **Guide & questions** tab, by opening the GitHub repository at <https://github.com/devalier/KEvidence>, or by emailing <kevidence@devalier.com>.

---

## License

KEvidence is licensed under the **GNU Affero General Public License v3.0** ([`LICENSE`](LICENSE)). If you run a modified version as a network service, you must offer its users the complete corresponding source code (AGPL §13); the app shows a *Source code* link in its footer for this. Releases before this change were published under GPL-3.0. Dependencies keep their own licences (PyMuPDF: AGPL-3.0).

Third-party datasets retain their own attribution and reuse requirements. Always preserve source attribution and do not imply endorsement by OECD, EFSA, EPA, ECHA, or other organizations unless explicitly authorized.
