"""
LLM Filter item selection response Pydantic models
"""

from pydantic import BaseModel, Field


class FilterItemDecision(BaseModel):
    relevant: bool = False
    reasoning: str | None = None
    filter_item_label: str | None = Field(
        alias="filterItemLabel",
        default=None,
        description="Echoed back by the model only so that a mis-referenced filter item can be detected.",
    )


class FilterItemDatasetResult(BaseModel):
    """Filter item decisions for a single dataset."""

    filter_items: dict[str, FilterItemDecision] = Field(
        alias="filterItems",
        default_factory=dict,
        description="Keyed by the reference number of a filter item provided to the model.",
    )
    irrelevant_filters: dict[str, str] = Field(
        alias="irrelevantFilters",
        default_factory=dict,
        description="Keyed by exact filter label. The value is an explanation of why none of the filter's filter items are relevant",
    )
