"""
Final dataset response Pydantic models
"""

from pydantic import Field
from schemas.shared.base_models import StrictCamelModel

from schemas.domain.locations_response import DatasetLocations


class TimePeriod(StrictCamelModel):
    """A time period, e.g. Academic year 2025/26 (code: AY, year: 2025).
    Duplicated from schemas.llm.time_period_selection_response.TimePeriod so the response shape can diverge from the LLM response shape in future."""

    code: str = ""
    year: int = 0


class DatasetTimePeriodRangeResult(StrictCamelModel):
    """The selected time period range for a dataset.
    Duplicated from schemas.llm.time_period_selection_response.DatasetTimePeriodRangeResult so the response shape can diverge from the LLM response shape in future."""

    start: TimePeriod = Field(default_factory=TimePeriod)
    end: TimePeriod = Field(default_factory=TimePeriod)


class FilterSelectionItem(StrictCamelModel):
    """A single filter item selected for a dataset."""

    id: str
    label: str


class IndicatorSelectionItem(StrictCamelModel):
    """A single indicator selected for a dataset."""

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
    filters: list[FilterSelectionItem] = Field(default_factory=list)
    indicators: list[IndicatorSelectionItem] = Field(default_factory=list)
    time_period: DatasetTimePeriodRangeResult | None = None
    geographic_levels: DatasetLocations | None = None
    relevance_reason: str | None = None
