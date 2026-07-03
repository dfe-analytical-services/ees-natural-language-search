import asyncio
import logging
import os

from clients.ees_data_api_client import EesDataApiClient
from common.reranker import run_reranking_agent
from common.retrieve_datasets import retrieve_datasets
from common.filter_selection import run_filter_selection_agent
from common.time_period_selection import run_time_period_selection_agent
from common.geography_levels_utils import get_geographical_matches
from common.indicator_selection import run_indicator_selection_agent
from common.data_utils import retrieve_and_transform_filter_data, combine_responses, rrf_to_percentage
from schemas.subject_meta_response import SubjectMetaResponse


async def run_workflow(user_query: str, publication_id: str):
    costPer1kTokensInput =  0.0004
    costPer1kTokensOutput = 0.0014
    total_tokens_used = {'input':0, 'output':0}
    yield {"stage": "starting pipeline"}

    logging.info("Retrieving Datasets")
    relevant_datasets, scores, grouped_filters = await retrieve_datasets(user_query=user_query, publication_id=publication_id)

    relevant_datasets_by_id = {
        d["fileId"]: d
        for d in relevant_datasets
    }

    scored_datasets = {'datasets': [{'title': r['title'],
                                     'relevanceScore': rrf_to_percentage(scores[r['fileId']]),
                                     'rawRelevanceScore': scores[r['fileId']]}
                                     for r in relevant_datasets]}
    yield {"stage": "retrieved datasets", "data":scored_datasets}

    logging.info("Running Reranker")
    reranking_results = await run_reranking_agent(user_query, relevant_datasets, grouped_filters)
    reranked_datasets = reranking_results["reranked_datasets"]
    query_requirements = reranking_results["query_requirements"]
    geography_requirements = reranking_results["geography_requirements"]
    grouped_filters = reranking_results["grouped_filters"]
    grouped_indicators = reranking_results["grouped_indicators"]
    grouped_title_description = reranking_results["grouped_title_description"]
    total_tokens_used['input'] += reranking_results["total_tokens_used"]['input']
    total_tokens_used['output'] += reranking_results["total_tokens_used"]['output']
    reranker_response = reranking_results["reranker_response"].model_dump()

    for item in reranker_response.get("shortlistedDatasets", []):
        file_id = item.get("fileId")
        item["relevanceScore"] = rrf_to_percentage(scores.get(file_id))
        if file_id in grouped_title_description:
            grouped_title_description[file_id]['relevance_reason'] = item.get('relevanceReason', '')
    yield {'stage': 'reranker complete', 'data': reranker_response}

    logging.info("Getting subject meta for shortlisted datasets")
    ees_data_api_client = EesDataApiClient(base_url=os.environ["EES_URL_API_DATA"])

    grouped_subject_meta: dict[str, SubjectMetaResponse] = {}
    for file_id in reranked_datasets:
        relevant_dataset = relevant_datasets_by_id[file_id]
        subject_id = relevant_dataset["subjectId"]
        grouped_subject_meta[file_id] = ees_data_api_client.get_subject_meta(subject_id=subject_id)

    logging.info("Getting geography matches")
    geo_dict = await get_geographical_matches(reranked_datasets, grouped_subject_meta, geography_requirements)

    # Can pass grouped filters into this in order to only pass the retrieved filters to the filter selection agent
    logging.info("Transforming dataset information for LLM ingestion")
    transformed_data = retrieve_and_transform_filter_data(reranked_datasets, grouped_filters)
    
    logging.info("Running filter selection, indicator selection, and time period selection models")
    (filter_responses, filter_tokens_used), (indicator_responses, indicator_tokens_used), (time_period_responses, time_period_tokens_used) = await asyncio.gather(
        run_filter_selection_agent(transformed_data,
                                    grouped_title_description,
                                    user_query,
                                    query_requirements,),
        run_indicator_selection_agent(grouped_indicators,
                                    grouped_title_description,
                                    user_query,
                                    query_requirements,),
        run_time_period_selection_agent(reranked_datasets, 
                                        grouped_subject_meta,
                                        user_query, 
                                        query_requirements)
    )
    total_tokens_used['input']+=(filter_tokens_used['input'] + indicator_tokens_used['input'] + time_period_tokens_used['input'])
    total_tokens_used['output']+=(filter_tokens_used['output'] + indicator_tokens_used['output'] + time_period_tokens_used['output'])
    cost = (costPer1kTokensInput*(total_tokens_used['input']/1000)) + (costPer1kTokensOutput*(total_tokens_used['output']/1000))
    
    logging.info("Consolidating Pipeline Responses")
    final_response = combine_responses(filter_responses, indicator_responses, time_period_responses, grouped_subject_meta, geo_dict, grouped_title_description)

    yield {'stage': 'pipeline complete', 'data': {'datasets': final_response, 'token_usage': total_tokens_used, 'cost': cost}}
