from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.trading import InstrumentContractSpec
from app.services.trading import TradingService


@pytest.mark.asyncio
async def test_closed_venue_still_returns_delayed_quote_when_market_data_exists() -> None:
    service = TradingService(Settings(env="test"))
    service._read_cache.clear()

    async def closed_note(_spec: InstrumentContractSpec) -> str | None:
        return "NMS is currently closed per IB trading hours"

    async def market_quote(_spec: InstrumentContractSpec) -> dict[str, object]:
        return {
            "ticker": SimpleNamespace(bid=100.0, ask=100.2, last=100.1, close=99.5),
            "data_mode": "delayed",
        }

    service._instrument_closed_note = closed_note  # type: ignore[method-assign]
    service._client = SimpleNamespace(market_quote=market_quote)

    quote = await service.get_market_quote(InstrumentContractSpec(symbol="AAPL"))

    assert quote.data_mode == "delayed"
    assert quote.quote_available is True
    assert quote.last == 100.1
    assert quote.availability_note == "NMS is currently closed per IB trading hours"


@pytest.mark.asyncio
async def test_closed_venue_note_is_preserved_when_quote_unavailable() -> None:
    service = TradingService(Settings(env="test"))
    service._read_cache.clear()

    async def closed_note(_spec: InstrumentContractSpec) -> str | None:
        return "NMS is currently closed per IB trading hours"

    async def market_quote(_spec: InstrumentContractSpec) -> dict[str, object]:
        raise ValueError("Market data error 10089 for symbol=AAPL")

    service._instrument_closed_note = closed_note  # type: ignore[method-assign]
    service._client = SimpleNamespace(market_quote=market_quote)

    quote = await service.get_market_quote(InstrumentContractSpec(symbol="AAPL"))

    assert quote.data_mode == "unavailable"
    assert quote.quote_available is False
    assert quote.availability_note == (
        "Market data error 10089 for symbol=AAPL | "
        "NMS is currently closed per IB trading hours"
    )
