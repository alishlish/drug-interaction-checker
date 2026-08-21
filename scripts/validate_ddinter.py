"""Validate the tool's interaction calls against DDInter 2.0 (external gold standard).

Joins DDInter to this project's dataset on the RxNorm-canonical drug name, then
for every drug pair evaluable in BOTH sources compares our find_interaction()
verdict to DDInter's. Reports precision / recall / agreement, split by our
evidence type (reference-DDI is high-confidence; mechanism-overlap is a broad
heuristic and expected to over-flag).

Run: python -m scripts.validate_ddinter
"""
from __future__ import annotations

import csv
import glob
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.data import load_datastore
from src.services.interactions import find_interaction

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "processed" / "drug_interactions_clean.csv"
RXCUI = ROOT / "data" / "processed" / "drug_rxcui.json"
DDINTER_GLOB = str(ROOT / "data" / "ddinter" / "ddinter_downloads_code_*.csv")


def load_ddinter():
    drugs, pairs = set(), {}
    for path in glob.glob(DDINTER_GLOB):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                a = (row.get("Drug_A") or "").strip().lower()
                b = (row.get("Drug_B") or "").strip().lower()
                if a and b:
                    drugs.add(a)
                    drugs.add(b)
                    pairs[frozenset((a, b))] = (row.get("Level") or "").strip()
    return drugs, pairs


def our_evidence(ds, d1, d2) -> str:
    """Our tool's evidence type for a pair: reference_ddi | mechanism_overlap | none/missing."""
    return (find_interaction(ds, d1, d2).get("evidence") or {}).get("type", "none")


def _rate(tp, fp, fn, tn):
    total = tp + fp + fn + tn
    prec = tp / (tp + fp) * 100 if tp + fp else float("nan")
    rec = tp / (tp + fn) * 100 if tp + fn else float("nan")
    agree = (tp + tn) / total * 100 if total else float("nan")
    return prec, rec, agree


def main():
    ds = load_datastore(str(CSV))
    rxmap = json.load(open(RXCUI))
    dd_drugs, dd_pairs = load_ddinter()
    print(f"DDInter: {len(dd_drugs)} drugs, {len(dd_pairs)} interaction pairs")

    # dataset drug -> DDInter join key (RxNorm-canonical name, lowercased)
    match_name = {}
    for name in ds.drug_names:
        rn = (rxmap.get(name, {}).get("rxnorm_name") or "").strip().lower()
        key = rn or name
        if key in dd_drugs:
            match_name[name] = key
    print(f"dataset drugs joinable to DDInter: {len(match_name)}/{len(ds.drug_names)} "
          f"({len(match_name) / len(ds.drug_names) * 100:.1f}%)")

    joinable = sorted(match_name)
    # overall confusion + a reference-DDI-only view (our high-confidence flags)
    tp = fp = fn = tn = 0
    ref_tp = ref_fp = 0
    for a, b in combinations(joinable, 2):
        dd = frozenset((match_name[a], match_name[b])) in dd_pairs
        ev = our_evidence(ds, a, b)
        ours = ev in ("reference_ddi", "mechanism_overlap")
        if ours and dd:
            tp += 1
        elif ours and not dd:
            fp += 1
        elif not ours and dd:
            fn += 1
        else:
            tn += 1
        if ev == "reference_ddi":
            (ref_tp := ref_tp + 1) if dd else (ref_fp := ref_fp + 1)

    total = tp + fp + fn + tn
    prec, rec, agree = _rate(tp, fp, fn, tn)
    print(f"\nevaluable pairs: {total}")
    print(f"  our-flag & DDInter lists (true pos):      {tp}")
    print(f"  our-flag, DDInter silent (over-flag):     {fp}")
    print(f"  DDInter lists, we miss (under-flag):      {fn}")
    print(f"  both silent (true neg):                   {tn}")
    print(f"\nALL flags   -> precision {prec:.1f}%  recall {rec:.1f}%  agreement {agree:.1f}%")
    if ref_tp + ref_fp:
        print(f"REFERENCE-DDI flags only -> precision {ref_tp / (ref_tp + ref_fp) * 100:.1f}% "
              f"({ref_tp}/{ref_tp + ref_fp} confirmed by DDInter)")


if __name__ == "__main__":
    main()
