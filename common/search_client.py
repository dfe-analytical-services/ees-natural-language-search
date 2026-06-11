import os
import time
from openai import AsyncAzureOpenAI
from collections import defaultdict
from azure.search.documents import SearchClient
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery

azure_search_key = os.environ.get("AZURE_SEARCH_KEY")
if azure_search_key and len(azure_search_key)>0:
    credential = azure_search_key
else:
    credential = DefaultAzureCredential()

filter_client = SearchClient(
    endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
    index_name=os.environ["AZURE_SEARCH_FILTER_INDEX"],
    credential=credential
)

dataset_client = SearchClient(
    endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
    index_name=os.environ["AZURE_SEARCH_DATASET_INDEX"],
    credential=credential
)

def batch(items, size=20):
    for i in range(0, len(items), size):
        yield items[i:i+size]

async def get_embeddings(input_text: str | list[str], model_name: str, dimensions: int = 1536):
    client = AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
    
    if isinstance(input_text, list):
        all_embeddings = []
        total_tokens = 0

        batches = list(batch(input_text, 15))

        for chunk in batches:
            for attempt in range(1, 2 + 1):
                try:
                    response = await client.embeddings.create(
                        model=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],  
                        input= chunk,
                        dimensions=dimensions
                    )

                    all_embeddings.extend(d.embedding for d in response.data)
                    total_tokens += response.usage.total_tokens

                    # Advance progress bar by number of texts processed
                    break

                except Exception as e:
                    if attempt == 2:
                        print(f"Tokens Processed: {total_tokens}")
                        print(chunk)
                        raise RuntimeError(f"Embedding failed after {2} attempts") from e

                    # Backoff for transient errors (504s, throttling)
                    time.sleep(2 ** attempt)

        return all_embeddings, total_tokens


    response = await client.embeddings.create(
        input = input_text,
        model = model_name,
        dimensions = dimensions
    )

    embeddings = [x.embedding for x in response.data]

    return embeddings, response.usage.total_tokens

async def hybrid_search(user_query: str, publication: str = None, top: int=10, weight: int=0.5):
    query_vector, _ = await get_embeddings(user_query, 'text-embedding-3-large')

    vector_query = VectorizedQuery(
        vector=query_vector[0],
        fields="embedding",
        k_nearest_neighbors=10,
        weight=weight,
    )

    results = filter_client.search(
        search_text=user_query,
        vector_queries=[vector_query],
        filter = f"publicationTitle eq '{publication}' and latestData eq true" if publication else publication,
        top=top
    )

    return user_query, results

async def multi_index_search(user_query: str, publication: str, top: int=10):
    query, results = await hybrid_search(user_query=user_query, 
                                   publication=publication, 
                                   top=top)
    dataset_ids = set()
    grouped_filters = defaultdict(list)
    for r in results:
        dataset_ids.add(r['fileId'])
        grouped_filters[r['fileId']].append(r['filterName'])

    datasets = [dataset_client.get_document(dataset_id) for dataset_id in dataset_ids]

    return query, datasets, grouped_filters