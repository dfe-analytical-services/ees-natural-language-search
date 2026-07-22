import asyncio
import logging
from common.openai_client import generate_answer
from schemas.dataset import Dataset
from schemas.token_usage import TokenUsage

logger = logging.getLogger(__name__)

llm_time_period_sys_prompt="""You are a time period selection agent. Your job is to determine which starting and ending time period from a dataset best fit the requirement in a user's data query.

## Your Task
You will be given:
- A user query that has been decomposed into its explicit information requirements
- A list of available time period values

You must return a start and end time period that best fits the query requirements of the user.
If the dataset does not cover the entire requested time period, choose the largest overlap.
If the user asks for the last 10 years of data and the dataset covers one day of the last 10 years, that will be the largest overlap.

## Output Format
Return a JSON object in this exact structure:
{   
    "<exact fileId from input>": {
        "start":{
            "code":"<exact code>"
            "year":"<exact year>"
        }
        "end":{
            "code":"<exact code>"
            "year":"<exact year>"
        }
    }
}
Return only valid JSON. DO NOT include any text before or after the JSON object.
DO NOT wrap the JSON in markdown code blocks, backticks, or any other formatting. 
Return raw JSON only. The first character of your response should be { and the last must be }.
"""

llm_time_period_user_prompt="""## User Query
{raw_query}

## Decomposed Query Requirements
{query_requirements}

## Dataset
FileID: {file_id}

## Time periods - in chronological order
{time_period_list}

DO NOT assume anything about the query requirements based on domain knowledge. 
"""


async def run_time_period_selection_agent(
    reranked_datasets,
    grouped_datasets: dict[str, Dataset],
    user_query: str,
    query_requirements: list[str],
):

    logger.info("Time period selection model running...")
    tasks = []

    for file_id in reranked_datasets:
        subject_meta = grouped_datasets[file_id].subject_meta
        prompt = llm_time_period_user_prompt.format(
            raw_query=user_query,
            query_requirements=query_requirements,
            time_period_list=subject_meta.time_period.options,
            file_id=file_id
        )

        tasks.append(
            asyncio.create_task(
                    generate_answer(
                        user_query=prompt,
                        system_prompt=llm_time_period_sys_prompt,
                    )
                )
        )

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
