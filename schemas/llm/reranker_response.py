"""
LLM Reranker response Pydantic models
"""

from pydantic import Field
from typing import Optional

from schemas.shared.base_models import StrictModel


class QueryRequirements(StrictModel):
    filters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    timePeriod: Optional[str] = None


class ShortlistedDataset(StrictModel):
    fileId: str
    title: str = ""
    relevanceReason: str = ""
    relevantFilters: list[str] = Field(default_factory=list)


class RerankerResponse(StrictModel):
    queryRequirements: QueryRequirements = Field(default_factory=QueryRequirements)
    shortlistedDatasets: list[ShortlistedDataset] = Field(default_factory=list)
    confidence: Optional[str] = None
