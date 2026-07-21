import logging
from common.data_utils import rrf_to_percentage
from common.search_client import multi_index_search
from schemas.relevant_dataset_response import RelevantDatasetResponse


async def retrieve_relevant_datasets(user_query: str, publication_id: str) -> tuple[list[RelevantDatasetResponse], dict, dict]:
    '''
    Get relevant datasets from Azure AI Search
    '''
    _, relevant_datasets, scores, grouped_filters = await multi_index_search(
        user_query=user_query,
        publication_id=publication_id
    )

    logging.info("Retrieved relevant datasets")

    relevant_datasets_responses = [
        RelevantDatasetResponse(
            dataSetFileId=dataset["dataSetFileId"],
            fileId=dataset["fileId"],
            publicationId=dataset["publicationId"],
            publicationSlug=dataset["publicationSlug"],
            publicationTitle=dataset["publicationTitle"],
            releaseSlug=dataset["releaseSlug"],
            releaseVersionId=dataset["releaseVersionId"],
            subjectId=dataset["subjectId"],
            title=dataset["title"],
            description=dataset["content"],
            filters=dataset["filters"],
            indicators=dataset["indicators"],
            timePeriodRange=dataset["timePeriodRange"],
            rawRelevanceScore=scores[dataset["fileId"]],
            relevanceScore=rrf_to_percentage(scores[dataset["fileId"]]),
        )
        for dataset in relevant_datasets
    ]

    return relevant_datasets_responses, scores, grouped_filters
