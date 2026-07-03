"""
Filter item selection response Pydantic models
"""

from pydantic import BaseModel, Field, RootModel


class FilterItemDecision(BaseModel):
    relevant: bool = False
    reasoning: str = ""


class FilterItemDatasetResult(BaseModel):
    """Filter item decisions for a single dataset."""

    filter_items: dict[str, FilterItemDecision] = Field(
        alias="filterItems",
        default_factory=dict,
        description="Keyed by composite filter item descriptor: filter label, filter item group ID, and filter item label",
    )


class FilterSelectionResponse(RootModel[dict[str, FilterItemDatasetResult]]):
    """Filter item selection results, keyed by dataset file ID."""
