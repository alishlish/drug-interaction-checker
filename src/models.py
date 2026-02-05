from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class DrugListRequest(BaseModel):
    drugs: List[str]


class ExplainRequest(BaseModel):
    drugs: List[str]


class DrugInfo(BaseModel):
    name: str
    enzymes: Optional[str] = None
    transporters: Optional[str] = None
    found: bool
