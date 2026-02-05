from __future__ import annotations

import re
from typing import Dict, Any, Set
from .data import DataStore

TRANSPORTERS: Set[str] = {"P-GP", "BCRP", "OATP", "OAT", "OCT", "MATE"}
_SPLIT_RE = re.compile(r"\s*\|\s*|\s*,\s*|\s*;\s*|\s*/\s*")


def _tokenize(s: str) -> Set[str]:
    s = (s or "").replace("–", "-").replace("—", "-").strip().upper()
    if not s or s == "NAN":
        return set()
    parts = _SPLIT_RE.split(s)
    return {p.strip() for p in parts if p and p.strip() and p.strip() != "NAN"}


def _norm_name(s: str) -> str:
    return (s or "").strip().lower()


def _severity_from_ref(delta_auc_pct: str) -> str:
    """
    Very conservative heuristic based ONLY on the dataset's delta AUC field.
    If delta AUC missing or non-numeric => 'unknown' (don’t guess).
    """
    try:
        x = float(delta_auc_pct)
    except Exception:
        return "unknown"

    # Conservative tiers; you can adjust later
    if x >= 200:
        return "high"
    if x >= 50:
        return "moderate"
    if x > 0:
        return "mild"
    return "none"


def find_interaction(datastore: DataStore, d1: str, d2: str) -> Dict[str, Any]:
    r1 = datastore.drug_map.get(d1)
    r2 = datastore.drug_map.get(d2)

    if not r1 or not r2:
        return {
            "drug_pair": [d1, d2],
            "interaction": "Drug not found",
            "severity": "unknown",
            "evidence": {"type": "missing_drug"},
        }

    # -------------------------
    # 1) Reference DDI evidence (PRIMARY)
    # -------------------------
    inh1 = _norm_name(r1.get("inhibitor", ""))
    inh2 = _norm_name(r2.get("inhibitor", ""))

    ref_hit = None
    if inh1 and inh1 == d2:
        ref_hit = {
            "direction": f"{d2} listed as inhibitor/reference drug for {d1}",
            "delta_auc_pct": (r1.get("delta_auc_pct") or "").strip(),
            "delta_auc_ref_pct": (r1.get("delta_auc_ref_pct") or "").strip(),
            "ref_ddi": (r1.get("ref_ddi") or "").strip(),
            "route_of_admin": (r1.get("route_of_admin") or "").strip(),
            "route_of_admin_ref": (r1.get("route_of_admin_ref") or "").strip(),
        }
    elif inh2 and inh2 == d1:
        ref_hit = {
            "direction": f"{d1} listed as inhibitor/reference drug for {d2}",
            "delta_auc_pct": (r2.get("delta_auc_pct") or "").strip(),
            "delta_auc_ref_pct": (r2.get("delta_auc_ref_pct") or "").strip(),
            "ref_ddi": (r2.get("ref_ddi") or "").strip(),
            "route_of_admin": (r2.get("route_of_admin") or "").strip(),
            "route_of_admin_ref": (r2.get("route_of_admin_ref") or "").strip(),
        }

    if ref_hit:
        sev = _severity_from_ref(ref_hit.get("delta_auc_pct", ""))
        msg = "Reference interaction found in dataset"
        return {
            "drug_pair": [d1, d2],
            "interaction": msg,
            "severity": sev,
            "evidence": {"type": "reference_ddi", **ref_hit},
        }

    # -------------------------
    # 2) Mechanism overlap (SECONDARY / fallback)
    # -------------------------
    e1 = _tokenize(r1.get("enzymes", ""))
    e2 = _tokenize(r2.get("enzymes", ""))
    t1 = _tokenize(r1.get("transporters", ""))
    t2 = _tokenize(r2.get("transporters", ""))

    shared_enz = e1 & e2
    shared_trn = (t1 & t2) & TRANSPORTERS

    if not shared_enz and not shared_trn:
        return {
            "drug_pair": [d1, d2],
            "interaction": "No interaction evidence found in dataset for this pair",
            "severity": "none",
            "evidence": {"type": "none"},
        }

    parts = []
    if shared_enz:
        parts.append(f"shared enzymes: {', '.join(sorted(shared_enz))}")
    if shared_trn:
        parts.append(f"shared transporters: {', '.join(sorted(shared_trn))}")

    return {
        "drug_pair": [d1, d2],
        "interaction": "Potential interaction mechanism overlap (" + " and ".join(parts) + ")",
        "severity": "mild" if (len(shared_enz) + len(shared_trn)) == 1 else "moderate",
        "evidence": {
            "type": "mechanism_overlap",
            "shared_enzymes": sorted(shared_enz),
            "shared_transporters": sorted(shared_trn),
        },
    }
