from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    app: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from app.config import get_settings

    return HealthResponse(status="ok", app=get_settings().app_name)
