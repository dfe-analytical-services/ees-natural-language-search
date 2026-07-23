import asyncio
import logging
from clients.openai_client import generate_answer
from schemas.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.token_usage import TokenUsage

logger = logging.getLogger(__name__)

llm_indicator_sys_prompt="""You are an indicator selection agent. Your job is to determine which indicators from a dataset are required to answer a user's data query.
Indicators are non filterable columns that contain mutually exclusive information that the user can choose to view.

# Task
You will be given:
- A user query that has been decomposed into its explicit information requirements
- A dataset description
- A list of indicator values

For every indicator, you must work through it in order and make an explicit decision whether it is relevant or not.

## Output format
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

## Decomposed query requirements
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
    datasets_by_id: dict[str, DatasetWithSubjectMeta],
    user_query: str,
    query_requirements: list[str]):
    
    logger.info("Indicator selection model running...")
    tasks: list[asyncio.Task] = []

    for file_id, indicators in grouped_indicators.items():
        prompt = llm_indicator_user_prompt.format(
            raw_query=user_query,
            query_requirements=query_requirements,
            dataset_name=datasets_by_id[file_id].title,
            dataset_description=datasets_by_id[file_id].description,
            indicator_list=indicators,
            file_id=file_id
        )

        task = asyncio.create_task(
            generate_answer(
                user_query=prompt,
                system_prompt=llm_indicator_sys_prompt,
            )
        )
        tasks.append(task)

    model_responses = await asyncio.gather(*tasks)

    contents = [
        response.choices[0].message.content
        for response in model_responses
    ]

    tokens_used = TokenUsage(
        input=sum(response.usage.prompt_tokens for response in model_responses),
        output=sum(response.usage.completion_tokens for response in model_responses),
    )

    return contents, tokens_used