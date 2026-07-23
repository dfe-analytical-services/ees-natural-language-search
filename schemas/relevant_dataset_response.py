"""
Relevant dataset response Pydantic models
"""

from pydantic import Field
from schemas.base_models import StrictCamelModel


class TimePeriodRange(StrictCamelModel):

    from_: str = Field(default="", alias="from")
    to: str = Field(default="")


class RelevantDatasetResponse(StrictCamelModel):

    data_set_file_id: str
    file_id: str
    publication_id: str
    publication_slug: str
    publication_title: str
    release_slug: str
    release_version_id: str
    subject_id: str
    title: str
    description: str
    filters: list[str]
    indicators: list[str]
    time_period_range: TimePeriodRange
    raw_relevance_score: float
    relevance_score: float
