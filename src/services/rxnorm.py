"""RxNorm (RxNav) drug-identity resolution.

RxNav is a free NIH/NLM REST API (no key required). A raw drug name is resolved
to an RxCUI in one of three confidence tiers:

    exact        an exact name / synonym / brand match — safe to use directly
    approximate  a fuzzy match — a SUGGESTION ONLY, never auto-applied
    unresolved   nothing plausible found

This is the "identity" layer the project deliberately does NOT do with
embeddings (embeddings match meaning, not identity). RxNorm is an authoritative
terminology, so it answers "is this a real drug, and which one?" correctly —
and recognizes brand names (Tylenol, Coumadin) that our generic-only CSV cannot.

IMPORTANT — approximate is suggestion-only. RxNav's fuzzy matcher is permissive:
calibration showed real typos ("warfrin"→warfarin) score ~8, but common English
words fuzzy-match too ("banana"→a product scores ~12). Score therefore cannot
separate a drug typo from a coincidental word match. So an `approximate` result
must be surfaced for user confirmation ("did you mean warfarin?"), never
silently substituted — consistent with the project's no-silent-substitution
guarantee. Only `exact` is safe to consume automatically.

Only the standard library is used (urllib), so this adds no dependency, and
lookups are cached so repeated calls don't re-hit the network.

API docs: https://lhncbc.nlm.nih.gov/RxNav/APIs/
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

BASE = "https://rxnav.nlm.nih.gov/REST"
# Calibrated against live RxNav: real typos score ~8 (warfrin, candesartn,
# ibuprofn), weak noise scores <5 (hello 3.97), pure garbage returns no
# candidate. 6.0 drops the weakest noise while keeping real typos. Note this
# only gates whether we bother SUGGESTING — an approximate hit is never
# auto-applied (see module docstring), so a permissive cutoff is low-risk.
APPROX_SCORE_CUTOFF = 6.0
_TIMEOUT = 6.0


@dataclass(frozen=True)
class RxNormMatch:
    query: str
    tier: str                 # "exact" | "approximate" | "unresolved"
    rxcui: Optional[str] = None
    name: Optional[str] = None   # canonical RxNorm name of the match
    score: Optional[float] = None

    @property
    def resolved(self) -> bool:
        return self.tier != "unresolved"


def _get(path: str, **params) -> dict:
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode())


def _name_for(rxcui: str) -> Optional[str]:
    try:
        data = _get(f"rxcui/{rxcui}/property.json", propName="RxNorm Name")
        props = (data.get("propConceptGroup") or {}).get("propConcept") or []
        return props[0]["propValue"] if props else None
    except Exception:
        return None


@lru_cache(maxsize=2048)
def resolve(name: str) -> RxNormMatch:
    """Resolve a raw drug name to an RxCUI with a confidence tier. Cached."""
    q = (name or "").strip()
    if not q:
        return RxNormMatch(name or "", "unresolved")

    # 1) exact name / synonym / brand match
    try:
        data = _get("rxcui.json", name=q, search="1")
        ids = (data.get("idGroup") or {}).get("rxnormId") or []
        if ids:
            return RxNormMatch(q, "exact", ids[0], _name_for(ids[0]) or q, 100.0)
    except Exception:
        pass

    # 2) approximate (fuzzy) match
    try:
        data = _get("approximateTerm.json", term=q, maxEntries="1")
        cands = (data.get("approximateGroup") or {}).get("candidate") or []
        if cands and cands[0].get("rxcui"):
            c = cands[0]
            score = float(c.get("score", 0))
            if score >= APPROX_SCORE_CUTOFF:
                return RxNormMatch(q, "approximate", c["rxcui"], _name_for(c["rxcui"]), score)
    except Exception:
        pass

    return RxNormMatch(q, "unresolved")


def ingredient_rxcuis(rxcui: str) -> list:
    """Ingredient (tty=IN) RxCUIs for a concept — links a brand/product back to
    its active ingredient (e.g. Diflucan 202813 -> fluconazole 4450). For an
    ingredient itself this is empty or [itself]. Network + best-effort."""
    try:
        data = _get(f"rxcui/{rxcui}/related.json", tty="IN")
    except Exception:
        return []
    groups = (data.get("relatedGroup") or {}).get("conceptGroup") or []
    return [c["rxcui"] for g in groups for c in (g.get("conceptProperties") or []) if c.get("rxcui")]


def _selfcheck():
    """One runnable check (hits the live API): drug, brand, typo, nonsense."""
    exact = resolve("warfarin")
    assert exact.tier == "exact" and exact.rxcui == "11289", exact
    brand = resolve("Tylenol")
    assert brand.tier == "exact" and brand.rxcui, brand           # brands resolve exactly
    typo = resolve("warfrin")
    assert typo.tier == "approximate" and typo.rxcui == "11289", typo  # suggestion, right RxCUI
    nonsense = resolve("asdfghjklqwerty")
    assert nonsense.tier == "unresolved", nonsense
    print("rxnorm selfcheck OK")
    for m in (exact, brand, typo, nonsense):
        print(f"  {m.query:18} -> {m.tier:11} rxcui={m.rxcui} name={m.name} score={m.score}")


if __name__ == "__main__":
    _selfcheck()
