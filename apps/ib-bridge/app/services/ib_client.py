import asyncio
import logging
import math
from typing import Literal, TypedDict
from ib_async import AccountValue, Contract, ContractDetails, Fill, IB, Order, PnL, PnLSingle, Position, Ticker, Trade

from app.core.config import Settings
from app.core.instrument_types import InstrumentType
from app.models.trading import InstrumentContractSpec
from app.services.products.registry import get_product_adapter


class QuoteResult(TypedDict):
    ticker: Ticker
    data_mode: str


class ConnectionTarget(TypedDict):
    backend: str
    mode: Literal["paper", "live"]
    host: str
    port: int


class IBGatewayClient:
    _NONFATAL_MARKET_DATA_ERROR_CODES = frozenset({200, 300, 354, 10089, 10167})
    _HISTORICAL_IP_CONFLICT_FRAGMENT = "Trading TWS session is connected from a different IP address"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ib = IB()
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger("uvicorn.app.ib")
        self._connected_mode: Literal["paper", "live"] | None = None
        self._connected_host: str | None = None
        self._connected_port: int | None = None
        self._connect_task: asyncio.Task[None] | None = None

    @property
    def ib(self) -> IB:
        return self._ib

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    @property
    def connected_mode(self) -> Literal["paper", "live"] | None:
        return self._connected_mode

    @property
    def connected_host(self) -> str | None:
        return self._connected_host

    @property
    def connected_port(self) -> int | None:
        return self._connected_port

    def _iter_backend_targets(self, mode: Literal["paper", "live"]) -> list[ConnectionTarget]:
        targets: list[ConnectionTarget] = []

        def add_target(backend: str, host: str, port: int) -> None:
            target: ConnectionTarget = {
                "backend": backend,
                "mode": mode,
                "host": host,
                "port": port,
            }
            if target not in targets:
                targets.append(target)

        add_target(
            "gateway",
            self._settings.ib_gateway_host,
            self._settings.ib_gateway_paper_port if mode == "paper" else self._settings.ib_gateway_live_port,
        )
        add_target(
            "tws",
            self._settings.ib_tws_host,
            self._settings.ib_tws_paper_port if mode == "paper" else self._settings.ib_tws_live_port,
        )
        return targets

    def connection_candidates(self) -> list[ConnectionTarget]:
        if self._settings.ib_target_mode == "paper":
            modes: list[Literal["paper", "live"]] = ["paper"]
        elif self._settings.ib_target_mode == "live":
            modes = ["live"]
        else:
            # In auto mode, once we have established a session against a specific
            # side, reconnect should prefer that same side rather than probing the
            # opposite mode on every disconnect. This keeps reconnect behavior
            # aligned with the active deployment and avoids noisy dual-port errors
            # after a paper-only gateway goes down.
            if self._connected_mode in {"paper", "live"}:
                modes = [self._connected_mode]
            else:
                fallback_mode: Literal["paper", "live"] = (
                    "live" if self._settings.ib_preferred_mode == "paper" else "paper"
                )
                modes = [self._settings.ib_preferred_mode, fallback_mode]

        return [candidate for mode in modes for candidate in self._iter_backend_targets(mode)]

    async def probe_socket(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        reader = None
        writer = None
        if host is None or port is None:
            raise ValueError("probe_socket requires explicit host and port")
        target_host = host
        target_port = port
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, target_port),
                timeout=self._settings.ib_connect_timeout_seconds,
            )
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def _connect_once(self) -> None:
        errors: list[str] = []
        candidates = self.connection_candidates()
        primary_mode = candidates[0]["mode"] if candidates else None
        for candidate in candidates:
            try:
                await self.probe_socket(
                    host=candidate["host"],
                    port=candidate["port"],
                )
                self._logger.info(
                    "Connecting to IB target backend=%s mode=%s host=%s port=%s client_id=%s",
                    candidate["backend"],
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
                self._connected_host = candidate["host"]
                self._connected_mode = candidate["mode"]
                self._connected_port = candidate["port"]
                self._logger.info(
                    "Connected to IB target backend=%s mode=%s host=%s port=%s",
                    candidate["backend"],
                    self._connected_mode,
                    candidate["host"],
                    self._connected_port,
                )
                return
            except Exception as exc:
                self._connected_host = None
                self._connected_mode = None
                self._connected_port = None
                detail = (
                    f"{candidate['backend']}:{candidate['mode']}"
                    f"@{candidate['host']}:{candidate['port']} -> {exc.__class__.__name__}"
                )
                message = str(exc).strip()
                if message:
                    detail = f"{detail}: {message}"
                errors.append(detail)
                try:
                    self._ib.disconnect()
                except Exception:
                    pass
                # In auto mode, a timeout on the primary candidate usually
                # means the selected gateway side is still booting and not
                # API-ready yet. Falling through to the opposite side just
                # adds noise and delays the next retry.
                if (
                    self._settings.ib_target_mode == "auto"
                    and primary_mode is not None
                    and candidate["mode"] == primary_mode
                    and isinstance(exc, TimeoutError)
                ):
                    break

        raise ConnectionError(" ; ".join(errors))

    async def connect(self) -> None:
        if self._ib.isConnected():
            return

        async with self._lock:
            if self._ib.isConnected():
                return
            connect_task = self._connect_task
            if connect_task is None:
                connect_task = asyncio.create_task(self._connect_once())
                self._connect_task = connect_task

        try:
            await asyncio.shield(connect_task)
        finally:
            async with self._lock:
                if self._connect_task is connect_task and connect_task.done():
                    self._connect_task = None

    async def disconnect(self) -> None:
        async with self._lock:
            connect_task = self._connect_task
            self._connect_task = None
        if connect_task is not None and not connect_task.done():
            connect_task.cancel()
            try:
                await connect_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        async with self._lock:
            if self._ib.isConnected():
                self._ib.disconnect()
            self._connected_host = None
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

    async def account_pnl(self, *, account: str, model_code: str = "") -> PnL:
        await self.ensure_connected()
        existing = self._ib.pnl(account, model_code)
        pnl = existing[0] if existing else self._ib.reqPnL(account, model_code)
        await asyncio.sleep(0.25)
        return pnl

    async def symbol_pnl_single(self, *, account: str, model_code: str, con_id: int) -> PnLSingle:
        await self.ensure_connected()
        existing = self._ib.pnlSingle(account, model_code, con_id)
        pnl = existing[0] if existing else self._ib.reqPnLSingle(account, model_code, con_id)
        await asyncio.sleep(0.25)
        return pnl

    async def pnl_subscriptions(self) -> tuple[list[PnL], list[PnLSingle]]:
        await self.ensure_connected()
        return list(self._ib.pnl()), list(self._ib.pnlSingle())

    async def qualify_stock_contract(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> Contract:
        return await self.qualify_contract(
            InstrumentContractSpec(
                instrument_type="stock",
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            )
        )

    async def stock_quote(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> QuoteResult:
        return await self.market_quote(
            InstrumentContractSpec(
                instrument_type="stock",
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            )
        )

    async def market_quote(self, spec: InstrumentContractSpec) -> QuoteResult:
        return await get_product_adapter(spec.instrument_type).market_quote(self, spec)

    async def historical_bars(
        self,
        spec: InstrumentContractSpec,
        *,
        timeframe: str,
        duration: str,
        what_to_show: str,
        use_rth: bool,
    ) -> list[object]:
        return await get_product_adapter(spec.instrument_type).historical_bars(
            self,
            spec,
            timeframe=timeframe,
            duration=duration,
            what_to_show=what_to_show,
            use_rth=use_rth,
        )

    async def contract_details(self, contract: Contract) -> ContractDetails | None:
        await self.ensure_connected()
        details = await self._ib.reqContractDetailsAsync(contract)
        if not details:
            return None
        return details[0]

    async def request_historical_bars(
        self,
        contract: Contract,
        *,
        symbol: str,
        timeframe: str,
        duration: str,
        what_to_show: str,
        use_rth: bool,
    ) -> list[object]:
        await self.ensure_connected()
        symbol = getattr(contract, "symbol", None) or symbol or "?"
        exchange = getattr(contract, "exchange", None) or "?"
        primary_exchange = getattr(contract, "primaryExchange", None)

        async def fetch(*, market_data_type: int) -> list[object]:
            captured_errors: list[tuple[int, str]] = []

            def on_error(
                event_req_id: int,
                error_code: int,
                error_string: str,
                _contract: Contract | None,
            ) -> None:
                if error_code != 162:
                    return
                self._logger.warning(
                    "Historical bars event error symbol=%s exchange=%s primary_exchange=%s req_id=%s code=%s message=%s",
                    symbol,
                    exchange,
                    primary_exchange,
                    event_req_id,
                    error_code,
                    error_string,
                )
                captured_errors.append((error_code, error_string))

            self._logger.info(
                "Requesting historical bars symbol=%s exchange=%s primary_exchange=%s market_data_type=%s timeframe=%s duration=%s what_to_show=%s use_rth=%s",
                symbol,
                exchange,
                primary_exchange,
                market_data_type,
                timeframe,
                duration,
                what_to_show,
                use_rth,
            )
            self._ib.reqMarketDataType(market_data_type)
            self._ib.errorEvent.connect(on_error)
            try:
                bars = await self._ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=timeframe,
                    whatToShow=what_to_show,
                    useRTH=use_rth,
                    formatDate=1,
                    keepUpToDate=False,
                    timeout=self._settings.ib_request_timeout_seconds,
                )
            finally:
                self._ib.errorEvent.disconnect(on_error)
            normalized = list(bars or [])
            self._logger.info(
                "Historical bars response symbol=%s exchange=%s primary_exchange=%s market_data_type=%s bar_count=%s",
                symbol,
                exchange,
                primary_exchange,
                market_data_type,
                len(normalized),
            )
            if not normalized:
                for _, error_string in captured_errors:
                    if self._HISTORICAL_IP_CONFLICT_FRAGMENT in error_string:
                        raise RuntimeError(error_string)
            return normalized

        try:
            bars = await fetch(market_data_type=1)
        except Exception as exc:
            self._logger.warning(
                "Live historical bars failed symbol=%s exchange=%s primary_exchange=%s timeframe=%s duration=%s error=%s",
                symbol,
                exchange,
                primary_exchange,
                timeframe,
                duration,
                exc,
            )
            try:
                bars = await fetch(market_data_type=3)
            except Exception as delayed_exc:
                raise ValueError(
                    f"Unable to load historical bars for symbol={symbol} "
                    f"(exchange={exchange}, primaryExchange={primary_exchange}); "
                    f"live_error={exc}; delayed_error={delayed_exc}"
                ) from delayed_exc

        if bars:
            return bars

        self._logger.warning(
            "Live historical bars returned empty symbol=%s exchange=%s primary_exchange=%s timeframe=%s duration=%s; retrying delayed mode",
            symbol,
            exchange,
            primary_exchange,
            timeframe,
            duration,
        )

        try:
            delayed_bars = await fetch(market_data_type=3)
        except Exception as exc:
            raise ValueError(
                f"Unable to load delayed historical bars for symbol={symbol} "
                f"(exchange={exchange}, primaryExchange={primary_exchange}): {exc}"
            ) from exc

        if delayed_bars:
            return delayed_bars

        raise ValueError(
            f"Historical bar request returned no usable bars for symbol={symbol} "
            f"(exchange={exchange}, primaryExchange={primary_exchange}) in live or delayed mode"
        )

    async def place_order(
        self,
        *,
        instrument_type: InstrumentType = InstrumentType.STOCK,
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
        return await get_product_adapter(instrument_type).place_order(
            self,
            InstrumentContractSpec(
                instrument_type=instrument_type,
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            ),
            action=action,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
        )

    async def place_bracket_order(
        self,
        *,
        instrument_type: InstrumentType = InstrumentType.STOCK,
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
        return await get_product_adapter(instrument_type).place_bracket_order(
            self,
            InstrumentContractSpec(
                instrument_type=instrument_type,
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            ),
            action=action,
            quantity=quantity,
            entry_limit_price=entry_limit_price,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            time_in_force=time_in_force,
        )

    async def place_position_exit_oca(
        self,
        *,
        instrument_type: InstrumentType = InstrumentType.STOCK,
        symbol: str,
        quantity: float,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str,
    ) -> tuple[str, Trade, Trade]:
        return await get_product_adapter(instrument_type).place_position_exit_oca(
            self,
            InstrumentContractSpec(
                instrument_type=instrument_type,
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            ),
            quantity=quantity,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            time_in_force=time_in_force,
        )

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

    async def request_market_data(self, contract: Contract, *, market_data_type: int) -> Ticker:
        await self.ensure_connected()
        symbol = getattr(contract, "symbol", None) or "?"
        exchange = getattr(contract, "exchange", None) or "?"
        primary_exchange = getattr(contract, "primaryExchange", None)
        self._logger.info(
            "Requesting market data symbol=%s exchange=%s primary_exchange=%s market_data_type=%s",
            symbol,
            exchange,
            primary_exchange,
            market_data_type,
        )
        self._ib.reqMarketDataType(market_data_type)
        try:
            ticker = self._ib.reqMktData(contract, "", False, False)
        except Exception as exc:
            self._logger.exception(
                "reqMktData failed symbol=%s exchange=%s primary_exchange=%s market_data_type=%s",
                symbol,
                exchange,
                primary_exchange,
                market_data_type,
            )
            raise
        req_id = self._ib.wrapper.ticker2ReqId.get("mktData", {}).get(ticker)
        captured_errors: list[tuple[int, str]] = []

        def on_error(event_req_id: int, error_code: int, error_string: str, _contract: Contract | None):
            if event_req_id != req_id:
                return
            self._logger.warning(
                "Market data event error symbol=%s exchange=%s primary_exchange=%s req_id=%s code=%s message=%s",
                symbol,
                exchange,
                primary_exchange,
                req_id,
                error_code,
                error_string,
            )
            captured_errors.append((error_code, error_string))

        self._ib.errorEvent.connect(on_error)
        deadline = asyncio.get_running_loop().time() + self._settings.ib_market_data_timeout_seconds
        try:
            while True:
                if self.ticker_has_value(ticker):
                    self._logger.info(
                        "Market data resolved symbol=%s exchange=%s primary_exchange=%s req_id=%s market_data_type=%s data_mode=%s bid=%s ask=%s last=%s close=%s",
                        symbol,
                        exchange,
                        primary_exchange,
                        req_id,
                        market_data_type,
                        self.ticker_data_mode(ticker),
                        ticker.bid,
                        ticker.ask,
                        ticker.last,
                        ticker.close,
                    )
                    return ticker

                if captured_errors:
                    setattr(ticker, "_etrader_market_data_errors", list(captured_errors))
                    if any(code in self._NONFATAL_MARKET_DATA_ERROR_CODES for code, _ in captured_errors):
                        self._logger.info(
                            "Market data returning after nonfatal error symbol=%s exchange=%s primary_exchange=%s req_id=%s market_data_type=%s errors=%s",
                            symbol,
                            exchange,
                            primary_exchange,
                            req_id,
                            market_data_type,
                            captured_errors,
                        )
                        return ticker

                if asyncio.get_running_loop().time() >= deadline:
                    if captured_errors:
                        setattr(ticker, "_etrader_market_data_errors", list(captured_errors))
                    self._logger.warning(
                        "Market data timed out symbol=%s exchange=%s primary_exchange=%s req_id=%s market_data_type=%s errors=%s bid=%s ask=%s last=%s close=%s",
                        symbol,
                        exchange,
                        primary_exchange,
                        req_id,
                        market_data_type,
                        captured_errors,
                        ticker.bid,
                        ticker.ask,
                        ticker.last,
                        ticker.close,
                    )
                    return ticker

                await asyncio.sleep(0.2)
        finally:
            self._ib.errorEvent.disconnect(on_error)
            try:
                self._ib.cancelMktData(contract)
            except Exception:
                self._logger.exception(
                    "cancelMktData failed symbol=%s exchange=%s primary_exchange=%s req_id=%s",
                    symbol,
                    exchange,
                    primary_exchange,
                    req_id,
                )

    async def request_delayed_market_data_with_retry(
        self,
        contract: Contract,
        *,
        symbol: str,
        attempts: int = 3,
        backoff_seconds: float = 0.35,
    ) -> Ticker:
        last_ticker: Ticker | None = None
        for attempt in range(1, attempts + 1):
            self._logger.info(
                "Requesting delayed market data attempt symbol=%s exchange=%s primary_exchange=%s attempt=%s/%s",
                symbol,
                contract.exchange,
                getattr(contract, "primaryExchange", None),
                attempt,
                attempts,
            )
            last_ticker = await self.request_market_data(contract, market_data_type=3)
            if self.ticker_has_value(last_ticker):
                if attempt > 1:
                    self._logger.info(
                        "Recovered delayed market data for symbol=%s on retry %s/%s",
                        symbol,
                        attempt,
                        attempts,
                    )
                return last_ticker
            captured_errors = getattr(last_ticker, "_etrader_market_data_errors", [])
            if captured_errors:
                code, message = captured_errors[-1]
                raise ValueError(
                    f"Market data error {code} for symbol={symbol} "
                    f"(exchange={contract.exchange}, primaryExchange={getattr(contract, 'primaryExchange', None)}): "
                    f"{message}"
                )
            if attempt < attempts:
                self._logger.warning(
                    "Empty delayed market data for symbol=%s on attempt %s/%s; retrying",
                    symbol,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(backoff_seconds * attempt)

        raise ValueError(
            f"Market data returned no usable prices for symbol={symbol} "
            f"(exchange={contract.exchange}, primaryExchange={getattr(contract, 'primaryExchange', None)})"
        )

    @staticmethod
    def ticker_has_value(ticker: Ticker) -> bool:
        for value in (ticker.bid, ticker.ask, ticker.last, ticker.close):
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return True
        return False

    @staticmethod
    def ticker_data_mode(ticker: Ticker) -> str:
        market_data_type = getattr(ticker, "marketDataType", None)
        if market_data_type == 1:
            return "live"
        if market_data_type in {2, 3, 4}:
            return "delayed"
        return "unknown"

    async def qualify_contract(self, spec: InstrumentContractSpec) -> Contract:
        return await get_product_adapter(spec.instrument_type).qualify_contract(self, spec)
