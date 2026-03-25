import asyncio
import logging
import math
from typing import Literal, TypedDict
from uuid import uuid4

from ib_async import AccountValue, Contract, Fill, IB, Order, Position, Stock, Ticker, Trade

from app.core.config import Settings


class QuoteResult(TypedDict):
    ticker: Ticker
    data_mode: str


class ConnectionTarget(TypedDict):
    mode: Literal["paper", "live"]
    host: str
    port: int


class IBGatewayClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ib = IB()
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger("uvicorn.app.ib")
        self._connected_mode: Literal["paper", "live"] | None = None
        self._connected_port: int | None = None

    @property
    def ib(self) -> IB:
        return self._ib

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    @property
    def connected_mode(self) -> Literal["paper", "live"] | None:
        return self._connected_mode

    @property
    def connected_port(self) -> int | None:
        return self._connected_port

    def connection_candidates(self) -> list[ConnectionTarget]:
        if self._settings.ib_target_mode == "paper":
            modes: list[Literal["paper", "live"]] = ["paper"]
        elif self._settings.ib_target_mode == "live":
            modes = ["live"]
        else:
            fallback_mode: Literal["paper", "live"] = (
                "live" if self._settings.ib_preferred_mode == "paper" else "paper"
            )
            modes = [self._settings.ib_preferred_mode, fallback_mode]

        return [
            {
                "mode": mode,
                "host": self._settings.ib_host,
                "port": self._settings.resolved_ib_port(mode),
            }
            for mode in modes
        ]

    async def probe_socket(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        reader = None
        writer = None
        target_host = host or self._settings.ib_host
        target_port = port or self._settings.resolved_ib_port()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, target_port),
                timeout=self._settings.ib_connect_timeout_seconds,
            )
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def connect(self) -> None:
        async with self._lock:
            if self._ib.isConnected():
                return

            errors: list[str] = []
            for candidate in self.connection_candidates():
                try:
                    await self.probe_socket(
                        host=candidate["host"],
                        port=candidate["port"],
                    )
                    self._logger.info(
                        "Connecting to IB target mode=%s host=%s port=%s client_id=%s",
                        candidate["mode"],
                        candidate["host"],
                        candidate["port"],
                        self._settings.ib_client_id,
                    )
                    await self._ib.connectAsync(
                        candidate["host"],
                        candidate["port"],
                        clientId=self._settings.ib_client_id,
                        timeout=self._settings.ib_connect_timeout_seconds,
                        readonly=self._settings.ib_read_only,
                    )
                    self._connected_mode = candidate["mode"]
                    self._connected_port = candidate["port"]
                    self._logger.info(
                        "Connected to IB target mode=%s host=%s port=%s",
                        self._connected_mode,
                        candidate["host"],
                        self._connected_port,
                    )
                    return
                except Exception as exc:
                    self._connected_mode = None
                    self._connected_port = None
                    detail = f"{candidate['mode']}@{candidate['host']}:{candidate['port']} -> {exc.__class__.__name__}"
                    message = str(exc).strip()
                    if message:
                        detail = f"{detail}: {message}"
                    errors.append(detail)
                    try:
                        self._ib.disconnect()
                    except Exception:
                        pass

            raise ConnectionError(" ; ".join(errors))

    async def disconnect(self) -> None:
        async with self._lock:
            if self._ib.isConnected():
                self._ib.disconnect()
            self._connected_mode = None
            self._connected_port = None

    async def ensure_connected(self) -> None:
        if not self._ib.isConnected():
            await self.connect()

    async def managed_accounts(self) -> list[str]:
        await self.ensure_connected()
        return list(self._ib.managedAccounts())

    async def account_summary(self) -> list[AccountValue]:
        await self.ensure_connected()
        return await self._ib.accountSummaryAsync()

    async def positions(self) -> list[Position]:
        await self.ensure_connected()
        return list(self._ib.positions())

    async def open_trades(self) -> list[Trade]:
        await self.ensure_connected()
        return list(self._ib.openTrades())

    async def open_orders(self) -> list[Order]:
        await self.ensure_connected()
        return list(self._ib.openOrders())

    async def fills(self) -> list[Fill]:
        await self.ensure_connected()
        return list(self._ib.fills())

    async def qualify_stock_contract(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> Contract:
        await self.ensure_connected()
        contract = Stock(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primaryExchange=primary_exchange,
        )
        qualified = await self._ib.qualifyContractsAsync(contract)
        qualified_contracts = [item for item in qualified if item is not None]
        if not qualified_contracts:
            raise ValueError(f"Unable to qualify contract for symbol={symbol}")
        return qualified_contracts[0]

    async def stock_quote(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> QuoteResult:
        qualified_contract = await self.qualify_stock_contract(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
        live_ticker = await self._request_market_data(qualified_contract, market_data_type=1)
        if self._ticker_has_value(live_ticker):
            return {"ticker": live_ticker, "data_mode": "live"}

        delayed_ticker = await self._request_market_data(qualified_contract, market_data_type=3)
        return {"ticker": delayed_ticker, "data_mode": "delayed"}

    async def place_order(
        self,
        *,
        symbol: str,
        action: str,
        quantity: float,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
        order_type: str,
        limit_price: float | None,
        stop_price: float | None,
        time_in_force: str,
    ) -> Trade:
        qualified_contract = await self.qualify_stock_contract(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = order_type
        order.tif = time_in_force
        if order_type == "LMT":
            order.lmtPrice = limit_price
        if order_type == "STP":
            order.auxPrice = stop_price
        if order_type == "STP LMT":
            order.lmtPrice = limit_price
            order.auxPrice = stop_price
        return self._ib.placeOrder(qualified_contract, order)

    async def place_bracket_order(
        self,
        *,
        symbol: str,
        action: str,
        quantity: float,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
        entry_limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ) -> list[Trade]:
        qualified_contract = await self.qualify_stock_contract(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
        orders = self._ib.bracketOrder(
            action=action,
            quantity=quantity,
            limitPrice=entry_limit_price,
            takeProfitPrice=take_profit_price,
            stopLossPrice=stop_loss_price,
        )
        trades: list[Trade] = []
        for order in orders:
            order.tif = time_in_force
            trades.append(self._ib.placeOrder(qualified_contract, order))
        return trades

    async def place_position_exit_oca(
        self,
        *,
        symbol: str,
        quantity: float,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ) -> tuple[str, Trade, Trade]:
        qualified_contract = await self.qualify_stock_contract(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
        oca_group = f"etrader-exit-{symbol}-{uuid4()}"

        take_profit = Order()
        take_profit.action = "SELL"
        take_profit.totalQuantity = quantity
        take_profit.orderType = "LMT"
        take_profit.lmtPrice = take_profit_price
        take_profit.tif = time_in_force
        take_profit.ocaGroup = oca_group
        take_profit.ocaType = 1

        stop_loss = Order()
        stop_loss.action = "SELL"
        stop_loss.totalQuantity = quantity
        stop_loss.orderType = "STP"
        stop_loss.auxPrice = stop_loss_price
        stop_loss.tif = time_in_force
        stop_loss.ocaGroup = oca_group
        stop_loss.ocaType = 1

        tp_trade = self._ib.placeOrder(qualified_contract, take_profit)
        sl_trade = self._ib.placeOrder(qualified_contract, stop_loss)
        return oca_group, tp_trade, sl_trade

    async def cancel_order(self, *, order_id: int) -> Trade:
        await self.ensure_connected()
        for trade in self._ib.openTrades():
            if trade.order.orderId == order_id:
                return self._ib.cancelOrder(trade.order)
        raise ValueError(f"Unable to find open order_id={order_id}")

    async def replace_order(
        self,
        *,
        order_id: int,
        quantity: float | None,
        limit_price: float | None,
        stop_price: float | None,
        time_in_force: str | None,
    ) -> Trade:
        await self.ensure_connected()
        for trade in self._ib.openTrades():
            if trade.order.orderId != order_id:
                continue
            order = trade.order
            if quantity is not None:
                order.totalQuantity = quantity
            if limit_price is not None:
                order.lmtPrice = limit_price
            if stop_price is not None:
                order.auxPrice = stop_price
            if time_in_force is not None:
                order.tif = time_in_force
            return self._ib.placeOrder(trade.contract, order)
        raise ValueError(f"Unable to find open order_id={order_id}")

    async def _request_market_data(self, contract: Contract, *, market_data_type: int) -> Ticker:
        self._ib.reqMarketDataType(market_data_type)
        ticker = self._ib.reqMktData(contract, "", False, False)
        await asyncio.sleep(1.0)
        self._ib.cancelMktData(contract)
        return ticker

    @staticmethod
    def _ticker_has_value(ticker: Ticker) -> bool:
        for value in (ticker.bid, ticker.ask, ticker.last, ticker.close):
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return True
        return False
