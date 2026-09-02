from collections import defaultdict
from typing import TypeVar
from pydantic import BaseModel
from common.llm_response_parser import parse_llm_response
from common.search_client import filter_client
from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.responses.final_dataset_response import (
    AutoSelectedFilterItem,
    FilterSelectionItem,
    FinalDatasetResponse,
    IndicatorSelectionItem,
    TimePeriod,
    TimePeriodRange,
)
from schemas.llm.filter_selection_response import FilterItemDatasetResult
from schemas.llm.indicator_selection_response import IndicatorDatasetResult, IndicatorDecision
from schemas.domain.locations_response import DatasetLocations
from schemas.llm.time_period_selection_response import (
    TimePeriodDatasetResult,
    TimePeriodRange as LlmTimePeriodRange,
)
from schemas.ees_data_api.subject_meta_response import FilterItem

T = TypeVar("T", bound=BaseModel)


def retrieve_and_transform_filter_data(file_ids: list[str], shortlisted_filters: defaultdict=None):
    ## Retrieve full dataset level information from Azure AI Search
    filter_expr = "search.in(fileId, '{}', ',')".format(",".join(file_ids))
    results = filter_client.search(
        search_text="*",
        filter=filter_expr,
        # TODO rename fields in the search index to use consistent terminology:
        # filterCategory is the field named used in the index for the filter label
        # filterName is the filter item group label. When the group label is 'Default', filterName contains the filter label instead.
        # filterValues is a list of the filter item labels
        select=['fileId', 'filterGroupId', 'filterCategory','filterName', 'filterValues']
    )

    # Each document in the search results represents a filter item group.
    # Transform the filter item group results into a list of dicts with each dict containing the file Id, filter item group Id, filter label, and a list of filter item labels.
    # Multiple results can be returned for the same file ID when the file contains multiple filter item groups or filters. Each filter contains at least one filter item group.
    results = [{'fileId': r['fileId'], 'filterItemGroupId':r['filterGroupId'], 'filterLabel':r['filterCategory'], 'filterItemGroupLabelOrFilterLabel':r['filterName'], 'filterItemLabels':r['filterValues']} for r in results]
    
    if shortlisted_filters:
        results = [
            d
            for d in results
            if d.get("fileId") in shortlisted_filters and d.get("filterItemGroupLabelOrFilterLabel") in shortlisted_filters.get(d.get("fileId"), [])
        ]
    # Flatten the list of filter labels and filter item labels for easier LLM consumption
    results_by_file_id = defaultdict(list)
    for result in results:
        results_by_file_id[result["fileId"]].append(result)

    results_by_file_id = dict(results_by_file_id)

    transformed = {
        file_id: {
            "filterItems": [
                f"{result['filterLabel']}|||{result.get('filterItemGroupId')}|||{filter_item_label}"
                for result in results
                for filter_item_label in result["filterItemLabels"]
            ]
        }
        for file_id, results in results_by_file_id.items()
    }

    return transformed


def _parse_responses_by_file_id(
    responses: list[tuple[str, str]],
    response_model: type[T],
    context: str,
) -> dict[str, T]:
    results: dict[str, T] = {}
    for file_id, raw in responses:
        parsed = parse_llm_response(raw, response_model, context=context)
        if parsed is not None:
            results[file_id] = parsed
    return results


def parse_selection_responses(
    filter_responses: list[tuple[str, str]],
    indicator_responses: list[tuple[str, str]],
    time_period_responses: list[tuple[str, str]],
) -> tuple[dict[str, FilterItemDatasetResult], dict[str, dict[str, IndicatorDecision]], dict[str, LlmTimePeriodRange | None]]:
    filter_results_by_id = _parse_responses_by_file_id(filter_responses, FilterItemDatasetResult, context="filter selection")
    indicator_results_by_id = {
        file_id: result.root
        for file_id, result in _parse_responses_by_file_id(indicator_responses, IndicatorDatasetResult, context="indicator selection").items()
    }
    time_period_results_by_id = {
        file_id: result.time_period
        for file_id, result in _parse_responses_by_file_id(time_period_responses, TimePeriodDatasetResult, context="time period selection").items()
    }
    return filter_results_by_id, indicator_results_by_id, time_period_results_by_id


