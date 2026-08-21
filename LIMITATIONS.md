# Limitations

An honest account of what this tool is *not* and where it falls short. Measured
limitations are quantified in `EVALUATION.md`; this is the plain-language scope.

## Clinical scope

- **This is a research/educational project — not medical advice.** It must not be
  used for diagnosis, prescribing, or treatment decisions. Always confirm with
  authoritative references and a licensed pharmacist or physician.
- It is a **screening and exploration** tool over a specific dataset, not a
  comprehensive or authoritative interaction checker.

## Data coverage

- The core dataset is **271 drugs** from an NIH organ-impairment PK reference —
  narrow by design. Many common drugs (e.g. warfarin as a lookup target) are not
  present; those queries correctly refuse.
- **DDInter join covers 63.8%** of the dataset (173/271 drugs). Pairs involving
  the other 36% get no DDInter cross-reference.
- Data is a **point-in-time snapshot** (CSV extracted from a PDF; DDInter
  downloaded once). Neither auto-updates.

## What the tool measures — and doesn't

- It is fundamentally a **pharmacokinetic-mechanism screen** (shared enzymes /
  transporters / reference PK studies), now augmented with DDInter's curated
  clinical DDIs. Against DDInter it shows **~33% precision / ~29% recall** — it
  **over-flags** mechanism overlaps that aren't clinically significant and
  **under-covers** clinical interactions outside its PK scope.
- The **severity heuristic** for our own evidence is crude (ΔAUC tiers); DDInter's
  clinical `Level` is the more meaningful severity when a pair is listed.
- The **grounding/hallucination check is literal string matching**, so legitimate
  unit conversions count against the ~8% rate (it's a conservative upper bound,
  on a small eligible sample).

## Identity resolution

- **No typo auto-correction**: exact-only means good misspellings (`candesartn`)
  are refused, not corrected — the safe failure. Suggestions are surfaced but
  never auto-applied.
- **Brand support depends on RxNorm** and on the brand's generic being in the
  dataset; brands of drugs we don't cover still won't resolve.
- RxNorm **approximate matches are not trusted** for identity (fuzzy matcher maps
  common words to drugs), so some resolvable-in-principle variants are refused.

## Operational

- **`/analyze` requires OpenAI + Pinecone keys and a populated index**; without
  them it returns `503` (by design, so the rest of the app still runs).
- Identity resolution and RAG depend on **external services** (RxNav, OpenAI,
  Pinecone) being reachable; they degrade gracefully but reduce functionality when
  down.
- A **backend timeout currently surfaces as a 500** rather than a graceful
  message — a known gap (documented in `tests/test_api.py`).
- The behavioral eval runs against a **local server**, not the deployed instance.

## Validation

- **Not validated against DrugBank** — its academic downloads are paused and its
  free interaction API was discontinued. DDInter 2.0 is the external gold standard
  instead.
- The **reference-DDI validation sub-metric is small (n=27)** and noisy.
