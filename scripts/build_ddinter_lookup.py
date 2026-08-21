"""Build a runtime DDInter lookup limited to THIS project's drug pairs.

Reads the raw DDInter CSVs + the RxCUI map, joins on the RxNorm-canonical name,
and writes data/processed/ddinter_pairs.json:

    {"drug1|drug2": "Major", ...}   # keys are this dataset's sorted drug names

Small (only pairs among our 271 drugs), so it's a clean derived artifact. The
raw DDInter data and this lookup are gitignored; run this after downloading
DDInter (see data/ddinter/README.md).

Run: python -m scripts.build_ddinter_lookup
"""
from __future__ import annotations

import csv
import glob
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.data import load_datastore

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "processed" / "drug_interactions_clean.csv"
RXCUI = ROOT / "data" / "processed" / "drug_rxcui.json"
OUT = ROOT / "data" / "processed" / "ddinter_pairs.json"
DDINTER_GLOB = str(ROOT / "data" / "ddinter" / "ddinter_downloads_code_*.csv")


def _load_ddinter_pairs():
    pairs = {}
    for path in glob.glob(DDINTER_GLOB):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                a = (row.get("Drug_A") or "").strip().lower()
                b = (row.get("Drug_B") or "").strip().lower()
                if a and b:
                    pairs[frozenset((a, b))] = (row.get("Level") or "").strip()
    return pairs


def main():
    if not glob.glob(DDINTER_GLOB):
        sys.exit("No DDInter CSVs in data/ddinter/ — download them first (see data/ddinter/README.md).")

    ds = load_datastore(str(CSV))
    rxmap = json.load(open(RXCUI))
    dd = _load_ddinter_pairs()

    join = {name: (rxmap.get(name, {}).get("rxnorm_name") or name).strip().lower()
            for name in ds.drug_names}

    lookup = {}
    for a, b in combinations(ds.drug_names, 2):
        level = dd.get(frozenset((join[a], join[b])))
        if level:
            lookup["|".join(sorted((a, b)))] = level

    OUT.write_text(json.dumps(lookup, indent=0))
    print(f"wrote {len(lookup)} DDInter pairs among dataset drugs -> {OUT}")
    print("by level:", dict(Counter(lookup.values())))


if __name__ == "__main__":
    main()
