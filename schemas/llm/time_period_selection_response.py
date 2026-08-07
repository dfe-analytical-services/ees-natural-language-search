"""
LLM Time period selection response Pydantic models
"""

from pydantic import BaseModel, Field, RootModel


class TimePeriod(BaseModel):
    code: str = ""
    year: int = 0


class DatasetTimePeriodRangeResult(BaseModel):
    start: TimePeriod = Field(default_factory=TimePeriod)
    end: TimePeriod = Field(default_factory=TimePeriod)


class TimePeriodSelectionResponse(RootModel[dict[str, DatasetTimePeriodRangeResult]]):
    """Time period selection results, keyed by dataset file ID."""
