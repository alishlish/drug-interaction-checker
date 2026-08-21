import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.data import load_datastore

CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "processed", "drug_interactions_clean.csv",
)


@pytest.fixture(scope="session")
def datastore():
    return load_datastore(CSV)
