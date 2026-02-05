import pandas as pd
import csv

RAW_PATH = "data/processed/drug_interactions_raw.csv"
OUT_PATH = "data/processed/drug_interactions_clean.csv"


def clean_text(val):
    if pd.isna(val):
        return ""
    return str(val).replace("\n", " ").replace("\r", " ").strip()


def norm_col(col: str) -> str:
    return (
        col.strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("-", "_")
        .replace("(", "")
        .replace(")", "")
    )


def main():
    df = pd.read_csv(
        RAW_PATH,
        engine="python",
        sep=",",
        quoting=csv.QUOTE_MINIMAL,
        on_bad_lines="skip",
    )

    print("Loaded raw shape:", df.shape)
    print("Columns:", df.columns.tolist())

    # normalize column names first
    original_cols = list(df.columns)
    df.columns = [norm_col(c) for c in df.columns]

    # map known raw headers to canonical headers used by the app
    # (based on what you printed)
    rename_map = {
        "name": "drug_name",
        "enzyme_s": "enzymes",
        "transporter_s": "transporters",
        "cas_number": "cas_number",
        "renal": "renal",
        "non_renal": "non_renal",
        "route_of": "route_of",
        "fe": "fe",
        "f": "f",
    }

    # apply rename if those columns exist
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    print("Normalized columns:", df.columns.tolist())

    if "drug_name" not in df.columns:
        raise RuntimeError(
            "Could not derive drug_name column. "
            f"Columns after normalization: {df.columns.tolist()}"
        )

    # clean all cells to single-line strings
    for col in df.columns:
        df[col] = df[col].apply(clean_text)

    # normalize drug names for your API lookup
    df["drug_name"] = df["drug_name"].astype(str).str.lower().str.strip()

    # drop blank names
    df = df[df["drug_name"].str.strip() != ""]

    # drop duplicates by drug_name (keep first)
    df = df.drop_duplicates(subset=["drug_name"])

    df.to_csv(OUT_PATH, index=False)
    print(f"Saved cleaned CSV → {OUT_PATH}")
    print("Final shape:", df.shape)


if __name__ == "__main__":
    main()
