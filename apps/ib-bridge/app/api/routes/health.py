from fastapi import APIRouter, Depends

from app.api.deps import get_trading_service
from app.models.health import ReadinessResponse
from app.services.trading import TradingService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ReadinessResponse)
async def health(
    trading_service: TradingService = Depends(get_trading_service),
) -> ReadinessResponse:
    snapshot = await trading_service.readiness()
    return ReadinessResponse.model_validate(snapshot)
