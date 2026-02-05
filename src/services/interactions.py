from __future__ import annotations

import re
from typing import Dict, Any, Set, Tuple
from .data import DataStore

TRANSPORTERS: Set[str] = {"P-GP", "BCRP", "OATP", "OAT", "OCT", "MATE"}
_SPLIT_RE = re.compile(r"\s*\|\s*|\s*,\s*|\s*;\s*|\s*/\s*")


def _tokenize(s: str) -> Set[str]:
    s = (s or "").replace("–", "-").replace("—", "-").strip().upper()
    if not s:
        return set()
    parts = _SPLIT_RE.split(s)
    return {p.strip() for p in parts if p and p.strip() and p.strip() != "NAN"}


def _severity(shared_enz: Set[str], shared_trn: Set[str]) -> str:
    hits = len(shared_enz) + len(shared_trn)
    if hits == 0:
        return "none"
    if hits == 1:
        return "mild"
    return "moderate"


def find_interaction(datastore: DataStore, d1: str, d2: str) -> Dict[str, Any]:
    r1 = datastore.drug_map.get(d1)
    r2 = datastore.drug_map.get(d2)

    if not r1 or not r2:
        return {
            "drug_pair": [d1, d2],
            "interaction": "Drug not found",
            "severity": "unknown",
            "evidence": {"shared_enzymes": [], "shared_transporters": []},
        }

    e1 = _tokenize(r1.get("enzymes", ""))
    e2 = _tokenize(r2.get("enzymes", ""))
    t1 = _tokenize(r1.get("transporters", ""))
    t2 = _tokenize(r2.get("transporters", ""))

    shared_enz = e1 & e2
    shared_trn = (t1 & t2) & TRANSPORTERS

    sev = _severity(shared_enz, shared_trn)

    if sev == "none":
        msg = "No significant interaction found"
    else:
        parts = []
        if shared_enz:
            parts.append(f"shared enzymes: {', '.join(sorted(shared_enz))}")
        if shared_trn:
            parts.append(f"shared transporters: {', '.join(sorted(shared_trn))}")
        msg = "Potential interaction due to " + " and ".join(parts)

    return {
        "drug_pair": [d1, d2],
        "interaction": msg,
        "severity": sev,
        "evidence": {
            "shared_enzymes": sorted(shared_enz),
            "shared_transporters": sorted(shared_trn),
        },
    }
