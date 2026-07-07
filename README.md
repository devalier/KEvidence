# KEvidence

**KEvidence** is an open-source, AOP-guided regulatory risk assessment workbench. It helps scientific officers, toxicologists, NAM developers, and risk assessors move from a chemical or biological concern to structured Adverse Outcome Pathway (AOP) evidence, hazard hypotheses, confidence statements, uncertainty/data-gap summaries, and screening-level quantitative comparisons.

KEvidence is not intended to replace expert regulatory judgement. It is a decision-support prototype that combines local AOP-Wiki-derived data, optional OpenFoodTox exports, optional EPA ToxCast/Tox21/ToxRefDB-style exports, and an LLM-assisted evidence assistant.

---

## What KEvidence does

KEvidence turns AOP-Wiki data into a workflow-oriented risk assessment interface. **Risk analysis** is the whole governance cycle — risk assessment, risk management, and risk communication (EU General Food Law, Regulation (EC) No 178/2002). KEvidence supports the scientific **risk assessment** part, which Codex defines as four steps. The workbench follows that structure, with problem formulation as the practical framing step:

- **Problem formulation** — define the substance/stressor, product domain, use scenario, endpoint of concern, and decision context. Not one of the four formal Codex steps, but it frames all of them.
1. **Hazard identification** — *can this agent cause harm?* Search and select candidate AOPs by chemical, stressor, key event, adverse outcome, or AOP ID.
2. **Hazard characterisation** — *what is the nature and severity of the harm, and at what dose?* Review MIEs, key events, KERs, weight of evidence, and quantitative understanding; pull reference points and health-based guidance values from OpenFoodTox; and set a dose-response point of departure (POD) from NAM data (optionally browsing locally indexed EPA ToxCast/Tox21/ToxRefDB-style exports).
3. **Exposure assessment** — *who is exposed, how much, how often, and by which route?* Record concentration in food/feed × consumption × population × use conditions, and the resulting exposure estimate.
4. **Risk characterisation** — *given hazard and exposure, what is the risk?* Integrate the POD with the exposure estimate to calculate screening margins (BER/MOE) and a hazard-quotient-style ratio.

The workbench then supports **uncertainty analysis** (confidence summaries, key uncertainties, critical data gaps, recommended next data) and a **scientific opinion draft** that can be refined with the Evidence Assistant and handed to risk managers.

> **Hazard is not risk.** Hazard is the intrinsic potential for harm; risk is that hazard under actual exposure conditions. KEvidence keeps the two separate and does not make risk-management decisions.

---

## Key features

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
├── static/index.html                 # Single-page workbench UI
├── requirements.txt                  # Python dependencies
├── scripts/
│   ├── import_openfoodtox.py          # EFSA OpenFoodTox Excel/CSV/XLSX importer
│   └── import_epa_bioactivity.py      # EPA ToxCast/Tox21/ToxRefDB-style importer
├── data/
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
python -m py_compile server.py scripts/import_openfoodtox.py scripts/import_epa_bioactivity.py
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
