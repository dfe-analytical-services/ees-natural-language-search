import logging
from collections.abc import Mapping
from datetime import datetime
from common.llm_response_parser import parse_llm_response
from clients.openai_client import generate_answer
from schemas.llm_validation_error import LLMValidationError
from schemas.relevant_dataset_response import RelevantDatasetResponse
from schemas.reranking_agent_result import RerankingAgentResult
from schemas.reranker_response import RerankerResponse
from schemas.token_usage import TokenUsage

logger = logging.getLogger(__name__)

llm_reranker_sys_prompt = """You are a data retrieval specialist. Your job is to analyse a user's query and determine which datasets from a provided list can meaningfully contribute to answering it.

## Your Task
Given:
1. A **user query**
2. A **list of dataset metadata dictionaries**
Break down the query into separate requirements that the user has mentioned
Identify and return only the datasets that are **directly relevant and usable** to answer the query.

---

## Relevance Criteria
A dataset is considered usable if it meets ALL of the following:
- Its content, schema, or described variables plausibly contain data needed to answer the query
- Its geographic scope, or domain is compatible with what the query requires
- It is not redundant given other already-selected datasets (prefer the more specific or complete one)

A dataset should be EXCLUDED if:
- It is only tangentially related by topic but lacks the necessary variables or granularity 
- Its geography or entity type doesn't match what the query demands
- There are NO temporal reasons to completely exclude a dataset.
- It duplicates information already covered by a higher quality selected dataset

---

## Time Period Criteria
If a user requests data for the last 10 years, a dataset is DEFINITELY usable if it contains data for at least one day within the requested 10-year period.

## Reasoning Process
Before returning your answer, think through each dataset systematically:
1. What does the query actually need to be answered? (identify the key data requirements)
2. Identify the potential filters that the user has mentioned in the query requirements
3. For each dataset: does it satisfy one or more of those requirements?

---

## Output Format
Return a JSON object with this exact structure:
{
    "queryRequirements": {
        "filters":
            [
                "Concise description of each distinct data requirement extracted from the query which can be a potential filter"
            ],
        "geography":
            [
                "Concise name of each distinct geography requirement extracted from the query. It can be as granular as a specific school. If nothing is identified then it should be National"
            ],
        "timePeriod": "The specific time interval that the user wants the data for. If nothing is identified then return None."
    },
    "shortlistedDatasets": [
        {
            "fileId": "<exact fileId from metadata>",
            "title": "<exact title from metadata>",
            "relevanceReason": "1-2 brief sentences explaining exactly why this dataset addresses the query for a user summary. This should be separate from the dataset description.",
            "relevantFilters": ["a list of the exact filter names that were deemed to be relevant to the user query"]
        }
    ],
    "confidence": "high | medium | low"
}

Return only valid JSON. DO NOT include any text before or after the JSON object.
DO NOT wrap the JSON in markdown code blocks, backticks, or any other formatting.
Return raw JSON only. The first character of your response should be { and the last must be }.
"""

llm_reranker_user_prompt = """**User Query**:
{user_query}

**Dataset Metadata**
{dataset_metadata_list}

The date today is {today_date}"""


async def run_reranking_agent(
    user_query: str,
    relevant_datasets: list[RelevantDatasetResponse],
    grouped_filters: Mapping[str, list[str]],
) -> RerankingAgentResult:
    """
    Retrieves, reranks datasets using an LLM, and returns all required artifacts.
    """

    # TODO Add indicators to reranking_datasets and adjust prompt and RerankerResponse to include them?

    reranking_datasets = [
        {
            "fileId": dataset.fileId,
            "title": dataset.title,
            "content": dataset.description,
            "filters": dataset.filters,
            "timePeriodRange": dataset.timePeriodRange.model_dump(by_alias=True)
        }
        for dataset in relevant_datasets
    ]

    logger.info("Reranking datasets")
    # 2. Rerank retrieved datasets using the LLM
    response = await generate_answer(
        user_query=llm_reranker_user_prompt.format(
            user_query=user_query,
            dataset_metadata_list=reranking_datasets,
            today_date=datetime.today().strftime('%d-%m-%Y')
        ),
        system_prompt=llm_reranker_sys_prompt,
    )

    reranker_response, used_input_tokens, used_output_tokens = response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens

    logger.info("Reranked datasets")

    total_tokens_used = TokenUsage(input=used_input_tokens, output=used_output_tokens)

    reranker_parsed = parse_llm_response(reranker_response, RerankerResponse, context='ranker')
    if reranker_parsed is None:
        raise LLMValidationError("The reranking step returned a malformed response, the query could not be processed.")

    reranked_dataset_file_ids = [
        d.fileId for d in reranker_parsed.shortlistedDatasets
    ]

    shortlisted_grouped_filters = {
        file_id: grouped_filters[file_id]
        for file_id in reranked_dataset_file_ids
        if file_id in grouped_filters
    }

    grouped_indicators = {
        dataset.fileId: dataset.indicators
        for dataset in relevant_datasets
        if dataset.fileId in reranked_dataset_file_ids
    }

    return RerankingAgentResult(
        grouped_filters=shortlisted_grouped_filters,
        grouped_indicators=grouped_indicators,
        reranker_response=reranker_parsed,
        total_tokens_used=total_tokens_used,
    )
