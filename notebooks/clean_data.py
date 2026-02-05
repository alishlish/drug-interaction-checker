# clean_data.py
"""
Takes a raw CSV extracted from the PDF and produces a clean CSV that the API uses.

Input (raw CSV) expected columns (case-insensitive-ish):
- NAME (or drug name)
- Enzyme(s)
- Transporter(s)

Output:
- drug_name (lowercased)
- enzymes (string, entries separated by " | ")
- transporters (string, entries separated by " | ")

Key upgrades vs your current version:
- merges duplicates instead of dropping them (so you don't lose enzymes/transporters)
- normalizes hyphens/dashes and whitespace
- robust paths + CLI args
"""

import os
import re
import argparse
from collections import defaultdict

import pandas as pd


def norm(s: str) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return (
        str(s)
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )


def normalize_delims(s: str) -> str:
    """Make separators more consistent so matching is less brittle."""
    s = norm(s)
    # convert common delimiters to " | " style
    s = re.sub(r"\s*[,;/]\s*", " | ", s)
    s = re.sub(r"\s*\|\s*", " | ", s)
    return s


def pick_col(df: pd.DataFrame, candidates: list[str]) -> str:
    cols = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    raise ValueError(f"Missing required column. Tried: {candidates}. Found: {list(df.columns)}")


def main(input_path: str, output_path: str) -> None:
    raw = pd.read_csv(input_path)

    name_col = pick_col(raw, ["NAME", "Drug", "Drug Name", "drug_name"])
    enz_col = pick_col(raw, ["Enzyme(s)", "Enzymes", "enzyme", "enzymes"])
    trn_col = pick_col(raw, ["Transporter(s)", "Transporters", "transporter", "transporters"])

    # Keyword filters (same spirit as your current one)
    enzyme_keywords = ["CYP", "UGT", "SULT"]
    transporter_keywords = ["P-GP", "PGLYCOPROTEIN", "BCRP", "OATP", "OAT", "OCT", "MATE"]

    agg = defaultdict(lambda: {"enzymes": set(), "transporters": set()})

    for _, row in raw.iterrows():
        drug_name = norm(row.get(name_col, "")).lower()
        if not drug_name:
            continue

        enzymes = normalize_delims(row.get(enz_col, ""))
        transporters = normalize_delims(row.get(trn_col, ""))

        enz_upper = enzymes.upper()
        trn_upper = transporters.upper()

        has_valid_enzyme = any(k in enz_upper for k in enzyme_keywords)
        has_valid_transporter = any(k in trn_upper for k in transporter_keywords)

        # Keep only if it has something useful
        if not (has_valid_enzyme or has_valid_transporter):
            continue

        if has_valid_enzyme and enzymes:
            # split on our canonical separator
            for token in [t.strip() for t in enzymes.split(" | ") if t.strip()]:
                agg[drug_name]["enzymes"].add(token)

        if has_valid_transporter and transporters:
            for token in [t.strip() for t in transporters.split(" | ") if t.strip()]:
                agg[drug_name]["transporters"].add(token)

    rows = []
    for name, vals in agg.items():
        rows.append(
            {
                "drug_name": name,
                "enzymes": " | ".join(sorted(vals["enzymes"])),
                "transporters": " | ".join(sorted(vals["transporters"])),
            }
        )

    out = pd.DataFrame(rows).sort_values("drug_name")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out.to_csv(output_path, index=False)

    print(f"✅ Wrote {len(out)} cleaned drugs to: {output_path}")


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=os.path.join(base, "..", "data", "processed", "drug_interactions_raw.csv"),
        help="Path to raw extracted CSV",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(base, "..", "data", "processed", "drug_interactions_clean.csv"),
        help="Path to write cleaned CSV",
    )
    args = parser.parse_args()

    main(args.input, args.output)
