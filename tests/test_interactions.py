"""Deterministic interaction logic — every branch, on a synthetic dataset."""
from src.services.data import DataStore
from src.services.interactions import find_interaction, unique_pairs


def _row(name, inhibitor="", enzymes="", transporters="", delta_auc_pct=""):
    return {
        "drug_name": name, "inhibitor": inhibitor, "enzymes": enzymes,
        "transporters": transporters, "delta_auc_pct": delta_auc_pct,
        "delta_auc_ref_pct": "", "ref_ddi": "", "route_of_admin": "",
        "route_of_admin_ref": "",
    }


def _ds():
    rows = {
        "a": _row("a", inhibitor="b", enzymes="CYP3A4", delta_auc_pct="250"),
        "b": _row("b", enzymes="CYP3A4"),
        "e": _row("e", enzymes="CYP3A4"),
        "c": _row("c", enzymes="CYP2D6"),
        "d": _row("d"),
    }
    return DataStore(data_path="x", drug_map=rows, drug_names=sorted(rows), attribute_cols=[])


def test_reference_ddi_high_severity():
    r = find_interaction(_ds(), "a", "b")
    assert r["evidence"]["type"] == "reference_ddi"
    assert r["severity"] == "high"  # delta AUC 250 >= 200


def test_mechanism_overlap():
    r = find_interaction(_ds(), "b", "e")
    assert r["evidence"]["type"] == "mechanism_overlap"
    assert "CYP3A4" in r["evidence"]["shared_enzymes"]


def test_no_evidence():
    r = find_interaction(_ds(), "c", "d")
    assert r["evidence"]["type"] == "none"


def test_missing_drug():
    r = find_interaction(_ds(), "a", "zzz")
    assert r["evidence"]["type"] == "missing_drug"
    assert r["interaction"] == "Drug not found"


def test_unique_pairs():
    assert unique_pairs([1, 2, 3]) == [(1, 2), (1, 3), (2, 3)]
    assert unique_pairs([1]) == []
    assert unique_pairs([]) == []


def test_ddinter_enrichment():
    rows = {"a": _row("a", enzymes="CYP3A4"), "b": _row("b", enzymes="CYP2D6")}
    ds = DataStore(data_path="x", drug_map=rows, drug_names=sorted(rows),
                   attribute_cols=[], ddinter={"a|b": "Major"})
    r = find_interaction(ds, "a", "b")
    assert r["ddinter"]["listed"] and r["ddinter"]["level"] == "Major"
    assert find_interaction(ds, "a", "zzz")["ddinter"]["listed"] is False


def test_ddinter_absent_by_default():
    # no ddinter lookup -> enrichment present but empty, no crash
    rows = {"a": _row("a", inhibitor="b"), "b": _row("b")}
    ds = DataStore(data_path="x", drug_map=rows, drug_names=sorted(rows), attribute_cols=[])
    assert find_interaction(ds, "a", "b")["ddinter"]["listed"] is False


def test_citations_consolidate_sources():
    rows = {"a": _row("a", enzymes="CYP3A4"), "b": _row("b", enzymes="CYP3A4")}
    ds = DataStore(data_path="x", drug_map=rows, drug_names=sorted(rows),
                   attribute_cols=[], ddinter={"a|b": "Major"})
    cites = find_interaction(ds, "a", "b")["citations"]
    sources = {c["source"] for c in cites}
    assert "NIH Organ-Impairment DB" in sources and "DDInter 2.0" in sources
