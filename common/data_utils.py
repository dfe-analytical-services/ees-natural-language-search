import json
import logging
from collections import defaultdict
from common.search_client import filter_client

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

def combine_responses(model_responses: list, indicator_responses:list, geo_dict: defaultdict):
    combined_responses = []

    for model_raw, indicator_raw in zip(model_responses, indicator_responses):
        model_json = json.loads(model_raw)
        indicator_json = json.loads(indicator_raw)
        combined = {}

        for file_id, file_data in model_json.items():
            filters = [
                filter_value
                for filter_value, details in file_data.get("filterValues", {}).items()
                if details.get("relevant") is True
            ]

            if filters:
                combined.setdefault(file_id, {"filters": [], "indicators": []})
                combined[file_id]["filters"] = filters

        for file_id, file_data in indicator_json.items():
            indicators = [
                indicator_name
                for indicator_name, details in file_data.items()
                if details.get("relevant") is True
            ]

            if indicators:
                combined.setdefault(file_id, {"filters": [], "indicators": []})
                combined[file_id]["indicators"] = indicators
        
        for file_id, geo_matches in geo_dict.items():
            if file_id in combined:
                combined[file_id]["geo_matches"] = geo_matches

        combined_responses.append(combined)

    return combined_responses