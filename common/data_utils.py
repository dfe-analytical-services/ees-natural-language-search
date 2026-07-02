from collections import defaultdict
from common.llm_response_parser import parse_llm_response
from common.search_client import filter_client
from schemas.filter_selection_response import FilterSelectionResponse
from schemas.indicator_selection_response import IndicatorSelectionResponse
from schemas.time_period_selection_response import TimePeriodSelectionResponse
from schemas.subject_meta_response import SubjectMetaResponse


def retrieve_and_transform_filter_data(reranked_datasets: list, shortlisted_filters: defaultdict=None):
    ## Retrieve full dataset level information from Azure AI Search
    filter_expr = "search.in(fileId, '{}', ',')".format(",".join(reranked_datasets))
    results = filter_client.search(
        search_text="*",
        filter=filter_expr,
        select=['fileId', 'filterName','filterValues','filterCategory']
    )

    results = [{'fileId': r['fileId'], 'filterName':r['filterName'],'filterValues':r['filterValues'], 'filterCategory':r['filterCategory']} for r in results]
    if shortlisted_filters:
        results = [
            d
            for d in results
            if d.get("fileId") in shortlisted_filters and d.get("filterName") in shortlisted_filters.get(d.get("fileId"), [])
        ]
    ## Flatten the list of filters and filter values for easier LLM consumption
    results_by_file_id = defaultdict(list)
    for doc in results:
        results_by_file_id[doc["fileId"]].append(doc)

    results_by_file_id = dict(results_by_file_id)

    transformed = {
        file_id: {
            "filters": [
                f"{value}"
                for item in filters
                for value in item["filterValues"]
            ]
        }
        for file_id, filters in results_by_file_id.items()
    }

    return transformed


def combine_responses(filter_responses: list,
                      indicator_responses:list,
                      time_period_responses:list,
                      grouped_subject_meta: dict[str, SubjectMetaResponse],
                      geo_dict: defaultdict,
                      grouped_title_description: defaultdict):
    combined_responses = []

    for filter_raw, indicator_raw, time_period_raw in zip(filter_responses, indicator_responses, time_period_responses):

        filter_selection_parsed = parse_llm_response(filter_raw, FilterSelectionResponse, context="filter selection")
        indicator_selection_parsed = parse_llm_response(indicator_raw, IndicatorSelectionResponse, context="indicator selection")
        time_period_selection_parsed = parse_llm_response(time_period_raw, TimePeriodSelectionResponse, context="time period selection")
        filter_data = filter_selection_parsed.root if filter_selection_parsed else {}
        indicator_data = indicator_selection_parsed.root if indicator_selection_parsed else {}
        time_period_data = time_period_selection_parsed.root if time_period_selection_parsed else {}
        combined = {}

        for file_id, file_data in filter_data.items():
            filters = [
                filter_item_label
                for filter_item_label, details in file_data.filterValues.items()
                if details.relevant is True
            ]

            if filters:
                combined.setdefault(file_id, {"filters": [], "indicators": []})
                combined[file_id]["filters"] = filters

        for file_id, file_data in indicator_data.items():
            indicators = [
                grouped_subject_meta[file_id].get_indicator(indicator_label).id
                for indicator_label, details in file_data.items()
                if details.relevant is True
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

        for file_id, title_desc in grouped_title_description.items():
            if file_id in combined:
                combined[file_id]["aiSummary"] = f'''This data is relevant because {title_desc['relevance_reason']}\n It contains information about {title_desc['description']}'''
                combined[file_id]['title'] = title_desc['title']

        combined_responses.append(combined)

    final_response = [
        {"fileId": key, **value}
        for item in combined_responses
        for key, value in item.items()
    ]

    return final_response


def rrf_to_percentage(rrf_score: float):
    RRF_K = 60
    RRF_MAX = (1.0 / (1 + RRF_K)) + (1.0 / (1 + RRF_K)) #Both components are equal since vector score and BM25 score have same weightage currently

    raw = (rrf_score/RRF_MAX) * 100
    return round(min(raw, 100.0), 1)
