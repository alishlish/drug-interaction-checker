from __future__ import annotations

import re
from typing import Dict, Any, Set
from .data import DataStore

TRANSPORTERS: Set[str] = {"P-GP", "BCRP", "OATP", "OAT", "OCT", "MATE"}

_SPLIT_RE = re.compile(r"\s*\|\s*|\s*,\s*|\s*;\s*|\s*/\s*")


def _tokenize(s: str) -> Set[str]:
    s = (s or "").replace("–", "-").replace("—", "-").strip().upper()
    if not s:
        return set()
    parts = _SPLIT_RE.split(s)
    return {p.strip() for p in parts if p and p.strip() and p.strip() != "NAN"}


def _severity_from_hits(shared_cyps: Set[str], shared_transporters: Set[str]) -> str:
    hits = len(shared_cyps) + len(shared_transporters)
    if hits == 0:
        return "none"
    if hits == 1:
        return "mild"
    return "moderate"


def find_interaction(datastore: DataStore, drug1: str, drug2: str) -> Dict[str, Any]:
    """
    Deterministic rule-based interaction:
    - shared enzyme tokens OR shared canonical transporters
    """
    d1 = datastore.drug_map.get(drug1)
    d2 = datastore.drug_map.get(drug2)

    if not d1 or not d2:
        return {"drug_pair": [drug1, drug2], "interaction": "Drug not found", "severity": "unknown"}

    e1 = _tokenize(d1.get("enzymes", ""))
    e2 = _tokenize(d2.get("enzymes", ""))
    t1 = _tokenize(d1.get("transporters", ""))
    t2 = _tokenize(d2.get("transporters", ""))

    shared_cyps = e1 & e2
    shared_transporters = (t1 & t2) & TRANSPORTERS

    severity = _severity_from_hits(shared_cyps, shared_transporters)

    if severity == "none":
        interaction = "No significant interaction found"
    else:
        bits = []
        if shared_cyps:
            bits.append(f"shared enzymes: {', '.join(sorted(shared_cyps))}")
        if shared_transporters:
            bits.append(f"shared transporters: {', '.join(sorted(shared_transporters))}")
        interaction = "Potential interaction due to " + " and ".join(bits)

    return {
        "drug_pair": [drug1, drug2],
        "interaction": interaction,
        "severity": severity,
    }
