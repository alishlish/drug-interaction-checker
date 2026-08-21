"""
Hallucination eval for src/services/llm.py::explain().

Ground truth = the deterministic interaction record produced by
find_interaction() + the structured drug attributes from get_drug().
Those are exactly the only facts the LLM is allowed to use (see the
system prompt in llm.py), so an explanation "hallucinates" if it
contains a number, enzyme/transporter token, or drug name that does
not appear anywhere in that source payload.

Usage:
    python -m scripts.eval_explanations --n 40 --tag baseline
    python -m scripts.eval_explanations --n 40 --tag after_prompt_v2
    python -m scripts.eval_explanations --diff results/baseline.json results/after_prompt_v2.json

Results are written to scripts/eval_results/<tag>.json so two runs
(e.g. before/after a prompt change) can be diffed.
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple

from src.services.data import load_datastore, get_drug, DataStore
from src.services.interactions import find_interaction
from src.services.llm import make_client, explain

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
DATA_PATH = os.path.join(REPO_ROOT, "data", "processed", "drug_interactions_clean.csv")
RESULTS_DIR = os.path.join(BASE_DIR, "eval_results")

# Negative lookbehind prevents a range hyphen ("0.066-0.095") from being
# misread as a minus sign on the second number.
NUMBER_RE = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?")
TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9\-]{2,}\b")
KNOWN_MECHANISM_TOKENS = {
    "CYP1A2", "CYP2C9", "CYP2C19", "CYP2D6", "CYP3A4", "CYP3A5", "CYP2B6",
    "P-GP", "BCRP", "OATP", "OAT", "OCT", "MATE", "SULT2A1",
}


@dataclass
class CaseResult:
    drug1: str
    drug2: str
    evidence_type: str
    category: str  # ok | hallucinated | blocked_advice | no_evidence_expected | not_configured | parse_failed
    explanation: str
    ungrounded_numbers: List[str]
    ungrounded_tokens: List[str]


def _flatten_source_text(*payloads: Any) -> str:
    """Flatten all source-of-truth values into one lowercase blob for substring checks."""
    parts: List[str] = []

    def walk(x: Any) -> None:
        if x is None:
            return
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        else:
            parts.append(str(x))

    for p in payloads:
        walk(p)
    blob = " ".join(parts).lower()
    # Source CSV has whitespace artifacts from PDF extraction (e.g. "B CRP"
    # instead of "BCRP"); compare on a whitespace-collapsed copy too so the
    # LLM isn't penalized for correctly normalizing them.
    return blob + " " + re.sub(r"\s+", "", blob)


def _check_grounding(explanation: str, source_text: str) -> Tuple[List[str], List[str]]:
    """Return (ungrounded_numbers, ungrounded_mechanism_tokens) found in explanation but absent from source."""
    ungrounded_numbers = []
    for m in NUMBER_RE.findall(explanation):
        if m not in source_text:
            ungrounded_numbers.append(m)

    ungrounded_tokens = []
    for tok in TOKEN_RE.findall(explanation.upper()):
        if tok in KNOWN_MECHANISM_TOKENS and tok.lower() not in source_text:
            ungrounded_tokens.append(tok)

    return ungrounded_numbers, ungrounded_tokens


def _sample_pairs(ds: DataStore, n: int, seed: int = 7) -> List[Tuple[str, str]]:
    rng = random.Random(seed)
    names = ds.drug_names

    ref_pairs, mech_pairs = [], []
    for name, row in ds.drug_map.items():
        inh = (row.get("inhibitor") or "").strip().lower()
        if inh and inh in ds.drug_map:
            ref_pairs.append((name, inh))

    def tokenize(s: str) -> set:
        s = (s or "").upper()
        return {p.strip() for p in re.split(r"[,;/|]", s) if p.strip()}

    enzyme_by_drug = {name: tokenize(row.get("enzymes", "")) for name, row in ds.drug_map.items()}
    sample_names = rng.sample(names, min(400, len(names)))
    for i, a in enumerate(sample_names):
        for b in sample_names[i + 1:]:
            if enzyme_by_drug.get(a) and enzyme_by_drug.get(a) & enzyme_by_drug.get(b, set()):
                mech_pairs.append((a, b))
                break
        if len(mech_pairs) >= n:
            break

    none_pairs = []
    while len(none_pairs) < max(1, n // 6):
        a, b = rng.sample(names, 2)
        none_pairs.append((a, b))

    pairs = []
    rng.shuffle(ref_pairs)
    rng.shuffle(mech_pairs)
    pairs.extend(ref_pairs[: n // 2])
    pairs.extend(mech_pairs[: n // 3])
    pairs.extend(none_pairs)
    pairs.append(("definitely-not-a-real-drug", names[0]))  # missing_drug case
    return pairs[:n]


def run_eval(n: int, model: str, style: str) -> List[CaseResult]:
    ds = load_datastore(DATA_PATH)
    api_key = os.getenv("OPENAI_API_KEY", "")
    client = make_client(api_key)

    results: List[CaseResult] = []
    for d1, d2 in _sample_pairs(ds, n):
        interaction = find_interaction(ds, d1, d2)
        drug1 = get_drug(ds, d1)
        drug2 = get_drug(ds, d2)
        ev_type = (interaction.get("evidence") or {}).get("type", "")

        explanation = explain(client, interaction, drug1, drug2, model=model, style=style)

        if client is None:
            category = "not_configured"
        elif explanation == "No explainable dataset evidence for this pair.":
            category = "no_evidence_expected"
        elif explanation.startswith("Explanation blocked"):
            category = "blocked_advice"
        elif explanation in ("Failed to parse LLM response safely.", "No explanation returned."):
            category = "parse_failed"
        else:
            source_text = _flatten_source_text(interaction, drug1, drug2)
            ungrounded_numbers, ungrounded_tokens = _check_grounding(explanation, source_text)
            category = "hallucinated" if (ungrounded_numbers or ungrounded_tokens) else "ok"
            results.append(CaseResult(d1, d2, ev_type, category, explanation, ungrounded_numbers, ungrounded_tokens))
            continue

        results.append(CaseResult(d1, d2, ev_type, category, explanation, [], []))

    return results


def summarize(results: List[CaseResult]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for r in results:
        counts[r.category] = counts.get(r.category, 0) + 1

    eligible = counts.get("ok", 0) + counts.get("hallucinated", 0)
    hallucination_rate = (counts.get("hallucinated", 0) / eligible * 100) if eligible else None

    return {
        "total_cases": len(results),
        "counts": counts,
        "eligible_for_hallucination_check": eligible,
        "hallucination_rate_pct": round(hallucination_rate, 1) if hallucination_rate is not None else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=40, help="number of drug pairs to sample")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--style", default="plain", choices=["plain", "clinical"])
    parser.add_argument("--tag", default="run", help="label for this run, used as the output filename")
    parser.add_argument("--diff", nargs=2, metavar=("BEFORE_JSON", "AFTER_JSON"), help="compare two saved result files instead of running")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    if args.diff:
        before_path, after_path = args.diff
        with open(before_path) as f:
            before = json.load(f)
        with open(after_path) as f:
            after = json.load(f)
        print(f"BEFORE ({before_path}): {before['summary']}")
        print(f"AFTER  ({after_path}): {after['summary']}")
        b, a = before["summary"]["hallucination_rate_pct"], after["summary"]["hallucination_rate_pct"]
        if b is not None and a is not None:
            print(f"\nHallucination rate: {b}% -> {a}% ({a - b:+.1f} pts)")
        return

    results = run_eval(args.n, args.model, args.style)
    summary = summarize(results)

    out_path = os.path.join(RESULTS_DIR, f"{args.tag}.json")
    with open(out_path, "w") as f:
        json.dump({"summary": summary, "cases": [asdict(r) for r in results]}, f, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"\nSaved {len(results)} cases to {out_path}")

    for r in results:
        if r.category == "hallucinated":
            print(f"\n[HALLUCINATED] {r.drug1} + {r.drug2} ({r.evidence_type})")
            print(f"  numbers not in source: {r.ungrounded_numbers}")
            print(f"  tokens not in source:  {r.ungrounded_tokens}")
            print(f"  explanation: {r.explanation}")


if __name__ == "__main__":
    main()
