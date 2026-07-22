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
    combine_final_dataset_responses
)
from schemas.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.event_responses import (
    PipelineCompleteEventData,
    PipelineCompleteEventResponse,
    RetrievedDatasetsEventData,
    RerankerEventResponse,
    RerankerEventData,
    RetrievedDatasetsEventResponse,
    StartEventResponse,
)
from schemas.reranker_dataset_response import RerankerDatasetResponse
from schemas.token_usage import TokenUsage

logger = logging.getLogger(__name__)


async def run_workflow(user_query: str, publication_id: str):
    yield StartEventResponse().model_dump()

    logger.info("Retrieving relevant datasets")
    relevant_dataset_responses, grouped_filters = (
        await retrieve_relevant_datasets(
            user_query=user_query, publication_id=publication_id
        )
    )

    retrieved_datasets_event = RetrievedDatasetsEventResponse(
        data=RetrievedDatasetsEventData(datasets=relevant_dataset_responses)
    )

    yield retrieved_datasets_event.model_dump(by_alias=True)

    logger.info("Running reranker")
    reranker_result = await run_reranking_agent(
        user_query, relevant_dataset_responses, grouped_filters
    )

    relevant_datasets_by_id = {
        dataset.fileId: dataset
        for dataset in relevant_dataset_responses
    }

    reranker_datasets: list[RerankerDatasetResponse] = []
    for dataset in reranker_result.reranker_response.shortlistedDatasets:
        relevant_dataset = relevant_datasets_by_id.get(dataset.fileId)
        if relevant_dataset is None:
            raise KeyError(
                f"Relevant dataset for file ID '{dataset.fileId}' not found"
            )

        # Use a combination of the relevant dataset data and the shortlisted reranker response data to create a reranker dataset response
        reranker_datasets.append(
            RerankerDatasetResponse(
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
                relevanceReason=dataset.relevanceReason,
                relevantFilters=dataset.relevantFilters,
                relevanceScore=relevant_dataset.relevanceScore,
            )
        )

    reranker_event = RerankerEventResponse(
        data=RerankerEventData(
            confidence=reranker_result.reranker_response.confidence,
            datasets=reranker_datasets,
            query_requirements=reranker_result.reranker_response.queryRequirements,
            token_usage=reranker_result.total_tokens_used,
            cost=calculate_token_cost(reranker_result.total_tokens_used),
        ),
    )

    yield reranker_event.model_dump()

    total_tokens_used = TokenUsage(
        input=reranker_result.total_tokens_used.input,
        output=reranker_result.total_tokens_used.output,
    )

    relevance_reasons_by_id = {
        dataset.fileId: dataset.relevanceReason
        for dataset in reranker_datasets
    }

    logger.info("Getting subject meta for shortlisted datasets")
    ees_data_api_client = EesDataApiClient(base_url=os.environ["EES_URL_API_DATA"])

    # Add subject meta to the reranked datasets for use in getting the geographical matches,
    # and in the filter selection, indicator selection, and time period selection agents
    reranked_datasets_by_id: dict[str, DatasetWithSubjectMeta] = {}
    for reranker_dataset in reranker_datasets:
        subject_meta = ees_data_api_client.get_subject_meta(
            subject_id=reranker_dataset.subjectId
        )
        reranked_datasets_by_id[reranker_dataset.fileId] = DatasetWithSubjectMeta(
            dataSetFileId=reranker_dataset.dataSetFileId,
            fileId=reranker_dataset.fileId,
            publicationId=reranker_dataset.publicationId,
            publicationSlug=reranker_dataset.publicationSlug,
            publicationTitle=reranker_dataset.publicationTitle,
            releaseSlug=reranker_dataset.releaseSlug,
            releaseVersionId=reranker_dataset.releaseVersionId,
            subjectId=reranker_dataset.subjectId,
            title=reranker_dataset.title,
            description=reranker_dataset.description,
            subject_meta=subject_meta,
        )

    logger.info("Getting geography matches")
    geo_dict = await get_geographical_matches(
        reranked_datasets_by_id, reranker_result.reranker_response.queryRequirements.geography
    )

    # Can pass grouped filters into this in order to only pass the retrieved filters to the filter selection agent
    logger.info("Transforming dataset information for LLM ingestion")
    transformed_data = retrieve_and_transform_filter_data(
        file_ids=list(reranked_datasets_by_id.keys()), shortlisted_filters=reranker_result.grouped_filters
    )

    logger.info(
        "Running filter selection, indicator selection, and time period selection models"
    )
    (
        (filter_responses, filter_tokens_used),
        (indicator_responses, indicator_tokens_used),
        (time_period_responses, time_period_tokens_used),
    ) = await asyncio.gather(
        run_filter_selection_agent(
            transformed_data,
            reranked_datasets_by_id,
            user_query,
            reranker_result.reranker_response.queryRequirements.filters,
        ),
        run_indicator_selection_agent(
            reranker_result.grouped_indicators,
            reranked_datasets_by_id,
            user_query,
            reranker_result.reranker_response.queryRequirements.filters,
        ),
        run_time_period_selection_agent(
            # TODO why doesn't this use the time period from the query requirements?
            reranked_datasets_by_id, user_query, reranker_result.reranker_response.queryRequirements.filters
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
        reranked_datasets_by_id,
        geo_dict,
        relevance_reasons_by_id,
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
