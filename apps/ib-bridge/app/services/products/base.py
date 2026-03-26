from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from ib_async import Contract

from app.models.trading import InstrumentContractSpec

if TYPE_CHECKING:
    from app.services.ib_client import IBGatewayClient, QuoteResult


class ProductAdapter(Protocol):
    instrument_type: str

    async def qualify_contract(
        self,
        client: IBGatewayClient,
        spec: InstrumentContractSpec,
    ) -> Contract: ...

    async def market_quote(
        self,
        client: IBGatewayClient,
        spec: InstrumentContractSpec,
    ) -> QuoteResult: ...
