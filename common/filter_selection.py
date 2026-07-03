import asyncio
import logging
from common.openai_client import generate_answer

llm_filtering_sys_prompt="""You are a filter suggestion agent. Your job is to determine which filter and values from a dataset can be suggested to answer a user's data query.

## Your Task
You will be given:
- A user query that has been decomposed into its explicit information requirements
- A dataset description
- A list of filter values

For every filter value, you must work through it in order and make an explicit decision whether it is relevant or not.
The decision for each filter value must be made independently, and in isolation of all other filter values.
The aim should be to match as many filter values as possible to each query requirement.
Each filter must only be compared for semantic relevance with the query requirements, no domain knowledge should be considered.

## Output Format
Return a JSON object in this exact structure:
{   
    "<exact fileId from input>": {
        "filterValues":{
            "<filterValue>": {
                "relevant": true|false,
                "reasoning": one concise sentence about why the relevance is true or false
            }
        }
    }
}
Return only valid JSON. DO NOT include any text before or after the JSON object.
DO NOT wrap the JSON in markdown code blocks, backticks, or any other formatting. 
Return raw JSON only. The first character of your response should be { and the last must be }.
"""

llm_filtering_user_prompt = """## User Query
{raw_query}

## Decomposed Query Requirements
{query_requirements}

## Dataset
Name: {dataset_name}
Description: {dataset_description}
FileID: {file_id}

## Filter Values - process every one in order
{filter_list}

Now work through each filter value and return your suggestions in the specified JSON format.
Try to suggest as many filters as possible that are semantically similar.
DO NOT assume anything about the query requirements based on domain knowledge.
"""


async def run_filter_selection_agent(
    transformed,
    grouped_title_description,
    user_query,
    query_requirements):

    logging.info("Filter Selection Model Running...")
    tasks = []

    for dataset, filters in transformed.items():
        prompt = llm_filtering_user_prompt.format(
            raw_query=user_query,
            query_requirements=query_requirements,
            dataset_name=grouped_title_description[dataset]["title"],
            dataset_description=grouped_title_description[dataset]["description"],
            filter_list=filters,
            file_id=dataset
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

    input_tokens_used = sum(
        response.usage.prompt_tokens for response in model_responses
    )
    output_tokens_used = sum(
        response.usage.completion_tokens for response in model_responses
    )

    contents = [
        response.choices[0].message.content
        for response in model_responses
    ]

    return contents, {'input':input_tokens_used, 'output':output_tokens_used}