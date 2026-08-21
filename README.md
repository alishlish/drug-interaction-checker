# Drug Interaction & Organ-Impairment Checker

A drug–drug interaction screening tool that **refuses to answer about drugs it doesn't have, rather than silently substituting a similar one** — pairing a deterministic pharmacokinetic dataset with a tightly-constrained LLM that explains the data without inventing facts or giving clinical advice.

> ⚠️ **Research / educational project — not medical advice.** See [Disclaimer](#disclaimer).

<!-- Demo GIF — record a 60s clip (grounded interaction → refusal on an unknown drug →
     provenance/citation trail), save it to docs/demo.gif, then uncomment the next line: -->
<!-- ![demo](docs/demo.gif) -->

*(A walkthrough GIF is coming — for now, try the [live demo](#live-demo).)*

---

## The thesis

Most "AI drug checker" demos fail quietly: ask about a drug that isn't in their data and they confidently answer about a *different* drug. This project treats that as the primary failure mode to eliminate.

- **Drug identity is resolved by exact lookup**, never by embedding similarity. An unrecognized name (misspelling, brand, nonsense) is reported as *not in the dataset* — not mapped to the nearest vector.
- **The LLM only explains data already retrieved deterministically.** It is structurally prevented from dosing advice, safe/unsafe verdicts, or facts outside the dataset.
- **The guardrail is measured, not asserted** — see [Evaluation](#evaluation).

---

## Live demo

**[drug-interaction-checker-f6mp.onrender.com/ui](https://drug-interaction-checker-f6mp.onrender.com/ui)** — Render free tier, so the first load may cold-start (~30s).

Try: `clarithromycin` + `ritonavir` (two cited sources agree) · type **`Diflucan`** (resolves to fluconazole via RxNorm) · type **`warfarin`** (refused — an explicit "not screened" card, no silent substitution).

## Documentation

| Doc | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the pieces fit — two-endpoint model, data sources, the LangGraph pipeline (diagrams) |
| [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | Why exact-match identity, why RxNorm/DDInter over DrugBank, the tradeoffs |
| [EVALUATION.md](EVALUATION.md) | Four measured evaluations, honestly reported |
| [LIMITATIONS.md](LIMITATIONS.md) | What the tool is — and isn't |

---

## Quickstart (from a clean clone)

Requires **Python 3.12**.

```bash
git clone <this-repo> && cd drug-interaction-checker
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in your keys (see below)
```

**`/check` works immediately** — it's deterministic and needs no keys or Pinecone:

```bash
uvicorn src.api:app --reload
curl -X POST localhost:8000/check -H 'Content-Type: application/json' \
     -d '{"drugs":["azilsartan","fluconazole"]}'
```

Open the UI at <http://127.0.0.1:8000/ui>, or Swagger docs at <http://127.0.0.1:8000/docs>.

### Enabling `/analyze` (the LLM + RAG agent)

`/analyze` and `/check/explain` need OpenAI + a **populated** Pinecone index:

1. Set `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` in `.env`.
2. **Create the Pinecone index by hand** in the Pinecone console — dimension **1536**, metric **cosine** (matches `text-embedding-3-small`). *The code assumes the index already exists; it does not create it.*
3. Embed the dataset into it (one-time):
   ```bash
   python scripts/ingest.py
   ```

Without keys the app still boots and serves `/check`; `/analyze` returns a clean `503`.

### Regenerating the derived data (optional)

The committed data (`drug_interactions_clean.csv`, `drug_rxcui.json`, `ddinter_pairs.json`) is enough to run — you don't need this to use the app. To rebuild the pipeline from source:

| Step | Command | Produces |
|---|---|---|
| Extract CSV from the source PDF | `pip install -r requirements-build.txt` → `python notebooks/parse_pdf.py` | `drug_interactions_clean.csv` |
| Anchor drugs to RxNorm | `python -m scripts.map_rxcui` | `drug_rxcui.json` (90.8% trusted) |
| Build the DDInter lookup | download DDInter (`data/ddinter/README.md`) → `python -m scripts.build_ddinter_lookup` | `ddinter_pairs.json` |
| Embed rows into Pinecone | `python scripts/ingest.py` | populated Pinecone index |

Run the tests and evals any time: `pytest -q` · `python eval/run_tests.py --selftest`.

---

## Architecture

Two endpoints, deliberately different in cost and trust:

| Endpoint | Engine | Needs keys? | Use |
|---|---|---|---|
| `/check` | Deterministic pandas lookup | No | Fast, exact interaction screen |
| `/analyze` | LangGraph agent + Pinecone RAG + LLM | Yes | Narrative synthesis with organ-impairment context |

### The `/analyze` LangGraph state graph, node by node

Defined in [`src/services/agent.py`](src/services/agent.py). State flows `START → … → END`; one conditional edge.

1. **`retrieve_drugs`** — Resolves each input name by **exact `drug_map` lookup** (the source of truth). A name that isn't an exact entry is marked `found: false`; it is **never** substituted with a similar drug. *(No Pinecone here — this is the deliberate design choice; see below.)*
2. **`retrieve_context`** — The genuine RAG step. Uses Pinecone semantic search keyed on the **patient's clinical situation** (renal/hepatic state + the drug list) to surface *other* pharmacokinetically-related drugs, adding PK-landscape context.
3. **`check_interactions`** — Deterministic pairwise interaction logic ([`interactions.py`](src/services/interactions.py)): reference-DDI evidence first, then shared enzyme/transporter overlap, else "no evidence."
4. **`assess_organ_context`** — Flags renal/hepatic concerns from the dataset's `fe`, `renal`, and enzyme fields when impairment is specified.
5. **`deep_evidence`** *(conditional — only fires when an interaction is moderate/high severity)* — A second Pinecone query along the shared enzyme/transporter pathway to pull related drugs and ΔAUC context.
6. **`synthesize`** — A single `gpt-4.1-mini` call (temperature 0, JSON mode) acting as a **strict summarizer**: dataset facts only, no dosing, no safe/unsafe verdict, must flag `drugs_not_in_dataset` as not analyzed, and appends a fixed disclaimer.

Routing: after `assess_organ_context`, the graph branches to `deep_evidence` only if severity is moderate/high, otherwise straight to `synthesize`.

---

## Design decisions

**Why drug identity uses exact match, not vectors.** "Is this drug in my dataset?" is an *exact-membership* question, and `drug_map` answers it authoritatively. Embedding a drug *name* captures its *meaning*, not its *spelling or identity* — so an earlier semantic fallback mapped `asdfghjkl` → a real drug (lorazepam) and `warfrin` → teriflunomide, then confidently reported the wrong drug's pharmacokinetics. Measured scores confirmed no embedding threshold cleanly separates real inputs from nonsense. Exact lookup removes the failure mode entirely.

**Why context enrichment still uses vector search.** "What *other* drugs share this PK profile?" is genuinely semantic and has no exact answer — that's legitimate RAG. So Pinecone is kept for `retrieve_context` and `deep_evidence` (enrichment), and removed from identity resolution.

**Why refuse instead of hedge.** An unresolved drug yields an explicit "not in the dataset and was not analyzed," not a hedged guess. Refusal is a safer failure than confident approximation in a clinical context.

**Typo tolerance is a deliberate omission (for now).** Exact-only means good misspellings (`candesartn`) are refused rather than auto-corrected — consistent with `/check`. A `difflib` near-match layer is a ready fast-follow (it resolved good typos while still rejecting brands/nonsense in testing) but was left out to keep `/check` and `/analyze` behavior identical.

---

## Evaluation

Two harnesses, both honest about their scope. **Neither validates against DrugBank** — the ground truth is the project's own NIH-derived CSV.

### Behavioral eval — `eval/` (71 cases, HTTP)

[`eval/run_tests.py`](eval/run_tests.py) POSTs 71 cases (drugs present, absent, brands, misspellings, nonsense, leading/dosing/implicit questions, and prompt-injection attempts) to `/check` and `/analyze`, scoring each as `correct_grounded`, `correct_refused`, `silent_substitution`, `advice_leak`, or `external_knowledge`. Has a `--selftest` that runs with no server or LLM.

Measured impact of the exact-match fix (strict scorer):

| | before | after |
|---|---:|---:|
| **silent_substitution** | 21 | **0** |
| advice_leak (across 24 question/adversarial cases) | 0 | **0** |

Baselines committed: `eval/baseline.csv` (`/check`), `eval/post_fix.csv` (`/analyze`, after the fix).

### Grounding eval — `scripts/eval_explanations.py` (in-process)

Checks whether each LLM *explanation* stays grounded in the interaction record it was given — i.e. every number and enzyme/transporter token in the output must appear in the source CSV payload. This is a **self-consistency / grounding** check against the internal dataset, **not** an external-knowledge benchmark.

Most recent run (n=109 sampled pairs):

- **~8% flagged grounding rate** — 2 of 25 *eligible* explanations contained a token/number not literally in the source.
- Both flagged cases are **unit conversions** (source `0.066` → explanation `6.6%`), not fabricated facts, so 8% is a conservative upper bound.
- The **advice guardrail refused ~62%** of explanation attempts outright (68/109) rather than risk an ungrounded claim.

Reproduce: `python -m scripts.eval_explanations --n 120 --tag grounding`.

### Known limitations

- The grounding check is literal string matching, so legitimate unit conversions count against the rate (conservative).
- The behavioral eval runs against a **local** server; a run against the deployed instance is still pending.
- Question-framed cases exercise the drug-list API; free-text advice-elicitation is tested via the optional `question` field, not a full chat surface.

---

## Dataset & provenance

Derived from the **Organ Impairment Drug Interaction Database (U.S. National Institutes of Health)** — peer-reviewed pharmacokinetic studies and reference interactions ([source](https://pmc.ncbi.nlm.nih.gov/articles/PMC4562165/)).

The source was a **PDF of complex, multi-page tables** (drug names, CAS numbers, CYP enzymes, transporters like P-gp, renal vs non-renal clearance, ΔAUC, reference inhibitors, PMIDs). Extraction required iterative PDF table parsing, manual column-semantics interpretation, and normalization into the committed `data/processed/drug_interactions_clean.csv` (the single source of truth; the PDF and raw exports are gitignored).

---

## API reference

- `GET /health` — status, drug count, whether the LLM is configured
- `GET /drugs?search=` — autocomplete over dataset drug names
- `GET /drug/{name}` — structured drug info (`404` if not in dataset)
- `POST /check` — deterministic interaction screen (≥2 drugs) — **no keys required**
- `POST /check/explain` — `/check` plus a constrained LLM explanation per pair *(keys required)*
- `POST /analyze` — full LangGraph agent: exact resolution + RAG context + organ-impairment flags + synthesis *(keys required; accepts optional `renal_impairment`, `hepatic_impairment`, `question`)*

---

## Configuration

| Var | Required for | Default |
|---|---|---|
| `OPENAI_API_KEY` | `/analyze`, `/check/explain` | — |
| `PINECONE_API_KEY` | `/analyze` | — |
| `PINECONE_INDEX_NAME` | `/analyze` | `drug-interactions` |
| `LLM_MODEL` | — | `gpt-4.1-mini` |
| `CORS_ORIGINS` | — | `*` |
| `DRUG_DATA_PATH` | — | committed CSV path |

See `.env.example`.

## Running with Docker

```bash
docker build -t drug-checker .
docker run -p 8000:8000 --env-file .env drug-checker
```

Deployable to Render, Railway, Fly.io, or any Docker host.

---

## Disclaimer

**This is a research and educational project. It is not medical advice and must not be used for diagnosis, prescribing, or treatment decisions.**

It does not replace clinical judgment, prescribing guidelines, or consultation with a qualified pharmacist or physician. The dataset is a limited PK reference, not a comprehensive interaction database. **Always confirm any interaction with authoritative clinical references and a licensed professional.**

---

## Roadmap

Delivered: RxNorm identity resolution, DDInter 2.0 merged as a second interaction source, consolidated citations, a provenance-visible frontend, and a four-part evaluation (see [EVALUATION.md](EVALUATION.md)). Next: fuller DDInter coverage to lift recall, a typo-suggestion UX, and DrugBank cross-validation once its downloads resume.