def build_final_dataset_response(
    dataset: DatasetWithSubjectMeta,
    filter_results: FilterItemDatasetResult | None,
    indicator_results: dict[str, IndicatorDecision] | None,
    time_period_result: LlmTimePeriodRange | None,
    time_period_requirement: str | None,
    location_results: DatasetLocations | None,
    relevance_reason: str | None,
) -> FinalDatasetResponse:
    subject_meta = dataset.subject_meta

    model_selected_filter_items: list[tuple[str, FilterItem]] = [
        (
            filter_item_group_id,
            subject_meta.get_filter_item(
                filter_item_group_id=filter_item_group_id,
                filter_item_label=filter_item_label,
            ),
        )
        for filter_item_descriptor, decision in (filter_results.filter_items if filter_results else {}).items()
        if decision.relevant is True
        for _filter_label, filter_item_group_id, filter_item_label in [filter_item_descriptor.split("|||")]
    ]

    # Every filter needs at least one selected filter item for the table query to work correctly.
    # If the model didn't select any relevant filter items for a filter, fallback to its auto_select_filter_item_id if set.
    # In the case of no auto_select_filter_item_id, select every filter item instead.
    # Selecting all filter items has the same effect as not applying the filter (since nothing is excluded).
    # Maintain a record of these auto-selected filter items, and unfiltered filters separately,
    # so they can be returned in the final dataset response. This allows the consumer to differentiate
    # between model selections and fallback selections.
    selected_filter_item_group_ids = {filter_item_group_id for filter_item_group_id, _ in model_selected_filter_items}
    selected_filter_items: list[FilterItem] = [filter_item for _, filter_item in model_selected_filter_items]
    auto_selected_filters_items: dict[str, AutoSelectedFilterItem] = {}
    unfiltered_filters: list[str] = []

    # Iterate over all filters in the subject meta
    for filter_ in subject_meta.filters.values():
        filter_item_group_ids = {filter_item_group.id for filter_item_group in filter_.filter_item_groups.values()}

        # Intersect the set of all filter item group IDs for the filter with the set of selected filter item group IDs,
        # to check if the filter has any filter item groups containing a filter item with a relevant decision made by the model
        if filter_item_group_ids & selected_filter_item_group_ids:
            continue  # filter has a filter item group containing a filter item with a relevant decision

        if filter_.auto_select_filter_item_id:
            auto_select_filter_item = subject_meta.get_filter_item_by_id(filter_.auto_select_filter_item_id)
            selected_filter_items.append(auto_select_filter_item)
            auto_selected_filters_items[filter_.label] = AutoSelectedFilterItem(
                filter_item_label=auto_select_filter_item.label, filter_item_id=auto_select_filter_item.id,
            )
        else:
            for filter_item_group in filter_.filter_item_groups.values():
                for filter_item in filter_item_group.filter_items:
                    selected_filter_items.append(filter_item)
            unfiltered_filters.append(filter_.label)

    filters = [FilterSelectionItem(id=filter_item.id, label=filter_item.label) for filter_item in selected_filter_items]

    indicators = [
        IndicatorSelectionItem(
            id=subject_meta.get_indicator(indicator_label).id,
            label=indicator_label,
        )
        for indicator_label, decision in (indicator_results or {}).items()
        if decision.relevant is True
    ]

    if time_period_result is not None:
        # Convert from the LLM response shape to the event response shape
        # The two are currently the same but we're allowing them to diverge in future if needed
        time_period = TimePeriodRange.model_validate(time_period_result.model_dump())
    elif time_period_requirement is None:
        # No time period requirement was extracted from the query, so the time period selection agent
        # was skipped. Fallback to the dataset's latest available time period.
        latest_time_period = subject_meta.get_latest_time_period()
        time_period = (
            TimePeriodRange(
                start=TimePeriod(code=latest_time_period.code, year=latest_time_period.year),
                end=TimePeriod(code=latest_time_period.code, year=latest_time_period.year),
            )
            if latest_time_period
            else None
        )
    else:
        # A time period requirement was present, but the model couldn't find a time period matching the
        # requirement for this dataset. Return None to distinguish this from the no requirement case.
        # Falling back to the dataset's latest available time period would be misleading.
        time_period = None

    return FinalDatasetResponse(
        data_set_file_id=dataset.dataset_file_id,
        file_id=dataset.file_id,
        publication_id=dataset.publication_id,
        publication_slug=dataset.publication_slug,
        publication_title=dataset.publication_title,
        release_slug=dataset.release_slug,
        release_version_id=dataset.release_version_id,
        subject_id=dataset.subject_id,
        title=dataset.title,
        description=dataset.description,
        filters=filters,
        indicators=indicators,
        time_period=time_period,
        geographic_levels=location_results,
        relevance_reason=relevance_reason,
        auto_selected_filter_items=auto_selected_filters_items,
        unfiltered_filters=unfiltered_filters,
    )


def rrf_to_percentage(rrf_score: float):
    RRF_K = 60
    RRF_MAX = (1.0 / (1 + RRF_K)) + (1.0 / (1 + RRF_K)) #Both components are equal since vector score and BM25 score have same weightage currently

    raw = (rrf_score/RRF_MAX) * 100
    return round(min(raw, 100.0), 1)
