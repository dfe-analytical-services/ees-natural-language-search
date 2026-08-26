from collections import defaultdict
from typing import TypeVar
from pydantic import RootModel
from common.llm_response_parser import parse_llm_response
from common.search_client import filter_client
from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.responses.final_dataset_response import (
    DatasetTimePeriodRangeResult,
    FilterSelectionItem,
    FinalDatasetResponse,
    IndicatorSelectionItem,
)
from schemas.llm.filter_selection_response import FilterItemDatasetResult, FilterSelectionResponse
from schemas.llm.indicator_selection_response import IndicatorDecision, IndicatorSelectionResponse
from schemas.domain.locations_response import DatasetLocations
from schemas.llm.time_period_selection_response import TimePeriodSelectionResponse

T = TypeVar("T")


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


def _merge_selection_responses(
    responses: list[str],
    response_model: type[RootModel[dict[str, T]]],
    context: str,
) -> dict[str, T]:
    merged: dict[str, T] = {}
    for raw in responses:
        parsed = parse_llm_response(raw, response_model, context=context)
        if parsed:
            merged.update(parsed.root)
    return merged


def parse_selection_responses(
    filter_responses: list[str],
    indicator_responses: list[str],
    time_period_responses: list[str],
) -> tuple[dict[str, FilterItemDatasetResult], dict[str, dict[str, IndicatorDecision]], dict[str, DatasetTimePeriodRangeResult | None]]:
    filter_results_by_id = _merge_selection_responses(filter_responses, FilterSelectionResponse, context="filter selection")
    indicator_results_by_id = _merge_selection_responses(indicator_responses, IndicatorSelectionResponse, context="indicator selection")
    time_period_results_by_id = _merge_selection_responses(time_period_responses, TimePeriodSelectionResponse, context="time period selection")
    return filter_results_by_id, indicator_results_by_id, time_period_results_by_id


def build_final_dataset_response(
    dataset: DatasetWithSubjectMeta,
    filter_results: FilterItemDatasetResult | None,
    indicator_results: dict[str, IndicatorDecision] | None,
    time_period_result: DatasetTimePeriodRangeResult | None,
    location_results: DatasetLocations | None,
    relevance_reason: str | None,
) -> FinalDatasetResponse:
    filters = [
        FilterSelectionItem(
            id=dataset.subject_meta.get_filter_item(
                filter_item_group_id=filter_item_group_id,
                filter_item_label=filter_item_label,
            ).id,
            label=filter_item_label,
        )
        for filter_item_descriptor, decision in (filter_results.filter_items if filter_results else {}).items()
        if decision.relevant is True
        for _, filter_item_group_id, filter_item_label in [filter_item_descriptor.split("|||")]
    ]

    indicators = [
        IndicatorSelectionItem(
            id=dataset.subject_meta.get_indicator(indicator_label).id,
            label=indicator_label,
        )
        for indicator_label, decision in (indicator_results or {}).items()
        if decision.relevant is True
    ]

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
        # Convert from the LLM response shape to the event response shape
        # The two are currently the same but we're allowing them to diverge in future if needed
        time_period=(
            DatasetTimePeriodRangeResult.model_validate(time_period_result.model_dump())
            if time_period_result is not None
            else None
        ),
        geographic_levels=location_results,
        relevance_reason=relevance_reason,
    )


def rrf_to_percentage(rrf_score: float):
    RRF_K = 60
    RRF_MAX = (1.0 / (1 + RRF_K)) + (1.0 / (1 + RRF_K)) #Both components are equal since vector score and BM25 score have same weightage currently

    raw = (rrf_score/RRF_MAX) * 100
    return round(min(raw, 100.0), 1)
