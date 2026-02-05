import pandas as pd
import re

def clean(raw_csv, out_csv):
    df = pd.read_csv(raw_csv)

    df.columns = [c.strip().lower() for c in df.columns]

    # remove header/legend rows
    df = df[~df.iloc[:,0].str.contains(
        r"δ|admin|route|auc|cl/f", case=False, na=False
    )]

    # normalize drug names
    df["drug_name"] = (
        df.iloc[:,0]
        .str.lower()
        .str.strip()
    )

    df = df[df["drug_name"].str.len() > 2]

    df = df.rename(columns={
        "renal": "renal_impairment",
        "non-renal": "hepatic_impairment",
        "enzyme(s)": "enzymes",
        "transporter(s)": "transporters"
    })

    df = df[[
        "drug_name",
        "renal_impairment",
        "hepatic_impairment",
        "enzymes",
        "transporters"
    ]]

    df.to_csv(out_csv, index=False)

if __name__ == "__main__":
    clean(
        "data/raw/extracted_tables.csv",
        "data/processed/drug_interactions_clean.csv"
    )
