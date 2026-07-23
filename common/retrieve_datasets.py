from collections.abc import Mapping
import logging
from common.data_utils import rrf_to_percentage
from common.search_client import multi_index_search
from schemas.relevant_dataset_response import RelevantDatasetResponse

logger = logging.getLogger(__name__)


async def retrieve_relevant_datasets(
    user_query: str, publication_id: str
) -> tuple[list[RelevantDatasetResponse], Mapping[str, list[str]]]:
    """
    Get relevant datasets from Azure AI Search
    """
    _, relevant_datasets, scores, grouped_filters = await multi_index_search(
        user_query=user_query, publication_id=publication_id
    )

    logger.info("Retrieved relevant datasets")

    relevant_datasets_responses = [
        RelevantDatasetResponse(
            data_set_file_id=dataset["dataSetFileId"],
            file_id=dataset["fileId"],
            publication_id=dataset["publicationId"],
            publication_slug=dataset["publicationSlug"],
            publication_title=dataset["publicationTitle"],
            release_slug=dataset["releaseSlug"],
            release_version_id=dataset["releaseVersionId"],
            subject_id=dataset["subjectId"],
            title=dataset["title"],
            description=dataset["content"],
            filters=dataset["filters"],
            indicators=dataset["indicators"],
            time_period_range=dataset["timePeriodRange"],
            raw_relevance_score=scores[dataset["fileId"]],
            relevance_score=rrf_to_percentage(scores[dataset["fileId"]]),
        )
        for dataset in relevant_datasets
    ]

    return relevant_datasets_responses, grouped_filters
