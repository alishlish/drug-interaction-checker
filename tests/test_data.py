"""Data loading / normalization against the real committed CSV."""
from src.services.data import normalize_drug_name, get_drug, search_drugs


def test_normalize():
    assert normalize_drug_name("  Warfarin ") == "warfarin"
    assert normalize_drug_name(None) == ""


def test_get_drug_found(datastore):
    info = get_drug(datastore, "Azilsartan")
    assert info["found"] is True
    assert info["enzymes"]


def test_get_drug_missing(datastore):
    assert get_drug(datastore, "asdfghjkl")["found"] is False


def test_search(datastore):
    assert "azilsartan" in search_drugs(datastore, "azil")
    assert search_drugs(datastore, "") == []
