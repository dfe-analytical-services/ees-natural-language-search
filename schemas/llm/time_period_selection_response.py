"""
LLM Time period selection response Pydantic models
"""

from pydantic import BaseModel, Field


class TimePeriod(BaseModel):
    code: str
    year: int


class TimePeriodRange(BaseModel):
    start: TimePeriod
    end: TimePeriod


class TimePeriodDatasetResult(BaseModel):
    """Time period selection result for a single dataset.

    The range result is wrapped in an object because the model returns `null` when no available
    time period overlaps the requirement, and JSON mode requires a top level JSON object.
    """

    time_period: TimePeriodRange | None = Field(
        alias="timePeriod",
        default=None,
    )
