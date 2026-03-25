from fastapi import APIRouter

from app.core.config import get_settings
from app.models.meta import ServiceInfoResponse

router = APIRouter(tags=["meta"])


@router.get("/", response_model=ServiceInfoResponse)
async def service_info() -> ServiceInfoResponse:
    settings = get_settings()
    return ServiceInfoResponse(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.env,
    )
