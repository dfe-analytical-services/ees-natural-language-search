import asyncio
import logging
from common.openai_client import generate_answer

llm_indicator_sys_prompt="""You are an indicator selection agent. Your job is to determine which indicators from a dataset are required to answer a user's data query.
Indicators are non filterable columns that contain mutually exclusive information that the user can choose to view.

## Your Task
You will be given:
- A user query that has been decomposed into its explicit information requirements
- A dataset description
- A list of indicator values

For every indicator, you must work through it in order and make an explicit decision whether it is relevant or not.

## Output Format
Return a JSON object in this exact structure:
{   
    "<exact file ID from input>": {
        "<indicator_name>":{
            "relevant": true|false,
            "reasoning": one concise sentence about why the relevance is true or false
        }
    }
}
Return only valid JSON. DO NOT include any text before or after the JSON object.
DO NOT wrap the JSON in markdown code blocks, backticks, or any other formatting. 
Return raw JSON only. The first character of your response should be { and the last must be }.
"""

llm_indicator_user_prompt="""## User Query
{raw_query}

## Decomposed Query Requirements
{query_requirements}

## Dataset
Name: {dataset_name}
Description: {dataset_description}
FileID: {file_id}

## Indicators - process every one in order
{indicator_list}

Now work through each indicator and return your selections in the specified JSON format.
DO NOT assume anything about the query requirements based on domain knowledge. 
"""

async def run_indicator_selection_agent(
    grouped_indicators,
    grouped_title_description,
    user_query,
    query_requirements):
    
    logging.info("Indicator Selection Model running...")
    tasks = []

    for dataset, indicators in grouped_indicators.items():
        prompt = llm_indicator_user_prompt.format(
            raw_query=user_query,
            query_requirements=query_requirements,
            dataset_name=grouped_title_description[dataset]["title"],
            dataset_description=grouped_title_description[dataset]["description"],
            indicator_list=indicators,
            file_id=dataset
        )

        tasks.append(
            generate_answer(
                user_query=prompt,
                system_prompt=llm_indicator_sys_prompt,
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