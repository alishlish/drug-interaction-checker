"""Map each dataset drug_name to an RxNorm RxCUI (one-time, cached).

Anchors the project's 271 drugs to the RxNorm identity space so user input can
be resolved (name/brand/synonym) -> RxCUI -> dataset drug. Writes
data/processed/drug_rxcui.json and prints the match rate.

Run: python -m scripts.map_rxcui
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.data import load_datastore
from src.services.rxnorm import resolve

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "processed" / "drug_interactions_clean.csv"
OUT = ROOT / "data" / "processed" / "drug_rxcui.json"


def _strip_qualifiers(name: str) -> str:
    """Drop route/formulation/synonym qualifiers so a name-verification check
    can compare the core drug name: '(iv)', '(gs-9137)', '-not approved…'."""
    s = name.lower()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"-?\s*not approve.*", "", s)
    return s.strip(" -")


def _name_verified(dataset_name: str, rxnorm_name: str | None) -> bool:
    """An approximate RxNav hit is trusted ONLY if the returned name actually
    appears in the dataset name. This rejects wrong matches (clinafloxacin ->
    finafloxacin) and the garbage collapse (5 distinct drugs -> one RxCUI) while
    keeping legit variants (erythromycin (iv) -> erythromycin)."""
    rn = (rxnorm_name or "").lower().strip()
    base = _strip_qualifiers(dataset_name)
    return bool(rn) and (rn in base or base in rn)


def main():
    ds = load_datastore(str(CSV))
    names = ds.drug_names
    mapping = {}
    counts = {"exact": 0, "verified": 0, "unresolved": 0}

    for i, name in enumerate(names, 1):
        m = resolve(name)
        if m.tier == "exact":
            tier = "exact"
        elif m.tier == "approximate" and _name_verified(name, m.name):
            tier = "verified"  # approximate but the returned name checks out
        else:
            tier = "unresolved"  # exact miss, or an unverified/ wrong fuzzy hit
        counts[tier] += 1
        mapping[name] = {
            "rxcui": m.rxcui if tier != "unresolved" else None,
            "tier": tier,
            "rxnorm_name": m.name if tier != "unresolved" else None,
        }
        if i % 25 == 0:
            print(f"  {i}/{len(names)} …", flush=True)

    OUT.write_text(json.dumps(mapping, indent=2))

    total = len(names)
    trusted = counts["exact"] + counts["verified"]
    print(f"\ntotal={total}  exact={counts['exact']}  verified={counts['verified']}  "
          f"unresolved={counts['unresolved']}")
    print(f"trusted match rate: {trusted / total * 100:.1f}%  "
          f"(exact-only: {counts['exact'] / total * 100:.1f}%)")
    print(f"wrote {OUT}")

    unresolved = [n for n, v in mapping.items() if v["tier"] == "unresolved"]
    if unresolved:
        print(f"\nunresolved ({len(unresolved)}) — mostly investigational/'not approved in US':")
        for n in unresolved[:12]:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
