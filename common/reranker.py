import json
import logging
from datetime import datetime
from common.search_client import multi_index_search
from common.openai_client import generate_answer

llm_reranker_sys_prompt = """You are a data retrieval specialist. Your job is to analysze a user's query and determine which datasets from a provided list can meaningfully contribute to ansawering it.

## Your Task
Given:
1. A **user query**
2. A **list of dataset metadata dictionaries**
Breakdown the query into separate requirements that the user has mentioned
Identify and return only the datasets that are **directly relevant and usable** to answer the query.

---

## Relevance Criteria
A dataset is considered usable if it meets ALL of the following:
- Its content, schema, or described variables plausibly contain data needed to answer the query
- Its temporal range, geographic scope, or domain is compatible with what the query requires
- It is not redundant given other already-selected datasets (prefer the more specific or complete one)

A dataset should be EXCLUDED if:
- It is only tangentially related by topic but lacks the necessary variables or granularity 
- It's scope (time range, geography, entity type) doesn't match what the query demands
- It duplicates information alreaday covered by a higher quality selected dataset

---

## Reasoning Process
Before returning your answer, think through each dataset systematically:
1. What does the query actually need to be answered? (identify the key data requirements)
2. Identify the potential filters that the user has mentioned in the query requirements
3. For each dataset: does it satisfy one or more of those requirements?

---

## Output Format
Return a JSON object with this exact structure:
{
    "query_requirements": {
        "filters":
            [
                "Concise description of each distinct data requirement extracted from the query which can be a potential filter"
            ],
        "geography":
            [
                "Concise name of each distinct geography requirement extracted from the query. If nothing is identified then it should be National"
            ],
        "time_period": "The specific time interval that the user wants the data for. If nothing is identified then return None."
    },
    "shortlisted_datasets": [
        {
            "file_id": "<exact fileId from metadata>",
            "title": "<exact title from metadata>",
            "relevance_reason": "one brief sentence explaining exactly why this dataset addresses the query",
            "relevant_filters": ["a list of the exact filter names that were deemed to be releavnt to the user query"]
        }
    ],
    "confidence": "high | medium | low",
}

Return only valid JSON. DO not include any text before or after the JSON object.
Do not wrap the JSON in markdown code blocks, backticks, or any other formatting. 
Return raw JSON only. The first character of your response should be { and the last must be }.
"""

llm_reranker_user_prompt = """**User Query**:
{user_query}

**Dataset Metadata**
{dataset_metadata_list}

The date today is {today_date}"""

async def run_reranking_agent(user_query: str, relevant_datasets: list, grouped_filters: list):
    """
    Retrieves, reranks datasets using an LLM, and returns all required artifacts.
    """
    relevant_keys = ['fileId','title','content', 'filters','timePeriodRange']
    total_tokens_used = 0

    reranking_datasets = [
        {k: r[k] for k in relevant_keys}
        for r in relevant_datasets
    ]

    logging.info("Reranking datasets")
    # 2. Rerank retrieved datasets using the LLM
    response = await generate_answer(
        user_query=llm_reranker_user_prompt.format(
            user_query=user_query,
            dataset_metadata_list=reranking_datasets,
            today_date=datetime.today().strftime('%d-%m-%Y')
        ),
        system_prompt=llm_reranker_sys_prompt,
    )
    
    reranker_response, used_tokens = response.choices[0].message.content, response.usage.total_tokens

    logging.info("Reranked datasets")

    total_tokens_used += used_tokens

    reranker_json = json.loads(reranker_response)

    reranked_datasets = [
        d["file_id"] for d in reranker_json["shortlisted_datasets"]
    ]

    logging.info("Extracting filter, indicator and geography requirements from query")
    
    query_requirements = reranker_json["query_requirements"]["filters"]
    geography_requirements = reranker_json["query_requirements"]["geography"]

    # 3. Collect dataset-level metadata for reranked datasets
    grouped_filters = {
        k: grouped_filters[k]
        for k in reranked_datasets
        if k in grouped_filters
    }

    grouped_indicators = {
        d["fileId"]: d["indicators"]
        for d in relevant_datasets
        if d["fileId"] in reranked_datasets
    }

    grouped_title_description = {
        d["fileId"]: {
            "title": d["title"],
            "description": d["content"],
        }
        for d in relevant_datasets
        if d["fileId"] in reranked_datasets
    }

    grouped_geographic_levels = {
        d["fileId"]: d['geographicLevelsLabels']
        for d in relevant_datasets
        if d["fileId"] in reranked_datasets
    }

    return {
        "reranked_datasets": reranked_datasets,
        "relevant_datasets": relevant_datasets,
        "query_requirements": query_requirements,
        "geography_requirements": geography_requirements,
        "grouped_filters": grouped_filters,
        "grouped_indicators": grouped_indicators,
        "grouped_title_description": grouped_title_description,
        "grouped_geographic_levels": grouped_geographic_levels,
        "total_tokens_used": total_tokens_used,
        "reranker_response_raw": reranker_response,
    }
