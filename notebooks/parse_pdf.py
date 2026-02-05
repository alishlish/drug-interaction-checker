"""
Parse Organ-Impairment Drug Interaction PDF tables into a clean CSV.

Input:
  - data/raw/Organ-Impairment-Drug-Interaction-database-PDF.pdf

Output:
  - data/processed/drug_interactions_clean.csv

Notes:
- This parser only keeps rows that look like true drug rows (CAS number present).
- It also tries to stitch wrapped text across adjacent columns for enzyme/name/transporters.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pdfplumber


# ----------------------------
# Paths
# ----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = PROJECT_ROOT / "data" / "Organ-Impairment-Drug-Interaction-database-PDF.pdf"
OUT_CSV = PROJECT_ROOT / "data" / "processed" / "drug_interactions_clean.csv"


# ----------------------------
# Heuristics / helpers
# ----------------------------
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")  # e.g., 128196-01-0


def is_cas(s: Any) -> bool:
    if s is None:
        return False
    return bool(CAS_RE.match(str(s).strip()))


def clean_cell(x: Any) -> str:
    if x is None:
        return ""
    s = str(x)
    s = s.replace("\n", " ").replace("\r", " ")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def join_nonempty(*parts: Any, sep: str = " ") -> str:
    cleaned = [clean_cell(p) for p in parts]
    cleaned = [c for c in cleaned if c]
    return sep.join(cleaned).strip()


def safe_float_str(s: str) -> Optional[str]:
    """
    Return string if it looks numeric-ish (e.g., 0.45, -57.1, 91.4), else None.
    """
    s = clean_cell(s)
    if not s:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    return None


def normalize_col_name(c: str) -> str:
    return (
        c.strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("-", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("%", "pct")
    )


# ----------------------------
# Row parsing
# ----------------------------
def parse_row(cells: List[Any]) -> Dict[str, Any]:
    """
    pdfplumber gives us ~20 columns per row (based on the PDF table layout).
    Some cells wrap across columns; we stitch the most important ones.
    """
    # Ensure length >= 20
    row = list(cells) + [""] * (20 - len(cells))
    row = row[:20]
    row = [clean_cell(x) for x in row]

    # Based on observed structure from the PDF:
    # 0 CAS number
    # 1 NAME
    # 2 fe
    # 3 (sometimes fe spills here if name wraps weirdly; we handle via fallback)
    # 5/6 F
    # 7 Renal
    # 8 Non-renal
    # 9/10 Enzyme(s) (often spans two cols)
    # 11 Transporter(s)
    # 12 Route of Admin (sometimes transporter spills into 12; heuristic below)
    # 13 Δ%AUC
    # 14 Δ %CL/F
    # 15 inhibitor
    # 16 Ref DDI (PMID or NDA etc)
    # 17 Route of Admin (ref)
    # 18 ΔAUC(%)
    # 19 (sometimes a second numeric column)

    cas_number = row[0]
    drug_name = row[1]

    # fe: try col2 first, else col3 if numeric
    fe = safe_float_str(row[2]) or safe_float_str(row[3]) or row[2] or row[3]
    fe = fe if fe else ""

    # F: usually around col5-6-?; try numeric first, else keep text if present
    F = safe_float_str(row[5]) or safe_float_str(row[6]) or row[5] or row[6]
    F = F if F else ""

    renal = row[7]
    non_renal = row[8]

    enzymes = join_nonempty(row[9], row[10])
    transporters = row[11]

    # Heuristic: if route_of_admin looks like it accidentally contains transporter tail,
    # stitch it back into transporters when transporter column looks cut off.
    route_of_admin = row[12]
    route_tokens = {"po", "iv", "im", "sc", "sq", "inhaled", "topical", "oral"}

    # If route_of_admin doesn't look like a route and transporters looks truncated, merge
    if route_of_admin and route_of_admin.lower() not in route_tokens:
        # if route cell contains a route token later ("m po" etc), keep it in route and merge prefix to transporters
        m = re.search(r"\b(po|iv|im|sc|sq|oral)\b", route_of_admin.lower())
        if m:
            # split at the first route token
            idx = m.start()
            prefix = route_of_admin[:idx].strip()
            suffix = route_of_admin[idx:].strip()
            if prefix:
                transporters = join_nonempty(transporters, prefix)
            route_of_admin = suffix
        else:
            # otherwise assume it's part of transporters
            transporters = join_nonempty(transporters, route_of_admin)
            route_of_admin = ""

    # max DDI observed fields (keep as strings, your API will expose as attributes)
    delta_auc = row[13]
    delta_clf = row[14]
    inhibitor = row[15]
    ref_ddi = row[16]
    route_of_admin_ref = row[17]
    delta_auc_ref = row[18]
    extra_col = row[19]

    record = {
        "cas_number": cas_number,
        "drug_name": drug_name.lower().strip(),
        "fe": fe,
        "f": F,
        "renal": renal,
        "non_renal": non_renal,
        "enzymes": enzymes,
        "transporters": transporters,
        "route_of_admin": route_of_admin,
        "delta_auc_pct": delta_auc,
        "delta_cl_over_f_pct": delta_clf,
        "inhibitor": inhibitor,
        "ref_ddi": ref_ddi,
        "route_of_admin_ref": route_of_admin_ref,
        "delta_auc_ref_pct": delta_auc_ref,
        "extra": extra_col,
    }

    return record


# ----------------------------
# Main extraction
# ----------------------------
def extract_pdf_to_csv(pdf_path: Path, out_csv: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for pageno, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                for cells in table:
                    if not cells:
                        continue

                    # Only keep drug rows (CAS number in first cell)
                    first = clean_cell(cells[0]) if len(cells) > 0 else ""
                    if not is_cas(first):
                        continue

                    rec = parse_row(cells)
                    if rec.get("drug_name"):
                        records.append(rec)

    if not records:
        raise RuntimeError("No drug rows found. Table extraction may need tuning.")

    df = pd.DataFrame(records)

    # Drop duplicates by drug_name (keep first)
    df = df[df["drug_name"].astype(str).str.strip() != ""]
    df = df.drop_duplicates(subset=["drug_name"], keep="first")

    # Final polish: normalize whitespace everywhere
    for col in df.columns:
        df[col] = df[col].astype(str).map(clean_cell)

    df.to_csv(out_csv, index=False)
    print(f"✅ Wrote {len(df)} drugs → {out_csv}")


if __name__ == "__main__":
    print("PDF:", PDF_PATH)
    print("OUT:", OUT_CSV)
    extract_pdf_to_csv(PDF_PATH, OUT_CSV)
