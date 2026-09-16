"""Tests for the warning builders in `common.validation_utils`."""

import pytest

from common.validation_utils import (
    build_filter_fallback_warnings,
    build_no_location_requirement_warning,
    build_no_time_period_requirement_warning,
)
from schemas.domain.locations_response import LocationItem
from schemas.ees_data_api.subject_meta_response import TimePeriod
from schemas.responses.final_dataset_response import (
    AutoSelectedFilterItem,
    DatasetValidationWarning,
    DatasetValidationWarningCode as WarningCode,
)

FILTER_1_LABEL = "Characteristic"
FILTER_2_LABEL = "School type"


def _auto_selected_filter(*filter_labels: str) -> dict[str, AutoSelectedFilterItem]:
    return {
        filter_label: AutoSelectedFilterItem(
            filter_item_label="Total", filter_item_id=f"filter-item-{index}"
        )
        for index, filter_label in enumerate(filter_labels, start=1)
    }


def _get_validation_warning_message(
    warnings: list[DatasetValidationWarning], code: WarningCode
) -> str:
    messages = [warning.message for warning in warnings if warning.code == code]
    assert (
        len(messages) == 1
    ), f"Expected exactly one validation warning with the code '{code}', found {len(messages)}"
    return messages[0]


def test_no_fallbacks_produce_no_warnings():
    assert build_filter_fallback_warnings({}, []) == []


def test_auto_selected_and_unfiltered_fallbacks_produce_separate_warnings():
    validation_warnings = build_filter_fallback_warnings(
        _auto_selected_filter(FILTER_1_LABEL), [FILTER_2_LABEL]
    )

    assert len(validation_warnings) == 2

    auto_selected_message = _get_validation_warning_message(
        validation_warnings, WarningCode.AUTO_SELECTED_FILTER_ITEMS
    )
    assert f"'{FILTER_1_LABEL}'" in auto_selected_message
    assert f"'{FILTER_2_LABEL}'" not in auto_selected_message

    unfiltered_message = _get_validation_warning_message(
        validation_warnings, WarningCode.UNFILTERED_FILTERS
    )
    assert f"'{FILTER_2_LABEL}'" in unfiltered_message
    assert f"'{FILTER_1_LABEL}'" not in unfiltered_message


# Set up test cases for filter labels and expected warning messages.
# Regardless of how many filters a warning covers, its message should include all of them.
ONE_FILTER = (FILTER_1_LABEL,)
TWO_FILTERS = (FILTER_1_LABEL, FILTER_2_LABEL)

AUTO_SELECTED_MESSAGE_CASES = [
    pytest.param(
        ONE_FILTER,
        "No relevant filter items were found matching the query for the filter 'Characteristic', "
        "so its auto-select fallback filter item was selected instead.",
        id="one_filter",
    ),
    pytest.param(
        TWO_FILTERS,
        "No relevant filter items were found matching the query for the filters 'Characteristic' and 'School type', "
        "so their auto-select fallback filter items were selected instead.",
        id="two_filters",
    ),
]

UNFILTERED_MESSAGE_CASES = [
    pytest.param(
        ONE_FILTER,
        "No relevant filter items were found matching the query for the filter 'Characteristic', "
        "and no auto-select fallback was configured, so every filter item was selected instead.",
        id="one_filter",
    ),
    pytest.param(
        TWO_FILTERS,
        "No relevant filter items were found matching the query for the filters 'Characteristic' and 'School type', "
        "and no auto-select fallback was configured, so every filter item was selected instead.",
        id="two_filters",
    ),
]


@pytest.mark.parametrize("labels, expected_message", AUTO_SELECTED_MESSAGE_CASES)
def test_auto_selected_warning_names_every_filter_and_agrees_in_number(
    labels: tuple[str, ...], expected_message: str
):
    validation_warnings = build_filter_fallback_warnings(
        _auto_selected_filter(*labels), []
    )

    assert len(validation_warnings) == 1
    assert validation_warnings[0].code == WarningCode.AUTO_SELECTED_FILTER_ITEMS
    assert validation_warnings[0].message == expected_message


@pytest.mark.parametrize("labels, expected_message", UNFILTERED_MESSAGE_CASES)
def test_unfiltered_warning_names_every_filter_it_covers(
    labels: tuple[str, ...], expected_message: str
):
    validation_warnings = build_filter_fallback_warnings({}, list(labels))

    assert len(validation_warnings) == 1
    assert validation_warnings[0].code == WarningCode.UNFILTERED_FILTERS
    assert validation_warnings[0].message == expected_message


def test_no_location_requirement_warning_produces_expected_warning():
    location_warning = build_no_location_requirement_warning(
        LocationItem(id="location-1", label="England", value="E92000001")
    )

    assert location_warning.code == WarningCode.NO_LOCATION_REQUIREMENT
    assert location_warning.message == (
        "No location requirement was found in the query, so the national level "
        "location for England was selected instead."
    )


def test_no_time_period_requirement_warning_produces_expected_warning():
    time_period_warning = build_no_time_period_requirement_warning(
        TimePeriod(code="AY", label="2025/26", year=2025)
    )

    assert time_period_warning.code == WarningCode.NO_TIME_PERIOD_REQUIREMENT
    assert time_period_warning.message == (
        "No time period requirement was found in the query, so the latest available "
        "time period (2025/26) was selected instead."
    )
