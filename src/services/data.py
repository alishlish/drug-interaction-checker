from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

import pandas as pd


def _norm_text(s: Optional[str]) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return str(s).replace("–", "-").replace("—", "-").strip()


@dataclass(frozen=True)
class DataStore:
    data_path: str
    drug_map: Dict[str, Dict[str, str]]
    drug_names: List[str]


def load_datastore(data_path: str) -> DataStore:
    """
    Load CSV once at startup and return a DataStore.
    Expected columns: drug_name, enzymes (optional), transporters (optional)
    """
    if not os.path.exists(data_path):
        raise RuntimeError(
            f"Could not find drug interaction CSV at {data_path}. "
            f"Set DRUG_DATA_PATH env var or ensure the file exists."
        )

    df = pd.read_csv(data_path)

    if "drug_name" not in df.columns:
        raise RuntimeError(f"CSV missing required column 'drug_name'. Found columns: {list(df.columns)}")

    df["drug_name"] = df["drug_name"].astype(str).str.lower().str.strip()

    drug_map: Dict[str, Dict[str, str]] = {}
    for _, row in df.iterrows():
        name = str(row["drug_name"]).lower().strip()
        enzymes = _norm_text(row["enzymes"]) if "enzymes" in df.columns else ""
        transporters = _norm_text(row["transporters"]) if "transporters" in df.columns else ""
        drug_map[name] = {"enzymes": enzymes, "transporters": transporters}

    drug_names = sorted(drug_map.keys())
    return DataStore(data_path=data_path, drug_map=drug_map, drug_names=drug_names)


def normalize_drug_name(name: str) -> str:
    return (name or "").lower().strip()


def get_drug(datastore: DataStore, drug_name: str) -> Dict[str, Any]:
    key = normalize_drug_name(drug_name)
    row = datastore.drug_map.get(key)
    if not row:
        return {"name": key, "enzymes": None, "transporters": None, "found": False}

    enzymes = (row.get("enzymes") or "").strip() or None
    transporters = (row.get("transporters") or "").strip() or None
    return {"name": key, "enzymes": enzymes, "transporters": transporters, "found": True}


def search_drugs(datastore: DataStore, query: str, limit: int = 50) -> List[str]:
    q = normalize_drug_name(query)
    if not q:
        return []
    matches = [name for name in datastore.drug_names if q in name]
    return matches[:limit]
