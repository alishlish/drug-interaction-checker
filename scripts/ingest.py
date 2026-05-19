"""
One-time script: embed each drug row from the CSV and upsert to Pinecone.

Run from project root:
    python scripts/ingest.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from openai import OpenAI
from pinecone import Pinecone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = PROJECT_ROOT / "data" / "processed" / "drug_interactions_clean.csv"

PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "drug-interactions")
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50


def row_to_text(row: dict) -> str:
    fields = [
        ("Drug", row.get("drug_name", "")),
        ("CAS number", row.get("cas_number", "")),
        ("Renal clearance", row.get("renal", "")),
        ("Non-renal clearance", row.get("non_renal", "")),
        ("Fraction excreted unchanged (fe)", row.get("fe", "")),
        ("Bioavailability (F)", row.get("f", "")),
        ("Enzymes", row.get("enzymes", "") or "none"),
        ("Transporters", row.get("transporters", "") or "none"),
        ("Route of administration", row.get("route_of_admin", "")),
        ("Delta AUC%", row.get("delta_auc_pct", "")),
        ("Delta CL/F%", row.get("delta_cl_over_f_pct", "")),
        ("Reference inhibitor", row.get("inhibitor", "")),
    ]
    return "\n".join(f"{k}: {v}" for k, v in fields if v and str(v).strip() not in ("", "nan"))


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df["drug_name"] = df["drug_name"].astype(str).str.lower().str.strip()
    df = df[df["drug_name"] != ""]

    records = df.to_dict(orient="records")
    print(f"Loaded {len(records)} drugs from CSV")

    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    for batch_start in range(0, len(records), BATCH_SIZE):
        batch = records[batch_start : batch_start + BATCH_SIZE]
        texts = [row_to_text(r) for r in batch]

        resp = openai_client.embeddings.create(model=EMBED_MODEL, input=texts)
        embeddings = [e.embedding for e in resp.data]

        vectors = []
        for row, emb in zip(batch, embeddings):
            drug_id = row["drug_name"].replace(" ", "_").replace("/", "_")
            metadata = {k: str(v) for k, v in row.items()}
            vectors.append({"id": drug_id, "values": emb, "metadata": metadata})

        index.upsert(vectors=vectors)
        print(f"  Upserted {batch_start + len(batch)}/{len(records)}")

    print("Done — Pinecone index populated.")


if __name__ == "__main__":
    main()
