from __future__ import annotations
from typing import Any, Dict

from src.constants.glossary import FIELD_LABELS, ROUTE_MAP

def yn(v: Any) -> str:
    s = str(v).strip().upper()
    if s in {"YES", "Y", "TRUE", "1"}: return "Yes"
    if s in {"NO", "N", "FALSE", "0"}: return "No"
    return str(v).strip() if v is not None else "—"

def fmt_pct(v: Any) -> str:
    s = str(v).strip()
    if not s or s.lower() == "nan": return "—"
    try:
        x = float(s)
        sign = "+" if x > 0 else ""
        return f"{sign}{x}%"
    except Exception:
        return s

def fmt_route(v: Any) -> str:
    s = str(v).strip().lower()
    if not s or s == "nan": return "—"
    return ROUTE_MAP.get(s, s.upper())

def translate_attributes(attrs: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    if not attrs:
        return out

    for key, val in attrs.items():
        label, gloss = FIELD_LABELS.get(key, (key, ""))
        if key in {"renal", "non_renal"}:
            value = yn(val)
        elif key in {"delta_auc_pct", "delta_auc_ref_pct"}:
            value = fmt_pct(val)
        elif key in {"route_of_admin", "route_of_admin_ref"}:
            value = fmt_route(val)
        else:
            value = "—" if val in (None, "", "nan", "NaN") else str(val).strip()

        out[label] = {"value": value, "gloss": gloss}

    return out
