"""Resolve a user-supplied drug name to a dataset drug.

Resolution order:
  1. exact dataset lookup (offline, authoritative)
  2. RxNorm — resolve the input, follow it to its active-ingredient RxCUI, and
     match that against the dataset's RxCUI map. This adds brand-name and
     synonym support (Diflucan -> fluconazole) for CONFIDENT (exact-tier) hits.

An approximate RxNorm hit is returned as a *suggestion*, never auto-applied —
preserving the project's no-silent-substitution guarantee. Only exact-tier
RxNorm matches (which include brands/synonyms) are resolved automatically.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from .data import DataStore, normalize_drug_name
from . import rxnorm

_MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "data", "processed", "drug_rxcui.json",
)


def _load_reverse_index(path: str = _MAP_PATH) -> dict:
    """ingredient RxCUI -> dataset drug_name, for trusted (exact/verified) rows."""
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return {}
    rev: dict = {}
    for name, v in data.items():
        if v.get("tier") in ("exact", "verified") and v.get("rxcui"):
            rev.setdefault(v["rxcui"], name)  # first dataset drug wins
    return rev


_REVERSE = _load_reverse_index()


@dataclass(frozen=True)
class Resolution:
    input: str
    found: bool
    drug_name: Optional[str] = None    # dataset drug to use (when found)
    via: str = "none"                  # "exact" | "rxnorm" | "none"
    rxcui: Optional[str] = None
    rxnorm_name: Optional[str] = None
    suggestion: Optional[str] = None   # dataset drug to suggest (needs confirmation)


def resolve_to_dataset(datastore: DataStore, name: str, use_rxnorm: bool = True) -> Resolution:
    """Map a raw name to a dataset drug. Only exact dataset hits and exact-tier
    RxNorm hits (incl. brands/synonyms) resolve; approximate hits suggest."""
    key = normalize_drug_name(name)
    if key in datastore.drug_map:
        return Resolution(name, True, key, "exact")

    if not use_rxnorm or not _REVERSE:
        return Resolution(name, False)

    m = rxnorm.resolve(name)
    if not m.rxcui:
        return Resolution(name, False)

    # Try the resolved RxCUI directly, then its ingredient(s) (brand -> ingredient).
    candidates = [m.rxcui]
    if m.rxcui not in _REVERSE:
        candidates += rxnorm.ingredient_rxcuis(m.rxcui)

    for ing in candidates:
        target = _REVERSE.get(ing)
        if not target:
            continue
        if m.tier == "exact":
            return Resolution(name, True, target, "rxnorm", ing, m.name)
        # approximate -> suggestion only, never auto-applied
        return Resolution(name, False, None, "none", ing, m.name, suggestion=target)

    return Resolution(name, False, None, "none", m.rxcui, m.name)
