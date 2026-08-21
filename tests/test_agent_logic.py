"""The retrieval + organ-impairment logic extracted from the LangGraph nodes.
No OpenAI/Pinecone needed — these are pure functions."""
from src.services.agent import resolve_drug, organ_impairment_reasons


# ---- retrieval path: exact match, never substitute (the core guarantee) ----

def test_resolve_exact(datastore):
    r = resolve_drug(datastore, "Azilsartan")
    assert r["found"] is True
    assert r["drug_name"] == "azilsartan"


def test_resolve_nonsense_is_not_substituted(datastore):
    r = resolve_drug(datastore, "asdfghjkl")
    assert r["found"] is False
    assert r["_queried_as"] == "asdfghjkl"
    # must stay the queried name, NOT a similar real drug
    assert r["drug_name"] == "asdfghjkl"


def test_resolve_inhibitor_only_drug_is_absent(datastore):
    # warfarin appears only in the inhibitor column, never as a lookup key
    assert resolve_drug(datastore, "warfarin")["found"] is False


# ---- organ-impairment logic ----

def test_renal_reasons():
    reasons = organ_impairment_reasons({"fe": "0.76", "renal": "YES"}, "severe", "none")
    assert any("renal excretion" in r for r in reasons)
    assert any("renally cleared" in r for r in reasons)


def test_no_impairment_no_reasons():
    assert organ_impairment_reasons({"fe": "0.76", "renal": "YES"}, "none", "none") == []


def test_hepatic_reason():
    reasons = organ_impairment_reasons({"enzymes": "CYP3A4"}, "none", "severe")
    assert any("hepatic impairment" in r for r in reasons)


def test_hepatic_skips_unspecified_enzymes():
    assert organ_impairment_reasons({"enzymes": "Not specified PL"}, "none", "severe") == []


def test_non_numeric_fe_does_not_crash():
    assert organ_impairment_reasons({"fe": "", "renal": "NO"}, "severe", "none") == []
