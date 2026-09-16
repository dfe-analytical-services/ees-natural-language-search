"""
Final dataset response Pydantic models
"""

from enum import StrEnum

from pydantic import Field, computed_field
from schemas.shared.base_models import StrictCamelModel

from schemas.domain.locations_response import DatasetLocations


class TimePeriod(StrictCamelModel):
    """A time period, e.g. Academic year 2025/26 (code: AY, year: 2025).
    Duplicated from schemas.llm.time_period_selection_response.TimePeriod so the response shape can diverge from the LLM response shape in future."""

    code: str
    year: int


class TimePeriodRange(StrictCamelModel):
    """The selected time period range for a dataset.
    Duplicated from schemas.llm.time_period_selection_response.TimePeriodRange so the response shape can diverge from the LLM response shape in future."""

    start: TimePeriod
    end: TimePeriod


class FilterSelectionItem(StrictCamelModel):
    """A single filter item selected for a dataset."""

    id: str
    label: str


class IndicatorSelectionItem(StrictCamelModel):
    """A single indicator selected for a dataset."""

    id: str
    label: str


class AutoSelectedFilterItem(StrictCamelModel):
    """A filter item that was selected via a filter's auto_select_filter_item_id fallback,
    because the model did not select anything relevant for that filter."""

    filter_item_label: str
    filter_item_id: str


class DatasetValidationErrorCode(StrEnum):
    """The set of reasons a dataset result is unusable for table generation."""

    INVALID_FILTER_ITEM = "invalid_filter_item"
    INVALID_INDICATOR = "invalid_indicator"
    INVALID_TIME_PERIOD = "invalid_time_period"
    MALFORMED_FILTER_ITEM_REFERENCE = "malformed_filter_item_reference"
    NO_AVAILABLE_TIME_PERIODS = "no_available_time_periods"
    NO_INDICATORS = "no_indicators"
    NO_LOCATION = "no_location"
    NO_TIME_PERIOD = "no_time_period"


class DatasetValidationWarningCode(StrEnum):
    """The set of reasons a dataset result needs user attention."""

    AUTO_SELECTED_FILTER_ITEMS = "auto_selected_filter_items"
    NO_TIME_PERIOD_REQUIREMENT = "no_time_period_requirement"
    UNFILTERED_FILTERS = "unfiltered_filters"


class DatasetValidationError(StrictCamelModel):
    """A reason why a dataset result cannot be used to generate a table."""

    code: DatasetValidationErrorCode
    message: str


class DatasetValidationWarning(StrictCamelModel):
    """A reason why a dataset result needs user attention, e.g. because it is broader than
    the query requirement.

    A warning on its own does not mean that the dataset result is invalid.
    Warnings can appear alongside errors, and only the errors decide `is_valid_for_table_generation`."""

    code: DatasetValidationWarningCode
    message: str


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
    time_period: TimePeriodRange | None = None
    geographic_levels: DatasetLocations | None = None
    relevance_reason: str | None = None
    auto_selected_filter_items: dict[str, AutoSelectedFilterItem] = Field(
        default_factory=dict,
        description="Keyed by filter label. The value is a filter item that has been auto-selected based on the filter's auto_select_filter_item_id, because there are no relevant selections made for the filter."
    )
    unfiltered_filters: list[str] = Field(
        default_factory=list,
        description="Labels of filters where every filter item is selected because there are no relevant selections made for the filter, and no auto_select_filter_item_id fallback exists either.",
    )
    validation_errors: list[DatasetValidationError] = Field(default_factory=list)
    validation_warnings: list[DatasetValidationWarning] = Field(default_factory=list)

    @computed_field
    @property
    def is_valid_for_table_generation(self) -> bool:
        return not self.validation_errors
