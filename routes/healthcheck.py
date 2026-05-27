from fastapi import APIRouter

router = APIRouter()

@router.get("/health_check")
async def health_check():
    return {"message": "API working"}


