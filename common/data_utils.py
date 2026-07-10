from collections import defaultdict
from common.llm_response_parser import parse_llm_response
from common.search_client import filter_client
from schemas.dataset import Dataset
from schemas.filter_selection_response import FilterSelectionResponse
from schemas.indicator_selection_response import IndicatorSelectionResponse
from schemas.time_period_selection_response import TimePeriodSelectionResponse


def retrieve_and_transform_filter_data(reranked_datasets: list, shortlisted_filters: defaultdict=None):
    ## Retrieve full dataset level information from Azure AI Search
    filter_expr = "search.in(fileId, '{}', ',')".format(",".join(reranked_datasets))
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


def combine_responses(filter_responses: list,
                      indicator_responses:list,
                      time_period_responses:list,
                      grouped_datasets: dict[str, Dataset],
                      geo_dict: defaultdict,
                      grouped_relevance_reasons: defaultdict):
    combined_responses = []

    for filter_raw, indicator_raw, time_period_raw in zip(filter_responses, indicator_responses, time_period_responses):

        filter_selection_parsed = parse_llm_response(filter_raw, FilterSelectionResponse, context="filter selection")
        indicator_selection_parsed = parse_llm_response(indicator_raw, IndicatorSelectionResponse, context="indicator selection")
        time_period_selection_parsed = parse_llm_response(time_period_raw, TimePeriodSelectionResponse, context="time period selection")
        filter_data = filter_selection_parsed.root if filter_selection_parsed else {}
        indicator_data = indicator_selection_parsed.root if indicator_selection_parsed else {}
        time_period_data = time_period_selection_parsed.root if time_period_selection_parsed else {}
        combined = {}

        for file_id, dataset_filters in filter_data.items():
            filters = [
                {
                    "id": grouped_datasets[file_id].subject_meta.get_filter_item(
                        filter_item_group_id=filter_item_group_id,
                        filter_item_label=filter_item_label,
                    ).id,
                    "label": filter_item_label,
                }
                for filter_item_descriptor, decision in dataset_filters.filter_items.items()
                if decision.relevant is True
                for _, filter_item_group_id, filter_item_label in [filter_item_descriptor.split("|||")]
            ]

            if filters:
                combined.setdefault(file_id, {"filters": [], "indicators": []})
                combined[file_id]["filters"] = filters

        for file_id, dataset_indicators in indicator_data.items():
            indicators = [
                {
                    "id": grouped_datasets[file_id].subject_meta.get_indicator(indicator_label).id,
                    "label": indicator_label,
                }
                for indicator_label, decision in dataset_indicators.items()
                if decision.relevant is True
            ]

            if indicators:
                combined.setdefault(file_id, {"filters": [], "indicators": []})
                combined[file_id]["indicators"] = indicators

        for file_id, dataset_time_period  in time_period_data.items():
            if file_id in combined:
                combined[file_id]["timePeriod"] = dataset_time_period.model_dump()

        for file_id, geo_matches in geo_dict.items():
            if file_id in combined:
                combined[file_id]["geographicLevels"] = geo_matches

        for file_id, relevance_reason in grouped_relevance_reasons.items():
            if file_id in combined:
                combined[file_id]["relevanceReason"] = relevance_reason

        combined_responses.append(combined)

    final_response = []
    for item in combined_responses:
        for file_id, value in item.items():
            dataset = grouped_datasets[file_id]
            final_response.append({
                "dataSetFileId": dataset.dataSetFileId,
                "fileId": file_id,
                "publicationId": dataset.publicationId,
                "publicationSlug": dataset.publicationSlug,
                "publicationTitle": dataset.publicationTitle,
                "releaseSlug": dataset.releaseSlug,
                "releaseVersionId": dataset.releaseVersionId,
                "subjectId": dataset.subjectId,
                "title": dataset.title,
                "description": dataset.description,
                **value,
            })

    return final_response


def rrf_to_percentage(rrf_score: float):
    RRF_K = 60
    RRF_MAX = (1.0 / (1 + RRF_K)) + (1.0 / (1 + RRF_K)) #Both components are equal since vector score and BM25 score have same weightage currently

    raw = (rrf_score/RRF_MAX) * 100
    return round(min(raw, 100.0), 1)
