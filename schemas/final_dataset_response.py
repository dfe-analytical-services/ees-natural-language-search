"""
Final dataset response Pydantic models
"""

from pydantic import Field
from schemas.base_models import StrictCamelModel

from schemas.locations_response import DatasetLocations
from schemas.time_period_selection_response import DatasetTimePeriodResult


class SelectionItem(StrictCamelModel):

    id: str
    label: str


class FinalDatasetResponse(StrictCamelModel):

    data_set_file_id: str
    file_id: str
    publication_id: str
    publication_slug: str
    publication_title: str
    release_slug: str
    release_version_id: str
    subject_id: str
    title: str
    description: str
    filters: list[SelectionItem] = Field(default_factory=list)
    indicators: list[SelectionItem] = Field(default_factory=list)
    time_period: DatasetTimePeriodResult | None = None
    geographic_levels: DatasetLocations | None = None
    relevance_reason: str | None = None
