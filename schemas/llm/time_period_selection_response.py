"""
LLM Time period selection response Pydantic models
"""

from pydantic import BaseModel, RootModel


class TimePeriod(BaseModel):
    code: str
    year: int


class DatasetTimePeriodRangeResult(BaseModel):
    start: TimePeriod
    end: TimePeriod


class TimePeriodSelectionResponse(
    RootModel[dict[str, DatasetTimePeriodRangeResult | None]]
):
    """Time period selection results, keyed by dataset file ID."""
