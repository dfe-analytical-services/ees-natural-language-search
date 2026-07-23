import asyncio
import json
import logging
from clients.openai_client import generate_answer
from schemas.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.token_usage import TokenUsage

logger = logging.getLogger(__name__)

llm_time_period_sys_prompt="""
You are a time period selection agent. Your task is to determine which starting and ending time period from a dataset best fit the time period requirement extracted from a user's data query.

# Inputs
You will be given:
- A user query.
- The time period requirement extracted from the user query.
- The dataset file ID.
- The list of available time period values available in the dataset, in chronological order.

# Task
You must return a start and end time period that best fits the query requirement of the user.
If the dataset does not cover the entire requested time period, choose the largest overlap.
If the user asks for the last 10 years of data and the dataset covers one day of the last 10 years, that will be the largest overlap.

## Output format
Return a JSON object in this exact structure:
{
    "<exact file ID>": {
        "start": {
            "code": "<exact code>",
            "year": <exact year>
        },
        "end": {
            "code": "<exact code>",
            "year": <exact year>
        }
    }
}

Use the exact input values for the file ID, code and year.
Return only valid JSON.
DO NOT include any text before or after the JSON object.
DO NOT wrap the JSON in markdown code blocks, backticks, or any other formatting. 
Return raw JSON only.
The first character of your response should be { and the last must be }.
"""

llm_time_period_user_prompt="""
# User query
{raw_query}

# Time period requirement
{time_period_requirement}

# Dataset
FileID: {file_id}

# Available time periods - in chronological order
{time_period_list}

DO NOT assume anything about the query requirements based on domain knowledge.
"""


async def run_time_period_selection_agent(
    datasets_by_id: dict[str, DatasetWithSubjectMeta],
    user_query: str,
    time_period_requirement: str,
):

    logger.info("Time period selection model running...")
    tasks: list[asyncio.Task] = []

    for file_id, dataset in datasets_by_id.items():
        subject_meta = dataset.subject_meta
        time_period_list_json = json.dumps(
            [time_period.model_dump() for time_period in subject_meta.time_period.options]
        )
        prompt = llm_time_period_user_prompt.format(
            raw_query=user_query,
            time_period_requirement=time_period_requirement,
            time_period_list=time_period_list_json,
            file_id=file_id
        )

        task = asyncio.create_task(
            generate_answer(
                user_query=prompt,
                system_prompt=llm_time_period_sys_prompt,
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
