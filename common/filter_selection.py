import asyncio
import logging
from common.openai_client import generate_answer
from schemas.dataset import Dataset
from schemas.workflow_response import TokenUsage

llm_filtering_sys_prompt = """You are a filter suggestion agent.
Your task is to determine which filter items from a dataset are semantically relevant to a user's data query.

# Definitions
## Filter
A filter is a filterable column in the dataset.

## Filter Item
A filter item is a selectable value within a filter column found in the dataset.

## Filter Item Groups
A filter item group is a collection of related filter items within the same filter.

# Inputs
You will be given:
- A user query decomposed into explicit information requirements.
- A dataset file ID, name and description.
- A list of filter items.

Each filter item is represented by three fields:
- Filter label
- Filter item group ID
- Filter item label

The file ID and filter item group IDs are identifiers and must not be interpreted semantically.
Only the filter label and filter item label should be used to determine semantic relevance.

# Task
You must evaluate every filter item one at a time, in the order provided.

For each filter item:
1. Compare the filter label and the filter item label to the user's explicit query requirements.
2. Decide whether the filter item is semantically relevant to at least one query requirement.

A filter item is semantically relevant if, based only on its filter label and filter item label, it matches or directly satisfies at least one explicit query requirement. Otherwise it is not relevant.
You may use the dataset name and description only to interpret the meaning of the dataset and its filters, not as evidence that any filter item is relevant or to infer additional query requirements.

The decision for each filter item must be made independently.
Do NOT let previous or subsequent filter items influence your current decision.
Do NOT use external knowledge, domain knowledge, or any other information not contained in the query requirements and filter item.

## Output Format
Return a JSON object in this exact structure:
{   
    "<exact file ID>": {
        "filterItems":{
            "<exact filter label>|||<exact filter item group ID>|||<exact filter item label>": {
                "relevant": true|false,
                "reasoning": One concise sentence explaining the decision using only the query requirement and the filter item's text.
            }
        }
    }
}

Use the exact input values for all filter item keys.
Return only valid JSON.
DO NOT include any text before or after the JSON object.
DO NOT wrap the JSON in markdown code blocks, backticks, or any other formatting. 
Return raw JSON only.
The first character of your response should be { and the last must be }.
"""

llm_filtering_user_prompt = """## User Query
{raw_query}

## Decomposed Query Requirements
{query_requirements}

## Dataset
Name: {dataset_name}
Description: {dataset_description}
FileID: {file_id}

## Filter Items
{filter_list}

Each filter item uses the exact format `filter label|||filter item group ID|||filter item label`.
Now work through each filter item and return your suggestions in the specified JSON format.
Try to suggest as many filter items as possible that are semantically similar.
DO NOT assume anything about the query requirements based on domain knowledge.
"""


async def run_filter_selection_agent(
    transformed,
    grouped_datasets: dict[str, Dataset],
    user_query: str,
    query_requirements: list[str],
):

    logging.info("Filter Selection Model Running...")
    tasks = []

    for file_id, filters in transformed.items():
        prompt = llm_filtering_user_prompt.format(
            raw_query=user_query,
            query_requirements=query_requirements,
            dataset_name=grouped_datasets[file_id].title,
            dataset_description=grouped_datasets[file_id].description,
            filter_list=filters,
            file_id=file_id,
        )

        tasks.append(
            asyncio.create_task(
                generate_answer(
                    user_query=prompt,
                    system_prompt=llm_filtering_sys_prompt,
                )
            )
        )

    model_responses = await asyncio.gather(*tasks)

    contents = [response.choices[0].message.content for response in model_responses]

    tokens_used = TokenUsage(
        input=sum(response.usage.prompt_tokens for response in model_responses),
        output=sum(response.usage.completion_tokens for response in model_responses),
    )

    return contents, tokens_used
