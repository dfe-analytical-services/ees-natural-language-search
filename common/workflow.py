import asyncio
import json
import logging
from common.reranker import run_reranking_agent
from common.retrieve_datasets import retrieve_datasets
from common.filter_selection import run_filter_selection_agent
from common.geography_levels_utils import get_geographical_matches
from common.indicator_selection import run_indicator_selection_agent
from common.data_utils import retrieve_and_transform_filter_data, combine_responses, rrf_to_percentage

async def run_workflow(user_query: str, publication: str):
    total_tokens_used = 0
    yield {"stage": "starting pipeline"}

    logging.info("Retrieving Datasets")
    relevant_datasets, scores, grouped_filters = await retrieve_datasets(user_query=user_query, publication=publication)

    scored_datasets = {'datasets': [{'title': r['title'], 
                                     'relevanceScore': rrf_to_percentage(scores[r['fileId']]),
                                     'rawRelevanceScore': scores[r['fileId']]}
                                     for r in relevant_datasets]}
    yield {"stage": "retrieved datasets", "data":scored_datasets}

    logging.info("Running Reranker")
    reranking_results = await run_reranking_agent(user_query, relevant_datasets, grouped_filters)
    reranked_datasets = reranking_results["reranked_datasets"]
    relevant_datasets = reranking_results["relevant_datasets"]
    query_requirements = reranking_results["query_requirements"]
    geography_requirements = reranking_results["geography_requirements"]
    grouped_filters = reranking_results["grouped_filters"]
    grouped_indicators = reranking_results["grouped_indicators"]
    grouped_title_description = reranking_results["grouped_title_description"]
    grouped_geographic_levels = reranking_results["grouped_geographic_levels"]
    total_tokens_used += reranking_results["total_tokens_used"]
    reranker_response = json.loads(reranking_results["reranker_response_raw"])

    for item in reranker_response.get("shortlistedDatasets", []):
        file_id = item.get("fileId")
        item["relevanceScore"] = rrf_to_percentage(scores.get(file_id))
        if file_id in grouped_title_description:
            grouped_title_description[file_id]['relevance_reason'] = item.get('relevanceReason', '')
    yield {'stage': 'reranker complete', 'data': reranker_response}

    logging.info("Getting geography matches")
    # geo_dict = geo_filter_and_group_matches([get_location_matches(x) for x in geography_requirements], grouped_geographic_levels)
    geo_dict = get_geographical_matches(grouped_geographic_levels, geography_requirements)

    # Can pass grouped filters into this in order to only pass the retrieved filters to the filter selection agent
    logging.info("Transforming dataset information for LLM ingestion")
    transformed_data = retrieve_and_transform_filter_data(reranked_datasets, grouped_filters)

    logging.info("Running filter selection and indicator selection models")
    (model_responses, filter_tokens_used), (indicator_responses, indicator_tokens_used) = await asyncio.gather(
        run_filter_selection_agent(transformed_data,
                                    grouped_title_description,
                                    user_query,
                                    query_requirements,),
        run_indicator_selection_agent(grouped_indicators,
                                    grouped_title_description,
                                    user_query,
                                    query_requirements,)
    )
    total_tokens_used+=(filter_tokens_used + indicator_tokens_used)

    logging.info("Consolidating Pipeline Responses")
    final_response = combine_responses(model_responses, indicator_responses, geo_dict, grouped_title_description)

    yield {'stage': 'pipeline complete', 'data': {'datasets': final_response, 'token_usage': total_tokens_used}}


