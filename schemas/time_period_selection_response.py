"""
Time period selection response Pydantic models
"""

from typing import TypeVar
from pydantic import BaseModel, Field, RootModel

T = TypeVar("T")


class TimePoint(BaseModel):
    code: str = ""
    year: str = ""


class TimePeriod(BaseModel):
    start: TimePoint = Field(default_factory=TimePoint)
    end: TimePoint = Field(default_factory=TimePoint)


class FileTimePeriodResult(BaseModel):
    timePeriod: TimePeriod = Field(default_factory=TimePeriod)


class TimePeriodSelectionResponse(RootModel[dict[str, FileTimePeriodResult]]):
    """keyed by fileId"""