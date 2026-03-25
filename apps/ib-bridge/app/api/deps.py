from fastapi import Request

from app.services.trading import TradingService


def get_trading_service(request: Request) -> TradingService:
    return request.app.state.trading_service
