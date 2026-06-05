from fastapi import APIRouter

router = APIRouter()

@router.get("/api/HealthCheck")
async def health_check():
    return {"message": "API working"}


