import logging
import os
from openai import AsyncAzureOpenAI

logger = logging.getLogger(__name__)


async def generate_answer(user_query: str, system_prompt: str = "You are a helpful assistant") -> str:
    chat_client = AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]

    response = await chat_client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=messages,
        temperature=0,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        seed=42
    )

    if logger.isEnabledFor(logging.DEBUG):
        response_content = (
            response.choices[0].message.content
            if response.choices and response.choices[0].message
            else None
        )
        logger.debug(
            "Chat completion\nSystem role message:\n%s\nUser role message:\n%s\nResponse:\n%s",
            system_prompt,
            user_query,
            response_content,
        )

    return response