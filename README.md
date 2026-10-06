# KEvidence

**KEvidence** is an open-source, AOP-guided regulatory risk assessment workbench. It helps scientific officers, toxicologists, NAM developers, and risk assessors move from a chemical or biological concern to structured Adverse Outcome Pathway (AOP) evidence, hazard hypotheses, confidence statements, uncertainty/data-gap summaries, and screening-level quantitative comparisons.

KEvidence is not intended to replace expert regulatory judgement. It is a decision-support prototype that combines local AOP-Wiki-derived data, optional OpenFoodTox exports, optional EPA ToxCast/Tox21/ToxRefDB-style exports, and an LLM-assisted evidence assistant.

---

## What KEvidence does

KEvidence turns AOP-Wiki data into a workflow-oriented risk assessment interface. **Risk analysis** is the whole governance cycle — risk assessment, risk management, and risk communication (EU General Food Law, Regulation (EC) No 178/2002). KEvidence supports the scientific **risk assessment** part, which Codex defines as four steps. The workbench follows that structure, with problem formulation as the practical framing step:

- **Problem formulation** — define the substance/stressor, product domain, use scenario, endpoint of concern, and decision context. Not one of the four formal Codex steps, but it frames all of them.
0. **Substance / product characterisation** (feed additives) — establish exactly what is being assessed: identity and composition of the additive and of *each component* of a product, mixture or formulation, impurities, physical properties, manufacturing, stability, homogeneity, conditions of use and methods of analysis, grounded in the EFSA FEEDAP *Guidance on the identity, characterisation and conditions of use of feed additives* (EFSA Journal 2017;15(10):5023). The MVP covers chemical characterisation.
1. **Hazard identification** — *can this agent cause harm?* Search and select candidate AOPs by chemical, stressor, key event, adverse outcome, or AOP ID.
2. **Hazard characterisation** — *what is the nature and severity of the harm, and at what dose?* Review MIEs, key events, KERs, weight of evidence, and quantitative understanding; pull reference points and health-based guidance values from OpenFoodTox; and set a dose-response point of departure (POD) from NAM data (optionally browsing locally indexed EPA ToxCast/Tox21/ToxRefDB-style exports).
3. **Exposure assessment** — *who is exposed, how much, how often, and by which route?* Record concentration in food/feed × consumption × population × use conditions, and the resulting exposure estimate.
4. **Risk characterisation** — *given hazard and exposure, what is the risk?* Integrate the POD with the exposure estimate to calculate screening margins (BER/MOE) and a hazard-quotient-style ratio.

The workbench then supports **uncertainty analysis** (confidence summaries, key uncertainties, critical data gaps, recommended next data) and a **scientific opinion draft** that can be refined with the Evidence Assistant and handed to risk managers.

> **Hazard is not risk.** Hazard is the intrinsic potential for harm; risk is that hazard under actual exposure conditions. KEvidence keeps the two separate and does not make risk-management decisions.

---

## Key features

### Step 0 — feed additive characterisation (chemical MVP)

Assists EFSA scientific officers with the characterisation section of a feed additive assessment.

- **Input:** confidential applicant documents — uploads (PDF, DOCX, XLSX, CSV/TSV, TXT/MD, JSON, HTML) and/or URLs (a PDF/DOCX/XLSX link, or an HTML page whose linked documents are followed). Product form, routes of administration, production type, additive type, current authorisation, preparations/formulations under application, and each component (name, CAS, role).
- **Output (Markdown, on screen and downloadable):**
  1. a draft of the opinion's characterisation section in the FEEDAP opinion layout: §1.1.1 *Characterisation of the additive* with the specifications, **Table 1** (product/active substance) and, when preparations are listed, **Table 2** (one column per preparation) — batch-to-batch variation as average (range) [number of batches], substance-related impurities and residual solvents as ranges, `<` below the LOQ, `-` not analysed, footnotes naming the source documents — followed by facts located for the scientific officer's conclusion (e.g. "3/3 batch values meet the specification ≥ 99.5 %") and, for fermentation products, the viable-cell and DNA fields; **Appendix A** with other impurities and physico-chemical/technological properties; §1.1.2 (production microorganism) as an out-of-scope stub;
  2. the data-gap analysis;
  3. an evidence map against Section 2 of the guidance (2.1 Identity … 2.6 Methods of analysis).

  KEvidence never writes the Panel's conclusions; it leaves an explicit placeholder for the scientific officer. The public template (`data/guidance/characterisation_template.md`) reproduces only the layout conventions visible in published FEEDAP opinions. An institution can use its own internal template by saving it as `data/guidance/local/characterisation_template.md` (git-ignored) or by setting `KEVIDENCE_CHARACTERISATION_TEMPLATE`; the available placeholders are documented at the top of the public template.
