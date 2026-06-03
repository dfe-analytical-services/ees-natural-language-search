import logging
from common.search_client import multi_index_search

async def retrieve_datasets(user_query: str, publication: str):
    '''
    Get relevant datasets from Azure AI Search
    '''
    _, relevant_datasets, scores, grouped_filters = await multi_index_search(
        user_query=user_query,
        publication=publication
    )

    logging.info("Retrieved relevant datasets")

    return relevant_datasets, scores, grouped_filters