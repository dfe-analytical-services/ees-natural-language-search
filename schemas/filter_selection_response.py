"""
Filter selection response Pydantic models
"""

from pydantic import BaseModel, Field, RootModel


class FilterValueDecision(BaseModel):
    relevant: bool = False
    reasoning: str = ""


class FilterDatasetResult(BaseModel):
    filterValues: dict[str, FilterValueDecision] = Field(default_factory=dict)


class FilterSelectionResponse(RootModel[dict[str, FilterDatasetResult]]):
    """keyed by fileId"""