- **Data-gap analysis:** each of 27 guidance requirements is marked *evidence located*, *partially addressed*, *not located*, *applicability to confirm*, *scientific-officer review* or *not applicable*. Quantitative checks come straight from the guidance: ≥ 5 batches for the specification and ≥ 3 for impurities (§2.1.3, §2.1.4), analyses within the last 5 years, statements of compliance flagged (not sufficient on their own), dusting potential in ≥ 3 batches (§2.1.5), shelf life in ≥ 3 batches (§2.4.1.1), premixture ≥ 6 months and feed ≥ 3 months (§2.4.1.2), water ≥ 48 h (§2.4.1.3), homogeneity ≥ 10 subsamples (§2.4.2). The minimum impurity set depends on production type (chemical synthesis, fermentation, plant-derived, animal-derived, mineral; §2.1.4). Exemptions (flavouring compounds, silage additives, colourants, mineral-based additives) are applied where the guidance gives them. Applicant justifications for omissions are surfaced (guidance p.5: reasons should be given for any omission).
- **Grounding:** the requirement catalogue (`data/guidance/feedap_2017_5023_chemical_requirements.json`) cites the guidance section and page and quotes it verbatim for every requirement. The guidance PDF is bundled unmodified (CC BY-ND 4.0) and every requirement is re-anchored against its text at start-up; the UI shows how many are anchored and the PDF is served at `/api/characterisation/guidance.pdf`. `tests/test_characterisation.py` fails if any quote, page reference or anchor drifts from the guidance. In step 0 the Evidence Assistant answers only from the guidance entries and refuses questions it cannot ground.
- **Traceability:** extraction is deterministic (pattern-based); every value carries a `D<n> p.<page>` citation. Statuses say whether evidence was *located*, not whether it is adequate — adequacy stays with the scientific officer.
- **Confidentiality:** documents are processed in memory for one request and are not stored. Extraction and gap analysis run locally. Optional LLM drafting of section narratives sends extracted excerpts to the OpenAI API and is **off unless ticked per request**; every number in an LLM narrative is checked against the dossier excerpts and untraced numbers are flagged.
- **Limits:** scanned PDFs need OCR first; dossier portals rendered by JavaScript (e.g. Open EFSA) cannot be read by URL — download and upload the documents. Production-strain characterisation (§2.2.1.2, §2.2.2.2; FEEDAP microorganism guidance, EFSA Journal 2018;16(3):5206) is out of scope; fermentation-related impurity requirements of §2.1.4 are included.

A fictional, deliberately incomplete demo dossier is provided at `static/samples/characterisation_demo_dossier.md` (also linked from the in-app *Guide & questions* tab).

### AOP-Wiki knowledge base

KEvidence builds a local SQLite database from bundled AOP-Wiki-derived TSV and XML data. The local database includes:

- AOP IDs, titles, molecular initiating events, adverse outcomes, and OECD status where available.
- Key events and event types.
- Key Event Relationships (KERs).
- KER-level evidence and quantitative understanding codes.
- Event components and ontology identifiers.
- Chemical/stressor mappings extracted from the bundled AOP-Wiki XML file.

### Risk assessment workbench UI

The frontend is a single-page workbench with step navigation and a contextual assistant. The workflow is organized around the four Codex risk-assessment steps (hazard identification, hazard characterisation, exposure assessment, risk characterisation), framed by problem formulation and followed by uncertainty analysis and a scientific-opinion draft — rather than around a generic chat page.

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

The Evidence Assistant uses structured workbench context when answering questions. If a user asks a short prompt such as “Explain AOP,” the assistant receives the current chemical, selected AOP, use case, route, population, OpenFoodTox summary, and quantitative context.

---

## Repository structure

