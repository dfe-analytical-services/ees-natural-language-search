"""
Location response Pydantic models
"""

from pydantic import RootModel
from schemas.shared.base_models import StrictCamelModel


class LocationItem(StrictCamelModel):
    """A single location match for a dataset."""

    id: str
    label: str
    value: str


class DatasetLocations(RootModel[dict[str, list[LocationItem]]]):
    """Location matches for a single dataset, keyed by geographic level (e.g. "National", "Regional", "Local authority")."""


class LocationsResponse(RootModel[dict[str, DatasetLocations]]):
    """Location matches for all reranked datasets, keyed by dataset file ID."""
