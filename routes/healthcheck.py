from azurefunctions.extensions.http.fastapi import Request, JSONResponse

async def health_check(req: Request) -> JSONResponse:
    return JSONResponse(
        content={"message": "API working"},
        status_code=200,
    )