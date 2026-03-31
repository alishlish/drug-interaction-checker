# Clinical Drug Interaction & Organ Impairment Checker

A clinically oriented drug–drug interaction screening tool that combines **deterministic pharmacokinetic data** with **carefully constrained generative explanations**, designed to surface enzyme-, transporter-, and organ-impairment–related interactions **without hallucinating medical facts**.

---

## Purpose & Motivation

This project was built to bridge the gap between:

- **Raw pharmacokinetic datasets**, which are information-dense and difficult to interpret
- **Clinical and research workflows**, which require clarity, provenance, and caution

Rather than attempting to *predict* interactions using machine learning, this system:

- Treats the dataset as the **single source of truth**
- Uses **deterministic logic** to flag potential interactions
- Uses **generative AI only to explain existing data**, never to infer or invent medical information

The goal is to support **screening, education, and exploration**, not diagnosis or prescribing.

---

## Dataset & Provenance

### Primary Data Source
The core dataset was derived from the:

**Organ Impairment Drug Interaction Database (courtesy of the National Institute of Health)**  
(assembled from peer-reviewed pharmacokinetic studies and reference interactions)

The original data was provided as a **PDF containing complex tables**, including:

- Drug names and CAS numbers
- CYP enzyme involvement
- Transporter involvement (e.g. P-gp)
- Renal vs non-renal clearance pathways
- Observed changes in exposure (ΔAUC)
- Reference inhibitors and PMIDs

More information available here: 

https://pmc.ncbi.nlm.nih.gov/articles/PMC4562165/
---

## Major Challenge: Parsing & Cleaning the Data

One of the most significant challenges in this project was **data extraction**.

### Issues encountered:
- Source data was **not machine-readable**
- Tables spanned multiple pages with inconsistent formatting
- Headers and values were misaligned in early CSV exports
- Column semantics required domain interpretation

### Resolution:
- Iterative PDF table extraction
- Manual inspection of column meanings
- Column normalization and standardization
- Separation of:
  - **Core interaction fields** (enzymes, transporters)
  - **Clinical attributes** (renal clearance, ΔAUC, route of administration)

Only after this process was a **reliable, structured CSV** produced and committed as the backend data source.

---

## System Architecture

### Backend
- **FastAPI** for API + UI serving
- **Pandas** for data loading and normalization
- Deterministic interaction logic (no ML inference)

### Frontend
- Server-rendered HTML (Jinja2)
- Vanilla JavaScript
- UI language designed for clinical clarity

### Containerization
- Fully containerized using **Docker**
- Ensures reproducibility across environments
- Suitable for deployment on Render, Fly.io, Railway, etc.

---

## Project Structure

```drug-interaction-checker/
├── src/
│ ├── api.py # FastAPI app entrypoint
│ ├── services/
│ │ ├── data.py # Data loading & normalization
│ │ ├── interactions.py# Deterministic interaction logic
│ │ ├── present.py # Attribute glossary & translation
│ │ └── llm.py # Constrained GenAI explanations
│ ├── constants/ # Shared labels / mappings
│ └── ui.py # UI routing
│
├── data/
│ └── processed/
│ └── drug_interactions_clean.csv
│
├── templates/
│ └── index.html # UI template
├── static/
│ ├── app.js # Frontend logic
│ └── styles.css
│
├── Dockerfile
├── .dockerignore
├── requirements.txt
└── README.md
```


---

## Use of Generative AI (and Why It’s Limited)

### What AI is used for
- Translating structured interaction data into **plain-language explanations**
- Improving interpretability for clinicians and students

### Safeguards
- AI receives **only structured JSON from the dataset**
- Prompts explicitly forbid:
  - hallucination
  - external facts
  - clinical advice
- If the mechanism is unclear, the AI must state **“insufficient data”**

AI output is explanatory only and never treated as evidence.

---

## 🧬 Medical Terminology Translation

Raw dataset fields are translated into clinician-friendly labels using a glossary layer.

### Example

| Raw Field | Displayed As |
|---------|--------------|
| `delta_auc_pct` | Reported change in exposure (ΔAUC) |
| `renal` | Renal clearance involvement |
| `route_of_admin` | Route of administration |
| `fe` | Fraction excreted unchanged |

Each attribute includes:
- the normalized value
- a brief explanatory gloss

This preserves provenance while improving usability.

---

## How to Use the App

### For Users (UI)
1. Open `/ui` in your browser
2. Enter one or more medication names
3. Click **Evaluate interactions**
4. Review:
   - interaction severity
   - enzyme / transporter overlap
   - renal and non-renal clearance attributes
   - reference interaction data (when available)

### For Developers (API)
- `/docs` – interactive Swagger documentation
- `/check` – deterministic interaction checking
- `/check/explain` – interaction + constrained explanation
- `/drug/{name}` – structured drug information

---

## 🐳 Running with Docker

### Build the image
```bash
docker build -t drug-checker .
```

### Run locally

```bash
docker run -p 8000:8000 drug-checker
```

### Then open:

```bash
UI: http://127.0.0.1:8000/ui

Docs: http://127.0.0.1:8000/docs
```

### Deployment

The app is deployed as a Docker container and can run on:

- Render
- Railway
- Fly.io
- Any Docker-compatible platform!

### Environment variables:

- OPENAI_API_KEY (optional)
- CORS_ORIGINS
- DRUG_DATA_PATH (optional if CSV is committed)

## Disclaimer

This tool is intended for educational and screening purposes only.

It does not replace:
- clinical judgment
- prescribing guidelines
- pharmacist or physician consultation
- **Always confirm interactions using authoritative clinical references.**

### Next Steps

**Planned or possible extensions:**

- Support for renal-only / hepatic-only filtering
- Clearer severity stratification tied to ΔAUC ranges
- Additional datasets (hepatic impairment, pediatrics)
- Improved evidence linking (PMID expansion)
- Audit logging for clinical review
- Optional removal of AI layer for fully deterministic mode
