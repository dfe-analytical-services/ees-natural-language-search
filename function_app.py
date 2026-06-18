import asyncio
import azure.functions as func
from azurefunctions.extensions.http.fastapi import Request, StreamingResponse

from core.app import fastapi_app

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.function_name(name="ees_fa_nlsearch_proxy")
@app.route(route="{*route}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def fastapi_proxy(req: Request) -> StreamingResponse:
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    response_started = asyncio.Event()
    response_meta: dict = {
        "status": 200,
        "media_type": "text/plain",
        "headers": [],
    }

    async def asgi_send(message: dict) -> None:
        if message["type"] == "http.response.start":
            response_meta["status"] = message["status"]
            response_meta["headers"] = message.get("headers", [])

            for k, v in message.get("headers", []):
                if k.lower() == b"content-type":
                    response_meta["media_type"] = v.decode()

            response_started.set()

        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                await queue.put(body)

            if not message.get("more_body", False):
                await queue.put(None)  # sentinel: stream complete

    async def body_generator():
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    # Launch FastAPI ASGI app
    asyncio.create_task(
        fastapi_app(req.scope, req._receive, asgi_send)
    )

    # Wait until FastAPI sends response headers
    await response_started.wait()

    return StreamingResponse(
        body_generator(),
        status_code=response_meta["status"],
        media_type=response_meta["media_type"],
    )