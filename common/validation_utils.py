"""Helpers for building the validation errors and warnings reported on a final dataset response."""

from collections.abc import Iterable

from schemas.domain.locations_response import LocationItem
from schemas.ees_data_api.subject_meta_response import (
    TimePeriod as SubjectMetaTimePeriod,
)
from schemas.responses.final_dataset_response import (
    AutoSelectedFilterItem,
    DatasetValidationWarning,
    DatasetValidationWarningCode,
)


def _describe_filters(filter_labels: Iterable[str]) -> tuple[str, bool]:
    """Format filter labels for use in a warning message.

    This returns ``"filter 'Characteristic'"`` as an example for one filter,
    or ``"filters 'Characteristic', 'School type' and 'Pupil sex'"`` as an
    example for multiple filters. It also returns whether the description is plural.
    """
    quoted = [f"'{filter_label}'" for filter_label in filter_labels]
    if len(quoted) == 1:
        return f"filter {quoted[0]}", False
    return f"filters {', '.join(quoted[:-1])} and {quoted[-1]}", True


def build_filter_fallback_warnings(
    auto_selected_filter_items: dict[str, AutoSelectedFilterItem],
    unfiltered_filters: list[str],
) -> list[DatasetValidationWarning]:
    """Build the warnings for filters that got a fallback selection rather than a model selection."""
    validation_warnings: list[DatasetValidationWarning] = []

    if auto_selected_filter_items:

        filter_description, is_plural = _describe_filters(
            list(auto_selected_filter_items)
        )

        message = (
            f"No relevant filter items were found matching the query for the {filter_description}, so "
            + (
                "their auto-select fallback filter items were"
                if is_plural
                else "its auto-select fallback filter item was"
            )
            + " selected instead."
        )
        validation_warnings.append(
            DatasetValidationWarning(
                code=DatasetValidationWarningCode.AUTO_SELECTED_FILTER_ITEMS,
                message=message,
            )
        )

    if unfiltered_filters:
        filter_description, _ = _describe_filters(unfiltered_filters)
        message = (
            f"No relevant filter items were found matching the query for the {filter_description}, "
            f"and no auto-select fallback was configured, so every filter item was selected instead."
        )
        validation_warnings.append(
            DatasetValidationWarning(
                code=DatasetValidationWarningCode.UNFILTERED_FILTERS,
                message=message,
            )
        )

    return validation_warnings


def build_no_location_requirement_warning(
    location: LocationItem,
) -> DatasetValidationWarning:
    return DatasetValidationWarning(
        code=DatasetValidationWarningCode.NO_LOCATION_REQUIREMENT,
        message=(
            f"No location requirement was found in the query, so the national level "
            f"location for ({location.label}) was selected instead."
        ),
    )


def build_no_time_period_requirement_warning(
    time_period: SubjectMetaTimePeriod,
) -> DatasetValidationWarning:
    return DatasetValidationWarning(
        code=DatasetValidationWarningCode.NO_TIME_PERIOD_REQUIREMENT,
        message=(
            f"No time period requirement was found in the query, so the latest available "
            f"time period ({time_period.label}) was selected instead."
        ),
    )
