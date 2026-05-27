import json
import asyncio

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import StreamingResponse

from common.workflow import run_workflow

router = APIRouter()

async def stream_response(user_query, publication):
    try:
        async for step in run_workflow(user_query, publication):
            yield f"data: {json.dumps(step)}\n\n"
            await asyncio.sleep(1)
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@router.post("/natural_language_search_function")
async def natural_language_search_function(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_query = body.get("user_query")
    publication = body.get("publication")

    return StreamingResponse(
        stream_response(user_query, publication),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
