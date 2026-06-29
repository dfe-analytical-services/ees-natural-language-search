"""
Reranker response Pydantic models
"""

from pydantic import BaseModel, Field
from typing import Optional


class QueryRequirements(BaseModel):
    filters: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    timePeriod: Optional[str] = None


class ShortlistedDataset(BaseModel):
    fileId: str
    title: str = ""
    relevanceReason: str = ""
    relevantFilters: list[str] = Field(default_factory=list)


class RerankerResponse(BaseModel):
    queryRequirements: QueryRequirements = Field(default_factory=QueryRequirements)
    shortlistedDatasets: list[ShortlistedDataset] = Field(default_factory=list)
    confidence: Optional[str] = None