```text
.
├── server.py                         # FastAPI backend and risk assessment logic
├── characterisation.py               # Step 0: document ingestion, guidance-grounded characterisation and gap analysis
├── static/index.html                 # Single-page workbench UI
├── requirements.txt                  # Python dependencies
├── scripts/
│   ├── import_openfoodtox.py          # EFSA OpenFoodTox Excel/CSV/XLSX importer
│   └── import_epa_bioactivity.py      # EPA ToxCast/Tox21/ToxRefDB-style importer
├── tests/
│   └── test_characterisation.py       # Grounding guard (quotes/anchors vs guidance PDF) and step 0 behaviour
├── data/
│   ├── guidance/
│   │   ├── efsa_2017_5023.pdf         # FEEDAP guidance on identity/characterisation (CC BY-ND 4.0, unmodified)
│   │   ├── feedap_2017_5023_chemical_requirements.json  # Requirement catalogue with verbatim quotes
│   │   ├── characterisation_template.md                 # Public output template (FEEDAP opinion layout + evidence map)
│   │   └── local/                                       # Git-ignored: institution's own template (optional)
│   ├── aop_ke_mie_ao.tsv              # AOP/event/MIE/AO source data
│   ├── aop_ke_ker.tsv                 # KER source data
│   ├── aop_ke_ec.tsv                  # Event component source data
│   ├── aop-wiki-xml.gz                # AOP-Wiki XML-derived source file
│   └── aops/                          # Cached AOP text excerpts
└── LICENSE
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR-ORG/KEvidence.git
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

KEvidence uses the OpenAI API for the Evidence Assistant.

```bash
export OPENAI_API_KEY="your-api-key"
```

Optional model override:

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

- **Authentication:** every endpoint is open unless you set `KEVIDENCE_AUTH_USER` and `KEVIDENCE_AUTH_PASSWORD` (HTTP Basic, checked in constant time on every route) or put an authenticating reverse proxy in front. Serve over HTTPS only. Step 0 handles confidential dossiers; do not expose it without authentication.
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
| `/api/characterisation/guidance` | GET | Step 0 requirement catalogue and grounding status of each requirement against the guidance text. |
| `/api/characterisation/guidance.pdf` | GET | The bundled FEEDAP guidance PDF (unmodified). |
| `/api/characterisation/analyse` | POST | Multipart: `files` (repeatable), `urls` (newline-separated), `meta` (JSON: `product_name`, `applicant`, `dossier_ref`, `authorisation`, `product_form`, `routes`, `production_types`, `additive_type`, `formulations`, `components`), `allow_external_llm`. Returns requirement evaluations, gap summary and `markdown`. |

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

---

## Data provenance and attribution

- AOP data are derived from OECD AOP-Wiki exports and local cached AOP text excerpts.
- OpenFoodTox content, when imported, should be attributed to EFSA and the source export package.
- EPA ToxCast/Tox21/ToxRefDB-style content, when imported, should retain the original source, export version, and retrieval date.
- Generated KEvidence outputs should clearly distinguish source data, user-supplied values, heuristic calculations, and LLM-generated summaries.

---

## Development notes

Recommended checks before opening a pull request:

```bash
python -m py_compile server.py characterisation.py scripts/import_openfoodtox.py scripts/import_epa_bioactivity.py
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
- Exportable assessment reports in Markdown, Word, or PDF.
- User authentication and assessment-session persistence.
- Dedicated tests for backend scoring, importers, and frontend workflow behavior.

---

## Contributing

Contributions are welcome. Useful contributions include:

- Bug reports and reproducible examples.
- Improved importers for specific official data releases.
- Tests for backend assessment and quantitative functions.
- UI/UX improvements for regulatory workflows.
- Documentation and example datasets.
- Scientific review of scoring logic, uncertainty labels, and NAM/AOP mapping assumptions.

Before contributing, please open an issue or discussion describing the proposed change, especially for scientific scoring, regulatory interpretation, or data-source integrations.

Feature requests can also be submitted from the in-app **Questions?** tab, by opening the GitHub repository at <https://github.com/LyzDevalier/KEvidence>, or by emailing <kevidence@devalier.com>.

---

## License

See [`LICENSE`](LICENSE) for repository licensing terms.

Third-party datasets retain their own attribution and reuse requirements. Always preserve source attribution and do not imply endorsement by OECD, EFSA, EPA, ECHA, or other organizations unless explicitly authorized.
