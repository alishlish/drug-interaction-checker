# Design Decisions

The *why* behind the architecture. Each entry is a decision, the reasoning, and
the tradeoff accepted.

## 1. Drug identity is exact-match; only *context* uses vectors

**Decision.** Resolve "is this a real drug, and which one?" with an exact lookup
(`drug_map`, then RxNorm). Use embeddings *only* to find pharmacokinetically
related drugs for context.

**Why.** Identity is an *exact-membership* question; an authoritative map answers
it correctly. Embedding a drug *name* captures its *meaning*, not its spelling or
identity — which is why an earlier semantic fallback mapped `asdfghjkl` →
*lorazepam* and `warfrin` → *teriflunomide*, then reported the wrong drug's PK.
Measured scores confirmed no embedding threshold cleanly separates real inputs
from nonsense. "What *other* drugs share this PK profile?" genuinely is semantic
and has no exact answer — that is where vector search belongs.

**Tradeoff.** Exact-match refuses good misspellings (`candesartn`) rather than
correcting them. Accepted: a safe refusal beats a confident wrong answer.

## 2. Refuse, don't hedge or substitute

**Decision.** An unresolved drug yields an explicit "not in the dataset and was
not analyzed", not a hedged guess or a nearest-match.

**Why.** In a clinical context, a confident answer about the *wrong* drug is the
most dangerous failure. Refusal is the honest failure mode. This is the project's
core thesis, and it's measured (silent-substitution 21 → 0; see `EVALUATION.md`).

## 3. RxNorm approximate matches are suggestions, never auto-applied

**Decision.** Only *exact-tier* RxNorm matches (which include brands/synonyms)
resolve automatically. Approximate matches are surfaced as "did you mean …?"
suggestions requiring confirmation.

**Why.** RxNav's fuzzy matcher is permissive: calibration showed real typos score
~8 but common English words fuzzy-match too ("banana" → a product scores ~12).
Score cannot separate a drug typo from a coincidental word match, so approximate
hits can't be trusted for identity. Same logic anchoring the dataset: a
name-verification guard rejected wrong RxNorm mappings (`clinafloxacin` →
*finafloxacin*; five drugs collapsed onto one RxCUI).

## 4. RxNorm over DrugBank for identity; DDInter over DrugBank for interactions

**Decision.** Use RxNorm (identity) and DDInter 2.0 (interactions) — both open —
rather than DrugBank.

**Why.** DrugBank's data is license-restricted and its free access is closing:
academic downloads are paused, and NLM discontinued the RxNav Drug Interaction
API (Jan 2024) that used to relay DrugBank's DDIs. Committing DrugBank data would
break redistribution *and* clean-clone reproducibility, and using a mirrored copy
would violate its license. RxNorm (NIH, free, authoritative) and DDInter 2.0
(open, 160k severity-annotated pairs — more than NLM ever exposed) are
accessible, redistributable-as-derived, and durable.

**Tradeoff.** No DrugBank cross-validation (its downloads are paused). DDInter
serves as the external gold standard instead.

## 5. Two endpoints: deterministic `/check` vs agentic `/analyze`

**Decision.** Keep a pure, key-free, deterministic `/check` separate from the
LLM+RAG `/analyze`.

**Why.** The deterministic path is the reproducible, auditable core — it needs no
API keys, always returns the same answer, and can't hallucinate. The agent adds
narrative and PK-context value but carries cost, latency, and LLM risk. Splitting
them lets the trustworthy core stand alone and be tested offline.

## 6. Agent (and clients) initialize lazily

**Decision.** Build the OpenAI/Pinecone-backed agent on first `/analyze` call, not
at import.

**Why.** The app must boot, serve `/check`, and run its test suite **without any
API keys** — needed for CI, a fresh clone, and the deterministic endpoints.
Eager init coupled the whole app to external services.

## 7. DDInter merged as a *second source*, not a replacement

**Decision.** `find_interaction` returns our PK evidence *and* a `ddinter` block
(curated clinical severity) side by side.

**Why.** The two measure different things (PK mechanism screen vs curated clinical
DDI — see the 33%/29% cross-check in `EVALUATION.md`). Presenting both, with clear
source attribution, is more honest and more useful than collapsing them into one
verdict, and it directly fills the recall gap the validation exposed.

## 8. Phased approach, honest evaluation first

**Decision.** Build the evaluation harness *before* fixing anything (Phase 0),
measure the defect, fix, then re-measure.

**Why.** Without a baseline you can't prove a fix worked or catch a regression.
The harness caught the silent-substitution defect, quantified it, and verified
the fix — and even caught a false positive in its own scorer. Evaluation
discipline is the point, not an afterthought.
