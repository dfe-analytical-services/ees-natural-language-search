"""
Time period selection response Pydantic models
"""

from pydantic import BaseModel, Field, RootModel


class TimePoint(BaseModel):
    code: str = ""
    year: str = ""


class DatasetTimePeriodResult(BaseModel):
    start: TimePoint = Field(default_factory=TimePoint)
    end: TimePoint = Field(default_factory=TimePoint)


class TimePeriodSelectionResponse(RootModel[dict[str, DatasetTimePeriodResult]]):
    """Time period selection results, keyed by dataset file ID."""
