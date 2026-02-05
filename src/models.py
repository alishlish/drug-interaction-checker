from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class DrugListRequest(BaseModel):
    drugs: List[str] = Field(..., description="List of drug names")


class ExplainRequest(BaseModel):
    drugs: List[str] = Field(..., description="List of drug names")


class DrugInfo(BaseModel):
    name: str
    found: bool
    enzymes: Optional[str] = None
    transporters: Optional[str] = None
    # dynamic map of organ impairment / precautions / other columns from CSV
    attributes: Dict[str, Any] = Field(default_factory=dict)


class InteractionResult(BaseModel):
    drug_pair: List[str]
    interaction: str
    severity: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    llm_explanation: Optional[str] = None


class InteractionsResponse(BaseModel):
    interactions: List[InteractionResult]
