FIELD_LABELS = {
    "cas_number": ("CAS", "Chemical identifier (CAS registry number)."),
    "fe": ("Fraction excreted unchanged (fe)", "Proportion eliminated unchanged (often urine)."),
    "f": ("Oral bioavailability (F)", "Fraction of oral dose reaching systemic circulation."),
    "renal": ("Renal impairment data available", "Whether renal impairment data are present in this dataset entry."),
    "non_renal": ("Non-renal impairment data available", "Whether non-renal (e.g., hepatic) impairment data are present."),
    "route_of_admin": ("Route (index drug)", "Administration route for the index drug in the dataset entry."),
    "delta_auc_pct": ("Reported change in exposure (ΔAUC)", "Percent change in overall exposure (AUC) under the dataset interaction entry."),
    "inhibitor": ("Interacting drug (study agent)", "Drug listed as the interacting agent in the dataset entry."),
    "ref_ddi": ("Reference (PMID)", "PubMed identifier for the referenced interaction study (when available)."),
    "route_of_admin_ref": ("Route (reference)", "Administration route for the reference drug."),
    "delta_auc_ref_pct": ("ΔAUC (reference)", "Reference ΔAUC value from the dataset entry (if provided)."),
    "extra": ("Other (unmapped)", "Field present in dataset but not yet mapped to a defined label."),
}

ROUTE_MAP = {
    "po": "PO (oral)",
    "iv": "IV (intravenous)",
    "im": "IM (intramuscular)",
    "sc": "SC (subcutaneous)",
    "sq": "SC (subcutaneous)",
}
