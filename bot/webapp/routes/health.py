from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
