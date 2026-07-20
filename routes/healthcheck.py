"""Azure Functions health check handler."""

from azurefunctions.extensions.http.fastapi import Request, JSONResponse


HEALTH_CHECK_RESPONSE = {"message": "API working"}


async def health_check(req: Request) -> JSONResponse:
    return JSONResponse(
        content=HEALTH_CHECK_RESPONSE,
        status_code=200,
    )
