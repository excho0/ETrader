from __future__ import annotations

from uuid import uuid4

from ib_async import Contract, Forex, Order

from app.models.trading import InstrumentContractSpec
from app.services.products.base import ProductAdapter


class ForexProductAdapter(ProductAdapter):
    instrument_type = "forex"

    @staticmethod
    def _normalize_pair(spec: InstrumentContractSpec) -> tuple[str, str]:
        raw_symbol = spec.symbol.strip().upper()
        raw_currency = spec.currency.strip().upper()
        if len(raw_symbol) == 6:
            return raw_symbol[:3], raw_symbol[3:]
        if len(raw_symbol) != 3 or len(raw_currency) != 3:
            raise ValueError(
                "Forex contracts require symbol='EUR', currency='USD' or symbol='EURUSD'"
            )
        return raw_symbol, raw_currency

    @classmethod
    def _build_contract(cls, spec: InstrumentContractSpec) -> Forex:
        base, quote = cls._normalize_pair(spec)
        exchange = (spec.exchange or "").strip().upper() or "IDEALPRO"
        if exchange == "SMART":
            exchange = "IDEALPRO"
        return Forex(f"{base}{quote}", exchange=exchange)

    async def qualify_contract(
        self,
        client,
        spec: InstrumentContractSpec,
    ) -> Contract:
        await client.ensure_connected()
        contract = self._build_contract(spec)
        qualified = await client.ib.qualifyContractsAsync(contract)
        qualified_contracts = [item for item in qualified if item is not None]
        if not qualified_contracts:
            raise ValueError(
                f"Unable to qualify forex contract for symbol={spec.symbol} "
                f"currency={spec.currency} exchange={contract.exchange}"
            )
        return qualified_contracts[0]

    async def market_quote(
        self,
        client,
        spec: InstrumentContractSpec,
    ):
        qualified_contract = await self.qualify_contract(client, spec)
        live_ticker = await client.request_market_data(qualified_contract, market_data_type=1)
        live_errors = getattr(live_ticker, "_etrader_market_data_errors", [])
        if client.ticker_has_value(live_ticker):
            live_data_mode = client.ticker_data_mode(live_ticker)
            if live_data_mode == "live":
                return {"ticker": live_ticker, "data_mode": "live"}
            if live_data_mode == "delayed":
                return {"ticker": live_ticker, "data_mode": "delayed"}

        if not live_errors:
            raise ValueError(
                f"Live market data request returned no prices or entitlement details for "
                f"forex pair symbol={spec.symbol} currency={spec.currency} "
                f"(exchange={qualified_contract.exchange})"
            )

        delayed_ticker = await client.request_delayed_market_data_with_retry(
            qualified_contract,
            symbol=f"{qualified_contract.symbol}{qualified_contract.currency}",
        )
        return {"ticker": delayed_ticker, "data_mode": "delayed"}

    async def historical_bars(
        self,
        client,
        spec: InstrumentContractSpec,
        *,
        timeframe: str,
        duration: str,
        what_to_show: str,
        use_rth: bool,
    ) -> list[object]:
        qualified_contract = await self.qualify_contract(client, spec)
        return await client.request_historical_bars(
            qualified_contract,
            symbol=f"{qualified_contract.symbol}{qualified_contract.currency}",
            timeframe=timeframe,
            duration=duration,
            what_to_show=what_to_show,
            use_rth=use_rth,
        )

    async def place_order(
        self,
        client,
        spec: InstrumentContractSpec,
        *,
        action: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        stop_price: float | None,
        time_in_force: str,
    ):
        qualified_contract = await self.qualify_contract(client, spec)
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
        return client.ib.placeOrder(qualified_contract, order)

    async def place_bracket_order(
        self,
        client,
        spec: InstrumentContractSpec,
        *,
        action: str,
        quantity: float,
        entry_limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ):
        qualified_contract = await self.qualify_contract(client, spec)
        orders = client.ib.bracketOrder(
            action=action,
            quantity=quantity,
            limitPrice=entry_limit_price,
            takeProfitPrice=take_profit_price,
            stopLossPrice=stop_loss_price,
        )
        trades: list = []
        for order in orders:
            order.tif = time_in_force
            trades.append(client.ib.placeOrder(qualified_contract, order))
        return trades

    async def place_position_exit_oca(
        self,
        client,
        spec: InstrumentContractSpec,
        *,
        quantity: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ):
        qualified_contract = await self.qualify_contract(client, spec)
        oca_group = f"etrader-exit-{qualified_contract.symbol}{qualified_contract.currency}-{uuid4()}"

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

        take_profit_trade = client.ib.placeOrder(qualified_contract, take_profit)
        stop_loss_trade = client.ib.placeOrder(qualified_contract, stop_loss)
        return oca_group, take_profit_trade, stop_loss_trade
