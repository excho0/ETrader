from __future__ import annotations

from ib_async import Contract, Stock

from app.models.trading import InstrumentContractSpec
from app.services.products.base import ProductAdapter


class StockProductAdapter(ProductAdapter):
    instrument_type = "stock"

    async def qualify_contract(
        self,
        client,
        spec: InstrumentContractSpec,
    ) -> Contract:
        await client.ensure_connected()
        candidate_specs: list[dict[str, str | None]] = []

        def add_candidate(*, exch: str, primary: str | None) -> None:
            candidate = {"exchange": exch, "primaryExchange": primary}
            if candidate not in candidate_specs:
                candidate_specs.append(candidate)

        add_candidate(exch=spec.exchange, primary=spec.primary_exchange)

        if spec.currency.upper() == "USD":
            for primary in [spec.primary_exchange, "NASDAQ", "ISLAND", "NYSE", "ARCA"]:
                add_candidate(exch="SMART", primary=primary)
            for exch in ["NASDAQ", "ISLAND", "NYSE", "ARCA"]:
                add_candidate(exch=exch, primary=None)

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
        if client.ticker_has_value(live_ticker):
            return {"ticker": live_ticker, "data_mode": "live"}

        delayed_ticker = await client.request_delayed_market_data_with_retry(
            qualified_contract,
            symbol=spec.symbol,
        )
        return {"ticker": delayed_ticker, "data_mode": "delayed"}
