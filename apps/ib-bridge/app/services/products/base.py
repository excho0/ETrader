from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from ib_async import Contract, Trade

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

    async def place_order(
        self,
        client: IBGatewayClient,
        spec: InstrumentContractSpec,
        *,
        action: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        stop_price: float | None,
        time_in_force: str,
    ) -> Trade: ...

    async def place_bracket_order(
        self,
        client: IBGatewayClient,
        spec: InstrumentContractSpec,
        *,
        action: str,
        quantity: float,
        entry_limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ) -> list[Trade]: ...

    async def place_position_exit_oca(
        self,
        client: IBGatewayClient,
        spec: InstrumentContractSpec,
        *,
        quantity: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ) -> tuple[str, Trade, Trade]: ...
