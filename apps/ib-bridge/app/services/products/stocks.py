from __future__ import annotations

from uuid import uuid4

from ib_async import Contract, Order, Stock

from app.models.trading import InstrumentContractSpec
from app.services.products.base import ProductAdapter


class StockProductAdapter(ProductAdapter):
    instrument_type = "stock"

    @staticmethod
    def _candidate_specs(spec: InstrumentContractSpec) -> list[dict[str, str | None]]:
        candidate_specs: list[dict[str, str | None]] = []

        def add_candidate(*, exch: str, primary: str | None) -> None:
            candidate = {"exchange": exch, "primaryExchange": primary}
            if candidate not in candidate_specs:
                candidate_specs.append(candidate)

        # For US equities, bare SMART requests are noisy and often rejected by IB
        # without a primary exchange. Prefer qualified SMART/direct venue variants
        # first so market data calls fail with the real entitlement error instead of
        # spending cycles on invalid-contract retries.
        should_try_explicit_first = (
            spec.currency.upper() == "USD"
            and (spec.exchange.upper() == "SMART" or not spec.exchange)
            and not spec.primary_exchange
        )

        if not should_try_explicit_first:
            add_candidate(exch=spec.exchange, primary=spec.primary_exchange)

        if spec.currency.upper() == "USD":
            for primary in [spec.primary_exchange, "NASDAQ", "ISLAND", "NYSE", "ARCA"]:
                if primary:
                    add_candidate(exch="SMART", primary=primary)
            for exch in ["NASDAQ", "ISLAND", "NYSE", "ARCA"]:
                add_candidate(exch=exch, primary=None)

        if should_try_explicit_first:
            add_candidate(exch=spec.exchange, primary=spec.primary_exchange)

        return candidate_specs

    async def qualify_contract(
        self,
        client,
        spec: InstrumentContractSpec,
    ) -> Contract:
        await client.ensure_connected()
        candidate_specs = self._candidate_specs(spec)

        errors: list[str] = []
        for candidate in candidate_specs:
            contract = Stock(
                symbol=spec.symbol,
                exchange=candidate["exchange"] or spec.exchange,
                currency=spec.currency,
                primaryExchange=candidate["primaryExchange"],
            )
            try:
                qualified = await client.ib.qualifyContractsAsync(contract)
            except Exception as exc:
                errors.append(
                    f"{contract.exchange}/{getattr(contract, 'primaryExchange', None) or '-'} -> "
                    f"{exc.__class__.__name__}: {exc}"
                )
                continue

            qualified_contracts = [item for item in qualified if item is not None]
            if qualified_contracts:
                return qualified_contracts[0]

        raise ValueError(
            f"Unable to qualify contract for symbol={spec.symbol}; tried "
            + ", ".join(
                f"{candidate['exchange']}/{candidate['primaryExchange'] or '-'}"
                for candidate in candidate_specs
            )
            + (f"; errors: {' ; '.join(errors)}" if errors else "")
        )

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

        # When the initial live request returns without prices and without any IB
        # entitlement/error details, a second delayed reqMktData request can hang
        # inside the underlying client call. Fail fast with a concrete unavailable
        # state instead of letting higher layers hit long tool timeouts.
        if not live_errors:
            raise ValueError(
                f"Live market data request returned no prices or entitlement details for "
                f"symbol={spec.symbol} (exchange={qualified_contract.exchange}, "
                f"primaryExchange={getattr(qualified_contract, 'primaryExchange', None)})"
            )

        delayed_ticker = await client.request_delayed_market_data_with_retry(
            qualified_contract,
            symbol=spec.symbol,
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
            symbol=spec.symbol,
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
        oca_group = f"etrader-exit-{spec.symbol}-{uuid4()}"

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

        tp_trade = client.ib.placeOrder(qualified_contract, take_profit)
        sl_trade = client.ib.placeOrder(qualified_contract, stop_loss)
        return oca_group, tp_trade, sl_trade
