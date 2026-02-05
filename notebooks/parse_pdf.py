# parse_pdf.py
"""
Extracts tables from the PDF into a raw CSV for clean_data.py to process.

FAST path: tabula-py (needs Java installed locally)
Fallback path: pdfplumber text scrape (works without Java, but is less reliable)

Output CSV should include columns:
- NAME
- Enzyme(s)
- Transporter(s)

Run:
  python parse_pdf.py --pdf Organ-Impairment-Drug-Interaction-database-PDF.pdf --out ../data/processed/drug_interactions_raw.csv
"""

import os
import re
import argparse
from typing import List

import pandas as pd


def try_tabula(pdf_path: str) -> pd.DataFrame:
    import tabula  # tabula-py

    # Read all pages, multiple tables
    tables: List[pd.DataFrame] = tabula.read_pdf(
        pdf_path,
        pages="all",
        multiple_tables=True,
        lattice=False,
        stream=True,
    )

    # Filter empty-ish
    tables = [t for t in tables if t is not None and not t.empty]
    if not tables:
        raise RuntimeError("tabula found 0 tables")

    df = pd.concat(tables, ignore_index=True)

    return df


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tries to coerce whatever was extracted into the 3 columns we need.
    This is intentionally defensive: PDF extraction is messy.
    """
    # Flatten multi-index cols if any
    df.columns = [str(c).strip() for c in df.columns]

    # Heuristic: look for columns that resemble name/enzyme/transporter
    colmap = {}
    for c in df.columns:
        cl = c.lower()
        if "name" in cl and "enzyme" not in cl and "transporter" not in cl:
            colmap[c] = "NAME"
        elif "enzyme" in cl:
            colmap[c] = "Enzyme(s)"
        elif "transporter" in cl:
            colmap[c] = "Transporter(s)"

    # If we found at least some, rename and keep
    if colmap:
        df = df.rename(columns=colmap)
        keep = [c for c in ["NAME", "Enzyme(s)", "Transporter(s)"] if c in df.columns]
        df = df[keep]
        return df

    # If columns are generic like "Unnamed: 0", attempt positional fallback (common in tabula)
    if len(df.columns) >= 3:
        df = df.iloc[:, :3].copy()
        df.columns = ["NAME", "Enzyme(s)", "Transporter(s)"]
        return df

    raise RuntimeError(f"Could not normalize columns. Extracted columns: {list(df.columns)}")


def try_pdfplumber(pdf_path: str) -> pd.DataFrame:
    """
    Fallback: extract text lines and attempt regex parsing.
    This depends heavily on how the PDF is formatted.
    """
    import pdfplumber

    rows = []
    # Example loose regex: "DrugName ... Enzyme(s): ... Transporter(s): ..."
    # If your PDF isn't like this, you'll need to tweak the parsing rules.
    enzyme_pat = re.compile(r"(CYP[0-9A-Z]+|UGT[0-9A-Z]+|SULT[0-9A-Z]+)", re.IGNORECASE)
    transporter_pat = re.compile(r"(P-?GP|BCRP|OATP|OAT|OCT|MATE)", re.IGNORECASE)

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Super conservative: only keep lines that look like they contain enzyme/transporter tokens
                enz = enzyme_pat.findall(line)
                trn = transporter_pat.findall(line)
                if not enz and not trn:
                    continue

                # Guess drug name as first chunk before two+ spaces (very heuristic)
                drug = re.split(r"\s{2,}", line)[0].strip()
                if not drug or len(drug) < 2:
                    continue

                rows.append(
                    {
                        "NAME": drug,
                        "Enzyme(s)": " | ".join(sorted({e.upper() for e in enz})),
                        "Transporter(s)": " | ".join(sorted({t.upper().replace("PGP", "P-GP") for t in trn})),
                    }
                )

    if not rows:
        raise RuntimeError("pdfplumber fallback produced 0 rows (needs custom parsing rules for this PDF)")

    return pd.DataFrame(rows)


def main(pdf_path: str, out_path: str) -> None:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # 1) Try tabula (best for table PDFs)
    extracted = None
    tabula_err = None
    try:
        extracted = try_tabula(pdf_path)
        extracted = normalize_columns(extracted)
        method = "tabula"
    except Exception as e:
        tabula_err = str(e)

    # 2) Fallback to pdfplumber (text heuristic)
    if extracted is None:
        extracted = try_pdfplumber(pdf_path)
        extracted = normalize_columns(extracted)
        method = "pdfplumber"

    # Basic cleanup
    for c in ["NAME", "Enzyme(s)", "Transporter(s)"]:
        if c in extracted.columns:
            extracted[c] = extracted[c].astype(str).str.replace("nan", "", regex=False).str.strip()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    extracted.to_csv(out_path, index=False)
    print(f"✅ Extracted via {method}: {len(extracted)} rows -> {out_path}")

    if method == "pdfplumber":
        print("⚠️ pdfplumber fallback is heuristic. If output looks messy, use tabula with Java installed.")
    if tabula_err:
        print(f"(tabula attempt failed: {tabula_err})")


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdf",
        default=os.path.join(base, "Organ-Impairment-Drug-Interaction-database-PDF.pdf"),
        help="Path to source PDF",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(base, "..", "data", "processed", "drug_interactions_raw.csv"),
        help="Path to write raw CSV",
    )
    args = parser.parse_args()

    main(args.pdf, args.out)
