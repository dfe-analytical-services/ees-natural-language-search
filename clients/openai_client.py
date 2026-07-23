import os
from openai import AsyncAzureOpenAI


async def generate_answer(user_query: str, system_prompt: str = "You are a helpful assistant") -> str:
    chat_client = AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )

    response = await chat_client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ],
        temperature=0,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        seed=42
    )

    return response