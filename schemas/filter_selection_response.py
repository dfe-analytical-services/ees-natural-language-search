"""
Filter selection response Pydantic models
"""

from pydantic import BaseModel, Field, RootModel


class FilterValueDecision(BaseModel):
    relevant: bool = False
    reasoning: str = ""


class FilterDatasetResult(BaseModel):
    """Filter decisions for a single dataset."""

    filterValues: dict[str, FilterValueDecision] = Field(
        default_factory=dict,
        description="Keyed by filter item label",
    )


class FilterSelectionResponse(RootModel[dict[str, FilterDatasetResult]]):
    """Filter selection results, keyed by dataset fileId."""
