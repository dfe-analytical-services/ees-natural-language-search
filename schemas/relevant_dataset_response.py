"""
Relevant dataset response Pydantic models
"""

from pydantic import BaseModel, ConfigDict, Field

class TimePeriodRange(BaseModel):
    model_config = ConfigDict(validate_by_name=True, populate_by_name=True, extra="forbid")

    from_: str = Field(default="", alias="from")
    to: str = Field(default="")


class RelevantDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    filters: list[str]
    indicators: list[str]
    timePeriodRange: TimePeriodRange
    rawRelevanceScore: float
    relevanceScore: float
