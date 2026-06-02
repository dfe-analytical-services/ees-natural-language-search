from fastapi import APIRouter, Request, HTTPException
from openai import AsyncAzureOpenAI
import os

router = APIRouter()

client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    base_url=f'{os.getenv("AZURE_OPENAI_ENDPOINT")}openai/deployments/{os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")}/embeddings?api-version={os.getenv("AZURE_OPENAI_API_VERSION")}',
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)

MODEL_NAME = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))


@router.post("/vectorizer_middleware")
async def vectorizer_middleware(req: Request):
    try:
        body = await req.json()
        values = body.get("values", [])

        texts = [v["data"]["text"] for v in values]

        response = await client.embeddings.create(
            model=MODEL_NAME,
            input=texts if len(texts) > 1 else texts[0],
            dimensions=DIMENSIONS
        )

        embeddings = [item.embedding for item in response.data]

        return {
            "values": [
                {
                    "recordId": values[i]["recordId"],
                    "data": {"embedding": embeddings[i]}
                }
                for i in range(len(values))
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))