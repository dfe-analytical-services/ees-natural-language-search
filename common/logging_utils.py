"""
Helpers for logging dataset selection results.
"""

import logging
from collections import defaultdict

from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.domain.locations_response import DatasetLocations
from schemas.llm.filter_selection_response import FilterItemDatasetResult
from schemas.llm.indicator_selection_response import IndicatorDecision
from schemas.llm.time_period_selection_response import TimePeriodRange

logger = logging.getLogger(__name__)


def _summarise_relevant_filters_for_logging(
    filter_results: FilterItemDatasetResult | None,
) -> dict[str, dict[str, str | None]]:
    """Groups relevant filter items by filter label, and keeps their reasoning."""
    relevant_by_label: dict[str, dict[str, str | None]] = defaultdict(dict)
    for composite_descriptor, decision in (filter_results.filter_items if filter_results else {}).items():
        if not decision.relevant:
            continue
        filter_label, _filter_item_group_id, filter_item_label = composite_descriptor.split("|||")
        relevant_by_label[filter_label][filter_item_label] = decision.reasoning

    return dict(relevant_by_label)


def _summarise_relevant_indicators_for_logging(
    indicator_results: dict[str, IndicatorDecision] | None,
) -> dict[str, str]:
    """Reduces indicators to those that are relevant, and keeps their reasoning."""
    return {
        label: decision.reasoning
        for label, decision in (indicator_results or {}).items()
        if decision.relevant
    }


def _summarise_locations_for_logging(
    location_results: DatasetLocations | None,
) -> dict[str, list[str]]:
    """Drops empty geographic levels and reduces each location to a label."""
    return {
        level: [location.label for location in locations]
        for level, locations in (location_results.root.items() if location_results else [])
        if locations
    }


def log_dataset_selection_summary(
    dataset: DatasetWithSubjectMeta,
    filter_results: FilterItemDatasetResult | None,
    indicator_results: dict[str, IndicatorDecision] | None,
    time_period_result: TimePeriodRange | None,
    location_results: DatasetLocations | None,
) -> None:
    """Logs a summary of the filter, indicator, time period, and location selections made for a dataset."""
    logger.info(
        "Combined response summary: dataset=%s, relevant_filters=%s, irrelevant_filters=%s, relevant_indicators=%s, time_period=%s, locations=%s",
        {
            "title": dataset.title,
            "dataset_file_id": dataset.dataset_file_id,
            "file_id": dataset.file_id,
        },
        _summarise_relevant_filters_for_logging(filter_results),
        filter_results.irrelevant_filters if filter_results else {},
        _summarise_relevant_indicators_for_logging(indicator_results),
        time_period_result,
        _summarise_locations_for_logging(location_results),
    )
