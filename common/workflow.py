import asyncio
import logging
import os

from clients.ees_data_api_client import EesDataApiClient
from common.reranker import run_reranking_agent
from common.filter_selection import run_filter_selection_agent
from common.retrieve_datasets import retrieve_relevant_datasets
from common.time_period_selection import run_time_period_selection_agent
from common.geography_levels_utils import get_geographical_matches
from common.indicator_selection import run_indicator_selection_agent
from common.data_utils import (
    retrieve_and_transform_filter_data,
    combine_final_dataset_responses,
    rrf_to_percentage,
)
from schemas.dataset import Dataset
from schemas.event_responses import PipelineCompleteEventData, PipelineCompleteEventResponse, RetrievedDatasetsEventData, RetrievedDatasetsEventResponse, StartEventResponse
from schemas.token_usage import TokenUsage

logger = logging.getLogger(__name__)


async def run_workflow(user_query: str, publication_id: str):
    total_tokens_used = TokenUsage()

    yield StartEventResponse().model_dump()

    logger.info("Retrieving relevant datasets")
    relevant_dataset_responses, scores, grouped_filters = await retrieve_relevant_datasets(user_query=user_query, publication_id=publication_id)

    retrieved_datasets_event = RetrievedDatasetsEventResponse(
        data=RetrievedDatasetsEventData(datasets=relevant_dataset_responses)
    )

    yield retrieved_datasets_event.model_dump(by_alias=True)

    logger.info("Running reranker")
    reranking_results = await run_reranking_agent(user_query, relevant_dataset_responses, grouped_filters)

    total_tokens_used.input += reranking_results["total_tokens_used"].input
    total_tokens_used.output += reranking_results["total_tokens_used"].output
    reranker_response = reranking_results["reranker_response"].model_dump()

    # TODO Do this in run_reranking_agent?
    for item in reranker_response.get("shortlistedDatasets", []):
        file_id = item.get("fileId")
        item["relevanceScore"] = rrf_to_percentage(scores.get(file_id))

    yield {'stage': 'reranker complete', 'data': reranker_response}

    relevant_datasets_by_id = {
        dataset.fileId: dataset
        for dataset in relevant_dataset_responses
    }

    reranked_datasets = reranking_results["reranked_datasets"]
    query_requirements = reranking_results["query_requirements"]
    geography_requirements = reranking_results["geography_requirements"]
    grouped_filters = reranking_results["grouped_filters"]
    grouped_indicators = reranking_results["grouped_indicators"]

    # TODO Do this in run_reranking_agent?
    grouped_relevance_reasons = {
        item["fileId"]: item.get('relevanceReason', '')
        for item in reranker_response.get("shortlistedDatasets", [])
    }

    logger.info("Getting subject meta for shortlisted datasets")
    ees_data_api_client = EesDataApiClient(base_url=os.environ["EES_URL_API_DATA"])

    grouped_datasets: dict[str, Dataset] = {}
    for file_id in reranked_datasets:
        relevant_dataset = relevant_datasets_by_id[file_id]
        subject_meta = ees_data_api_client.get_subject_meta(
            subject_id=relevant_dataset.subjectId
        )
        grouped_datasets[file_id] = Dataset(
            dataSetFileId=relevant_dataset.dataSetFileId,
            fileId=relevant_dataset.fileId,
            publicationId=relevant_dataset.publicationId,
            publicationSlug=relevant_dataset.publicationSlug,
            publicationTitle=relevant_dataset.publicationTitle,
            releaseSlug=relevant_dataset.releaseSlug,
            releaseVersionId=relevant_dataset.releaseVersionId,
            subjectId=relevant_dataset.subjectId,
            title=relevant_dataset.title,
            description=relevant_dataset.description,
            subject_meta=subject_meta,
        )

    logger.info("Getting geography matches")
    geo_dict = await get_geographical_matches(
        reranked_datasets, grouped_datasets, geography_requirements
    )

    # Can pass grouped filters into this in order to only pass the retrieved filters to the filter selection agent
    logger.info("Transforming dataset information for LLM ingestion")
    transformed_data = retrieve_and_transform_filter_data(reranked_datasets, grouped_filters)

    logger.info("Running filter selection, indicator selection, and time period selection models")
    (
        (filter_responses, filter_tokens_used),
        (indicator_responses, indicator_tokens_used),
        (time_period_responses, time_period_tokens_used),
    ) = await asyncio.gather(
        run_filter_selection_agent(
            transformed_data,
            grouped_datasets,
            user_query,
            query_requirements,
        ),
        run_indicator_selection_agent(
            grouped_indicators,
            grouped_datasets,
            user_query,
            query_requirements,
        ),
        run_time_period_selection_agent(
            reranked_datasets, grouped_datasets, user_query, query_requirements
        ),
    )
    total_tokens_used.input += (
        filter_tokens_used.input
        + indicator_tokens_used.input
        + time_period_tokens_used.input
    )
    total_tokens_used.output += (
        filter_tokens_used.output
        + indicator_tokens_used.output
        + time_period_tokens_used.output
    )

    logger.info("Combining final dataset responses")
    final_dataset_responses = combine_final_dataset_responses(
        filter_responses,
        indicator_responses,
        time_period_responses,
        grouped_datasets,
        geo_dict,
        grouped_relevance_reasons,
    )

    pipeline_complete_event = PipelineCompleteEventResponse(
        data=PipelineCompleteEventData(
            datasets=final_dataset_responses,
            token_usage=total_tokens_used,
            cost=calculate_token_cost(total_tokens_used),
        )
    )

    yield pipeline_complete_event.model_dump()

def calculate_token_cost(tokens: TokenUsage) -> float:
    costPer1kTokensInput = 0.0004
    costPer1kTokensOutput = 0.0014
    return (costPer1kTokensInput * (tokens.input / 1000)) + (
        costPer1kTokensOutput * (tokens.output / 1000)
    )
