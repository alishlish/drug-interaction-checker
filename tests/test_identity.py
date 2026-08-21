"""Identity resolution: exact dataset, RxNorm brand/synonym (via ingredient),
and approximate-as-suggestion. RxNorm is monkeypatched — no network."""
from src.services import rxnorm, identity
from src.services.rxnorm import RxNormMatch


def test_exact_dataset(datastore):
    r = identity.resolve_to_dataset(datastore, "Azilsartan")
    assert r.found and r.drug_name == "azilsartan" and r.via == "exact"


def test_unknown_without_rxnorm(datastore):
    r = identity.resolve_to_dataset(datastore, "asdfghjkl", use_rxnorm=False)
    assert not r.found and r.via == "none"


def test_brand_resolves_via_ingredient(datastore, monkeypatch):
    # Diflucan (brand RxCUI) -> ingredient fluconazole (4450), which is mapped.
    monkeypatch.setattr(rxnorm, "resolve",
                        lambda name: RxNormMatch(name, "exact", "202813", "Diflucan", 100.0))
    monkeypatch.setattr(rxnorm, "ingredient_rxcuis", lambda rxcui: ["4450"])
    r = identity.resolve_to_dataset(datastore, "Diflucan")
    assert r.found and r.drug_name == "fluconazole" and r.via == "rxnorm"


def test_approximate_is_suggestion_only(datastore, monkeypatch):
    # an approximate hit must NOT auto-resolve — only suggest.
    monkeypatch.setattr(rxnorm, "resolve",
                        lambda name: RxNormMatch(name, "approximate", "4450", "fluconazole", 8.0))
    r = identity.resolve_to_dataset(datastore, "flucnazole")
    assert not r.found and r.suggestion == "fluconazole"
