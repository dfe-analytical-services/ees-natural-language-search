"""
Final dataset response Pydantic models
"""

from pydantic import BaseModel, Field

from schemas.time_period_selection_response import DatasetTimePeriodResult


class SelectionItem(BaseModel):
    id: str
    label: str


class GeographicLevelItem(BaseModel):
    id: str
    label: str
    value: str


class FinalDatasetResponse(BaseModel):
    dataSetFileId: str
    fileId: str
    publicationId: str
    publicationSlug: str
    publicationTitle: str
    releaseSlug: str
    releaseVersionId: str
    subjectId: str
    title: str
    description: str
    filters: list[SelectionItem] = Field(default_factory=list)
    indicators: list[SelectionItem] = Field(default_factory=list)
    timePeriod: DatasetTimePeriodResult | None = None
    geographicLevels: dict[str, list[GeographicLevelItem]] | None = None
    relevanceReason: str | None = None