import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from common.workflow import run_workflow

router = APIRouter()


async def stream_response(user_query: str, publication_id: str):
    try:
        async for step in run_workflow(user_query, publication_id):
            yield f"data: {json.dumps(step)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@router.post("/api/natural_language_search_function")
async def natural_language_search_function(request: Request):
    try:
        body: dict[str, str] = await request.json()
    except Exception:
        body = {}

    user_query = body.get("userQuery")
    publication_id = body.get("publicationId")

    if not user_query or not publication_id:
        return Response(content="Missing required fields", status_code=400)

    return StreamingResponse(
        stream_response(user_query=user_query, publication_id=publication_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
