import logging
from collections import defaultdict
from collections.abc import Mapping
from typing import TypeVar
from pydantic import BaseModel
from common.llm_response_parser import parse_llm_response
from common.search_client import filter_client
from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.domain.filter_item_candidates import (
    DatasetFilterItemCandidates,
    FilterItemCandidate,
)
from schemas.responses.final_dataset_response import (
    AutoSelectedFilterItem,
    DatasetValidationIssue,
    DatasetValidationIssueCode,
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
from schemas.ees_data_api.subject_meta_response import FilterItem, SubjectMetaResponse

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


def build_filter_item_candidates(
    datasets_by_file_id: dict[str, DatasetWithSubjectMeta],
    shortlisted_relevant_filters_by_file_id: Mapping[str, list[str]] | None = None,
) -> dict[str, DatasetFilterItemCandidates]:
    """Builds the numbered filter items offered to the filter selection agent, per dataset.

    The Azure AI Search filter index is used to find relevant filter item groups and the datasets
    they belong to which are worth shortlisting by the reranker.

    The candidate filter items for the filter selection agent are obtained from the subject meta,
    which is the source of truth for their IDs.

    Datasets left without any candidates are omitted, so no agent call is made for them.
    """
    filter_item_group_ids_by_file_id = _retrieve_shortlisted_relevant_filter_item_group_ids(
        file_ids=list(datasets_by_file_id.keys()),
        shortlisted_relevant_filters_by_file_id=shortlisted_relevant_filters_by_file_id,
    )

    candidates_by_file_id: dict[str, DatasetFilterItemCandidates] = {}
    for file_id, filter_item_group_ids in filter_item_group_ids_by_file_id.items():
        dataset = datasets_by_file_id.get(file_id)
        if dataset is None:
            continue

        candidates = _build_filter_item_candidates(
            file_id=file_id,
            subject_meta=dataset.subject_meta,
            filter_item_group_ids=filter_item_group_ids,
        )

        # Omit datasets that have no filter item candidates
        if not candidates.root:
            continue

        logger.info(
            "Built filter item candidates for dataset: file_id=%s, candidate_count=%s",
            file_id,
            len(candidates.root),
        )
        candidates_by_file_id[file_id] = candidates

    return candidates_by_file_id


def _retrieve_shortlisted_relevant_filter_item_group_ids(
    file_ids: list[str],
    shortlisted_relevant_filters_by_file_id: Mapping[str, list[str]] | None,
) -> dict[str, list[str]]:
    """Reverse engineers the ID's of relevant filter item groups that were retrieved from Azure AI Search based on their names.
    """

    # TODO this additional call to the search index doesn't seem ideal.
    # This seems to be necessary because when the filter names are added to the search index,
    # they can be a filter item group label, or a filter label depending on whether the group label is 'Default'.
    # Those names are passed in `shortlisted_relevant_filters_by_file_id` to this function, and there's no easy way to distinguish between the two cases.
    # We need to go back to the search index where the values came from, and get the 'filterGroupId' corresponding with 'filterName' for each name value.
    # The filter group id's could have been retrieved earlier by changing the way `multi_index_search` builds `relevant_filters_by_file_id`.

    # TODO there might be a bug if multiple filter item groups with the same name exist in a dataset (possible if there are multiple filters each with their own groups)

    filter_expr = "search.in(fileId, '{}', ',')".format(",".join(file_ids))
    results = filter_client.search(
        search_text="*",
        filter=filter_expr,
        # TODO rename fields in the search index to use consistent terminology:
        # filterName is the filter item group label. When the group label is 'Default', filterName contains the filter label instead.
        # Unused fields:
        # filterCategory is the field named used in the index for the filter label
        # filterValues is a list of the filter item labels
        select=['fileId', 'filterGroupId', 'filterName']
    )

    filter_item_group_ids_by_file_id: defaultdict[str, list[str]] = defaultdict(list)
    for result in results:
        file_id = result["fileId"]
        if (
            shortlisted_relevant_filters_by_file_id is not None
            and result["filterName"] not in shortlisted_relevant_filters_by_file_id.get(file_id, [])
        ):
            continue
        filter_item_group_ids_by_file_id[file_id].append(result["filterGroupId"])

    return dict(filter_item_group_ids_by_file_id)


def _build_filter_item_candidates(
    file_id: str,
    subject_meta: SubjectMetaResponse,
    filter_item_group_ids: list[str],
) -> DatasetFilterItemCandidates:
    """Numbers every filter item of every filter item group in `filter_item_group_ids`, found in the subject meta.
    Raises a `KeyError` on the first filter item group missing from the subject meta.
    """
    # Datasets without any filters are expected to have no matches
    if subject_meta.filters:
        # Get all the filter item group IDs present in the subject meta
        all_filter_item_group_ids = {
            filter_item_group.id
            for filter_ in subject_meta.filters.values()
            for filter_item_group in filter_.filter_item_groups.values()
        }

        # Ensure that all the filter item group IDs exist in the subject meta
        for filter_item_group_id in filter_item_group_ids:
            if filter_item_group_id not in all_filter_item_group_ids:
                message = (
                    f"Filter item group '{filter_item_group_id}' from the search index was not found in the "
                    f"dataset's subject meta: file_id={file_id}"
                )
                logger.error(message)
                raise KeyError(message)

    # Convert the list of filter item group IDs to a set for faster lookups
    filter_item_group_ids_set = set(filter_item_group_ids)

    candidates: dict[int, FilterItemCandidate] = {}
    reference = 1

   # Build the candidate list by iterating over the subject meta rather than the set of ID's,
   # so that the order is stable for a given release version.
    for filter_ in subject_meta.filters.values():
        for filter_item_group in filter_.filter_item_groups.values():

            # Skip filter item groups that are not in the set of ID's
            if filter_item_group.id not in filter_item_group_ids_set:
                continue

            if not filter_item_group.filter_items:
                logger.error(
                    "Filter item group contains no filter items: file_id=%s, filter_item_group_id=%s",
                    file_id,
                    filter_item_group.id,
                )
                continue

            for filter_item in filter_item_group.filter_items:
                candidates[reference] = FilterItemCandidate(
                    filter_id=filter_.id,
                    filter_label=filter_.label,
                    filter_item=filter_item,
                )
                reference += 1

    return DatasetFilterItemCandidates(candidates)


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


def _resolve_indicators(
    subject_meta: SubjectMetaResponse,
    indicator_results: dict[str, IndicatorDecision] | None,
) -> tuple[list[IndicatorSelectionItem], list[DatasetValidationIssue]]:
    """Resolve the indicators result for the final dataset response, along with any validation issues."""
    issues: list[DatasetValidationIssue] = []
    indicators: list[IndicatorSelectionItem] = []

    for indicator_label, decision in (indicator_results or {}).items():
        if not decision.relevant:
            continue
        try:
            indicator = subject_meta.get_indicator(indicator_label)
        except KeyError:
            issues.append(DatasetValidationIssue(
                code=DatasetValidationIssueCode.INVALID_INDICATOR,
                message=f"No indicator '{indicator_label}' was found for this dataset in the subject meta.",
            ))
            continue
        indicators.append(IndicatorSelectionItem(id=indicator.id, label=indicator_label))

    if not indicators:
        issues.append(DatasetValidationIssue(
            code=DatasetValidationIssueCode.NO_INDICATORS,
            message="No relevant indicators were found for this dataset matching the query.",
        ))

    return indicators, issues


def _resolve_time_period(
    subject_meta: SubjectMetaResponse,
    time_period_result: LlmTimePeriodRange | None,
    time_period_requirement: str | None,
) -> tuple[TimePeriodRange | None, list[DatasetValidationIssue]]:
    """Resolve the time period result for the final dataset response, along with any validation issues."""
    issues: list[DatasetValidationIssue] = []

    if time_period_result is not None:
        # The model returned a time period selection so validate it against the available time periods in the subject meta
        available_time_periods = {(time_period.code, time_period.year) for time_period in subject_meta.time_period.options}
        start_valid = (time_period_result.start.code, time_period_result.start.year) in available_time_periods
        end_valid = (time_period_result.end.code, time_period_result.end.year) in available_time_periods
        if not (start_valid and end_valid):
            issues.append(DatasetValidationIssue(
                code=DatasetValidationIssueCode.INVALID_TIME_PERIOD,
                message=(
                    f"No time period (start: {time_period_result.start.year} {time_period_result.start.code}, "
                    f"end: {time_period_result.end.year} {time_period_result.end.code}) was found for this dataset in the subject meta."
                ),
            ))
            return None, issues

        # Convert from the model response shape to the event response shape
        # The two are currently the same but we're allowing them to diverge in future if needed
        return TimePeriodRange.model_validate(time_period_result.model_dump()), issues

    if time_period_requirement is None:
        # No time period requirement was extracted from the query, so the time period selection agent
        # was skipped. Fallback to the dataset's latest available time period.
        latest_time_period = subject_meta.get_latest_time_period()
        if latest_time_period is None:
            # Should never happen because every dataset is expected to have at least one available time period
            # in its subject meta, but handle this gracefully anyway.
            issues.append(DatasetValidationIssue(
                code=DatasetValidationIssueCode.NO_AVAILABLE_TIME_PERIODS,
                message="No available time periods were found for this dataset in the subject meta.",
            ))
            return None, issues

        return TimePeriodRange(
            start=TimePeriod(code=latest_time_period.code, year=latest_time_period.year),
            end=TimePeriod(code=latest_time_period.code, year=latest_time_period.year),
        ), issues

    # A time period requirement was present, but the model couldn't find a relevant time period matching the requirement.
    # Return None to distinguish this case from the 'no requirement' case.
    # Falling back to the dataset's latest available time period would be misleading.
    issues.append(DatasetValidationIssue(
        code=DatasetValidationIssueCode.NO_TIME_PERIOD,
        message="No relevant time period range was found for this dataset matching the query.",
    ))
    return None, issues


def build_final_dataset_response(
    dataset: DatasetWithSubjectMeta,
    filter_item_candidates: DatasetFilterItemCandidates,
    filter_results: FilterItemDatasetResult | None,
    indicator_results: dict[str, IndicatorDecision] | None,
    time_period_result: LlmTimePeriodRange | None,
    time_period_requirement: str | None,
    location_results: DatasetLocations | None,
    relevance_reason: str | None,
) -> FinalDatasetResponse:
    subject_meta = dataset.subject_meta
    issues: list[DatasetValidationIssue] = []

    # Resolve the model's filter item selections against the filter item candidates it was provided
    selected_filter_items: list[FilterItem] = []
    selected_filter_ids: set[str] = set()

    for raw_reference, decision in (filter_results.filter_items if filter_results else {}).items():
        if not decision.relevant:
            continue

        reference = DatasetFilterItemCandidates.parse_reference(raw_reference)
        if reference is None:
            issues.append(DatasetValidationIssue(
                code=DatasetValidationIssueCode.MALFORMED_FILTER_ITEM_REFERENCE,
                message=f"The filter item reference '{raw_reference}' was not a valid number.",
            ))
            continue

        candidate = filter_item_candidates.get(reference)
        if candidate is None:
            # There was no candidate for the given reference number, indicating an invalid selection by the model.
            issues.append(DatasetValidationIssue(
                code=DatasetValidationIssueCode.INVALID_FILTER_ITEM,
                message=f"No filter item was found for the reference number '{reference}' for this dataset.",
            ))
            continue

        if decision.filter_item_label is not None and decision.filter_item_label != candidate.filter_item.label:
            # Log a warning if the label echoed by the model does not match the candidate's label.
            # This means that the model may have returned an incorrect reference number for the filter item.
            logger.warning(
                "The filter item label returned by the filter selection agent did not match the filter item it referenced: file_id=%s, reference=%s, returned_label='%s', candidate_label='%s'",
                dataset.file_id,
                reference,
                decision.filter_item_label,
                candidate.filter_item.label,
            )

        selected_filter_items.append(candidate.filter_item)
        selected_filter_ids.add(candidate.filter_id)

    # Every filter needs at least one selected filter item for the table query to work correctly.
    # If the model didn't select any relevant filter items for a filter, fallback to its auto_select_filter_item_id if set.
    # In the case of no auto_select_filter_item_id, select every filter item instead.
    # Selecting all filter items has the same effect as not applying the filter (since nothing is excluded).
    # Maintain a record of these auto-selected filter items, and unfiltered filters separately,
    # so they can be returned in the final dataset response. This allows the consumer to differentiate
    # between model selections and fallback selections.
    auto_selected_filters_items: dict[str, AutoSelectedFilterItem] = {}
    unfiltered_filters: list[str] = []

    # Iterate over all filters in the subject meta
    for filter_ in subject_meta.filters.values():
        if filter_.id in selected_filter_ids:
            continue  # the model made a relevant decision for at least one of the filter's filter items

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

    indicators, indicator_issues = _resolve_indicators(subject_meta, indicator_results)
    issues.extend(indicator_issues)

    time_period, time_period_issues = _resolve_time_period(subject_meta, time_period_result, time_period_requirement)
    issues.extend(time_period_issues)

    # The result must have at least one location selection at any geographic level.
    has_location = location_results is not None and any(len(locations) > 0 for locations in location_results.root.values())

    if not has_location:
        issues.append(DatasetValidationIssue(
            code=DatasetValidationIssueCode.NO_LOCATION,
            message="No relevant location was found for this dataset matching the query.",
        ))

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
        validation_issues=issues,
    )


def rrf_to_percentage(rrf_score: float):
    RRF_K = 60
    RRF_MAX = (1.0 / (1 + RRF_K)) + (1.0 / (1 + RRF_K)) #Both components are equal since vector score and BM25 score have same weightage currently

    raw = (rrf_score/RRF_MAX) * 100
    return round(min(raw, 100.0), 1)
