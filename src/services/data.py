from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Set

import pandas as pd


def _norm_text(s: Any) -> str:
    if s is None:
        return ""
    if isinstance(s, float) and pd.isna(s):
        return ""
    return str(s).replace("–", "-").replace("—", "-").strip()


def normalize_drug_name(name: str) -> str:
    return (name or "").lower().strip()


def normalize_col_name(col: str) -> str:
    # make keys consistent for JSON + UI
    return (col or "").strip().lower().replace(" ", "_")


@dataclass(frozen=True)
class DataStore:
    data_path: str
    drug_map: Dict[str, Dict[str, Any]]      # drug_name -> entire row dict (normalized)
    drug_names: List[str]
    attribute_cols: List[str]                # non-core columns you might want to show


CORE_COLS: Set[str] = {"drug_name", "enzymes", "transporters"}


def load_datastore(data_path: str) -> DataStore:
    if not os.path.exists(data_path):
        raise RuntimeError(
            f"Could not find CSV at {data_path}. Set DRUG_DATA_PATH or ensure file exists."
        )

    df = pd.read_csv(data_path)

    if "drug_name" not in df.columns:
        raise RuntimeError(f"CSV missing required 'drug_name' column. Found: {list(df.columns)}")

    # normalize columns
    df.columns = [normalize_col_name(c) for c in df.columns]
    if "drug_name" not in df.columns:
        raise RuntimeError("After normalization, 'drug_name' column missing. Check CSV headers.")

    df["drug_name"] = df["drug_name"].astype(str).str.lower().str.strip()

    # figure out what other columns exist (renal/hepatic/etc)
    attribute_cols = [c for c in df.columns if c not in CORE_COLS]

    drug_map: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        name = normalize_drug_name(row["drug_name"])
        row_dict: Dict[str, Any] = {}
        for c in df.columns:
            v = row[c]
            row_dict[c] = _norm_text(v)

        drug_map[name] = row_dict

    drug_names = sorted(drug_map.keys())
    return DataStore(
        data_path=data_path,
        drug_map=drug_map,
        drug_names=drug_names,
        attribute_cols=attribute_cols,
    )


def get_drug(datastore: DataStore, drug_name: str) -> Dict[str, Any]:
    key = normalize_drug_name(drug_name)
    row = datastore.drug_map.get(key)
    if not row:
        return {
            "name": key,
            "found": False,
            "enzymes": None,
            "transporters": None,
            "attributes": {},
        }

    enzymes = (row.get("enzymes") or "").strip() or None
    transporters = (row.get("transporters") or "").strip() or None

    # everything else becomes attributes (renal/hepatic/etc)
    attrs: Dict[str, Any] = {}
    for c in datastore.attribute_cols:
        val = (row.get(c) or "").strip()
        if val:  # only include non-empty
            attrs[c] = val

    return {
        "name": key,
        "found": True,
        "enzymes": enzymes,
        "transporters": transporters,
        "attributes": attrs,
    }


def search_drugs(datastore: DataStore, query: str, limit: int = 50) -> List[str]:
    q = normalize_drug_name(query)
    if not q:
        return []
    matches = [name for name in datastore.drug_names if q in name]
    return matches[:limit]
