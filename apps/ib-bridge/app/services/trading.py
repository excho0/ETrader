from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from peewee import ModelSelect
from pydantic import BaseModel

from app.core.config import Settings
from app.core.instrument_types import InstrumentType
from app.db import (
    ApprovalMandateStore,
    AuditEventRecord,
    IdempotencyRecord,
    OrderLifecycleRecord,
    PositionSnapshotRecord,
    dump_json,
    initialize_database,
)
from app.core.errors import TradingConnectionError, TradingValidationError
from app.models.health import ReadinessResponse
from app.models.trading import (
    AccountRiskSnapshotResponse,
    AccountPnLResponse,
    AccountSummaryResponse,
    AccountValue,
    ApprovalDecisionRequest,
    ApprovalMandateRequest,
    ApprovalMandateResponse,
    AuditBehaviorBreakdownItem,
    AuditBehaviorSummaryResponse,
    AuditEventResponse,
    CashSizingRequest,
    CashSizingResponse,
    CancelAllOrdersResponse,
    ClosePositionRequest,
    ConnectivityProbeResponse,
    ExecutionGuardrailsResponse,
    ExecutionReportResponse,
    ExecutionQualityResponse,
    HistoricalBarResponse,
    HistoricalBarsResponse,
    HistoricalNewsRequest,
    HistoricalNewsResponse,
    InstrumentContractSpec,
    LevelMapResponse,
    MarketQuoteResponse,
    MarketSnapshotResponse,
    MarketSessionStatusResponse,
    MultiTimeframeBarsResponse,
    NewsArticleResponse,
    NewsProvidersResponse,
    OpenOrderResponse,
    OpenPositionRequest,
    OrderAdvisorResponse,
    OrderCancellationResponse,
    OrderLifecycleEventResponse,
    OrderStatusResponse,
    OrderPreviewRequest,
    OrderPreviewResponse,
    OrderReplaceRequest,
    OrderSubmissionResponse,
    PolicyProfileResponse,
    PortfolioRiskItem,
    PortfolioRiskSnapshotResponse,
    PnLSubscriptionItem,
    PnLSubscriptionsResponse,
    PositionExitOcaRequest,
    PositionSnapshotResponse,
    PositionActionPlanResponse,
    PositionResponse,
    SymbolPnLResponse,
    QualifiedContractResponse,
    QualifiedStockContractResponse,
    ReducePositionRequest,
    BrokerReconciliationResponse,
    SupportedInstrumentTypesResponse,
    SymbolConflictResponse,
    SymbolExposureResponse,
    TradeCandidateEvaluationResponse,
)
from app.services.news.registry import get_news_adapter
from app.services.products.registry import list_supported_instrument_types
if TYPE_CHECKING:
    from ib_async import AccountValue as BrokerAccountValue
    from ib_async import ContractDetails
    from ib_async import Position as BrokerPosition
    from ib_async import Trade

    from app.services.ib_client import IBGatewayClient


@dataclass
class PolicyProfile:
    name: str
    max_trade_notional: float
    max_position_notional: float
    max_symbol_concentration_pct: float
    max_daily_new_exposure: float
    max_open_orders_per_symbol: int
    block_delayed_market_orders: bool
    max_market_spread_bps: float
    require_limit_for_wide_spread: bool
    wide_spread_bps: float
    require_approval_for_all: bool
    approval_trade_notional: float


@dataclass
class ApprovalMandate:
    mandate_id: str
    status: str
    created_at: datetime
    expires_at: datetime
    instrument_type: InstrumentType
    target_mode: str
    symbols: list[str]
    actions: list[str]
    max_order_notional: float
    max_uses: int
    uses_consumed: int
    note: str | None = None
    requester: str | None = None
    approved_by: str | None = None
    request: OrderPreviewRequest | None = None
    policy_decision: str | None = None
    approval_required: bool | None = None
    guardrails: ExecutionGuardrailsResponse | None = None
    request_context: dict[str, object] = field(default_factory=dict)


@dataclass
class TradingRuntime:
    approval_mandates: dict[str, ApprovalMandate] = field(default_factory=dict)
    recent_policy_blocks: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    reconnect_state: str | None = None
    last_broker_sync_at: datetime | None = None
    approval_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    idempotency_records: dict[str, OrderSubmissionResponse] = field(default_factory=dict)
    pending_request_ids: set[str] = field(default_factory=set)
    idempotency_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    audit_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active_database_mode: Literal["paper", "live"] | None = None
    active_database_path: str | None = None


@dataclass
class ReadCacheEntry:
    value: Any
    expires_at: datetime


_RUNTIME = TradingRuntime()


def _model_payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json")


def _json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


class _NullIBGatewayClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.connected_mode: Literal["paper", "live"] | None = None
        self.connected_port: int | None = None

    def is_connected(self) -> bool:
        return False

    async def ensure_connected(self) -> None:
        return None

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        self.connected_mode = None
        self.connected_port = None

    async def probe_socket(self, *, host: str | None = None, port: int | None = None) -> None:
        return None

    async def managed_accounts(self) -> list[str]:
        return []

    async def account_pnl(self, *, account: str, model_code: str = ""):
        raise TradingConnectionError("IB client is not available in test mode")

    async def symbol_pnl_single(self, *, account: str, model_code: str, con_id: int):
        raise TradingConnectionError("IB client is not available in test mode")

    async def pnl_subscriptions(self):
        return [], []

    async def news_providers(self):
        raise TradingConnectionError("IB client is not available in test mode")

    async def historical_news(
        self,
        *,
        con_id: int,
        provider_codes: list[str],
        start_date_time: str,
        end_date_time: str,
        total_results: int,
    ):
        raise TradingConnectionError("IB client is not available in test mode")

    async def news_article(self, *, provider_code: str, article_id: str):
        raise TradingConnectionError("IB client is not available in test mode")


class TradingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if settings.env == "test":
            self._client = _NullIBGatewayClient(settings)
        else:
            from app.services.ib_client import IBGatewayClient

            self._client = IBGatewayClient(settings)
        self._request_lock = asyncio.Lock()
        self._logger = logging.getLogger("uvicorn.app.trading")
        self._audit_logger = logging.getLogger("uvicorn.app.audit")
        self._reconnect_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._runtime = _RUNTIME
        self._read_cache: dict[str, ReadCacheEntry] = {}
        self._read_inflight: dict[str, asyncio.Task[Any]] = {}
        self._read_cache_lock = asyncio.Lock()

    async def startup(self) -> None:
        initial_mode = self._settings.resolved_database_mode()
        initialize_database(self._settings.resolved_database_path(initial_mode))
        self._runtime.active_database_mode = initial_mode
        self._runtime.active_database_path = self._settings.resolved_database_path(initial_mode)
        self._load_persistent_state()
        if self._settings.auto_connect_on_startup:
            try:
                await self.ensure_connected()
            except TradingConnectionError as exc:
                self._log_reconnect_state(
                    "startup_degraded",
                    "IB auto-connect on startup failed; service will stay up in degraded mode: %s",
                    exc.message,
                )
        if self._settings.ib_auto_reconnect:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def shutdown(self) -> None:
        self._shutdown_event.set()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        await self.disconnect()

    async def ensure_connected(self) -> None:
        try:
            await self._client.ensure_connected()
            self._sync_database_binding()
            self._runtime.last_broker_sync_at = datetime.now(UTC)
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            raise TradingConnectionError(f"Unable to connect to IB Gateway: {detail}") from exc

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def probe(self) -> ConnectivityProbeResponse:
        tcp_reachable = False
        ib_connected = self._client.is_connected()
        handshake_error: str | None = None
        candidates = self._client.connection_candidates()
        if not candidates:
            raise TradingConnectionError("No IB connection candidates are configured")
        probe_target = candidates[0]
        probe_host = self._client.connected_host or probe_target["host"]
        probe_port = self._client.connected_port or probe_target["port"]

        try:
            await self._client.probe_socket(
                host=probe_host,
                port=probe_port,
            )
            tcp_reachable = True
        except Exception as exc:
            handshake_error = f"tcp_probe_failed: {self._format_exception_detail(exc)}"
            return ConnectivityProbeResponse(
                host=probe_host,
                port=probe_port,
                client_id=self._settings.ib_client_id,
                tcp_reachable=tcp_reachable,
                ib_connected=ib_connected,
                handshake_error=handshake_error,
            )

        try:
            await self._client.connect()
            ib_connected = self._client.is_connected()
        except Exception as exc:
            handshake_error = self._format_exception_detail(exc)

        return ConnectivityProbeResponse(
            host=probe_host,
            port=probe_port,
            client_id=self._settings.ib_client_id,
            tcp_reachable=tcp_reachable,
            ib_connected=ib_connected,
            handshake_error=handshake_error,
        )

    async def readiness(self) -> ReadinessResponse:
        connected = self._client.is_connected()
        accounts: list[str] = []
        if not connected:
            try:
                await self.ensure_connected()
            except Exception:
                connected = self._client.is_connected()
            else:
                connected = self._client.is_connected()

        if connected:
            try:
                accounts = await self._client.managed_accounts()
            except Exception as exc:
                self._logger.warning("Readiness check connected but managed_accounts failed: %s", exc)

        status = "ready" if connected else "degraded"
        return ReadinessResponse(
            status=status,
            connected=connected,
            target_mode=self._settings.ib_target_mode,
            connected_mode=self._client.connected_mode,
            host=self._client.connected_host or self._client.connection_candidates()[0]["host"],
            port=self._client.connected_port or self._client.connection_candidates()[0]["port"],
            client_id=self._settings.ib_client_id,
            managed_accounts=accounts,
            reconnect_state=self._runtime.reconnect_state,
            reconnect_interval_seconds=self._settings.ib_reconnect_interval_seconds,
            approval_queue_count=self._approval_queue_count(),
            recent_policy_blocks=list(self._runtime.recent_policy_blocks),
        )

    def _sync_database_binding(self) -> None:
        mode = self._client.connected_mode
        if mode not in {"paper", "live"}:
            return
        target_path = self._settings.resolved_database_path(mode)
        if self._runtime.active_database_mode == mode and self._runtime.active_database_path == target_path:
            return
        initialize_database(target_path)
        self._runtime.active_database_mode = mode
        self._runtime.active_database_path = target_path
        self._load_persistent_state()
        self._logger.info("Switched trading persistence to mode=%s db=%s", mode, target_path)

    async def _reconnect_loop(self) -> None:
        delay = self._settings.ib_reconnect_interval_seconds
        while not self._shutdown_event.is_set():
            try:
                if not self._client.is_connected():
                    if self._runtime.reconnect_state not in {"startup_degraded", "disconnected", "retry_failed"}:
                        self._log_reconnect_state("disconnected", "IB bridge disconnected; attempting reconnect")
                    await self.ensure_connected()
                    self._log_reconnect_state(
                        "reconnected",
                        "IB reconnect successful mode=%s port=%s",
                        self._client.connected_mode,
                        self._client.connected_port,
                    )
                    delay = self._settings.ib_reconnect_interval_seconds
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_reconnect_state(
                    "retry_failed",
                    "IB reconnect attempt failed: %s; next retry in %.1fs",
                    self._format_exception_detail(exc),
                    self._settings.ib_reconnect_interval_seconds,
                )
                delay = self._settings.ib_reconnect_interval_seconds
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    continue

    def _log_reconnect_state(self, state: str, message: str, *args: object) -> None:
        if self._runtime.reconnect_state == state:
            return
        self._runtime.reconnect_state = state
        if state == "reconnected":
            self._logger.info(message, *args)
        else:
            self._logger.warning(message, *args)

    async def _cached_read(
        self,
        key: str,
        ttl_seconds: float,
        factory: Callable[[], Any],
    ) -> Any:
        now = datetime.now(UTC)
        async with self._read_cache_lock:
            cached = self._read_cache.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.value
            inflight = self._read_inflight.get(key)
            if inflight is None:
                async def runner() -> Any:
                    result = factory()
                    if asyncio.iscoroutine(result):
                        return await result
                    return result

                inflight = asyncio.create_task(runner())
                self._read_inflight[key] = inflight

        try:
            value = await inflight
        except BaseException:
            async with self._read_cache_lock:
                current = self._read_inflight.get(key)
                if current is inflight:
                    self._read_inflight.pop(key, None)
            raise

        async with self._read_cache_lock:
            self._read_cache[key] = ReadCacheEntry(
                value=value,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            current = self._read_inflight.get(key)
            if current is inflight:
                self._read_inflight.pop(key, None)
        return value

    async def get_account_summary(self) -> AccountSummaryResponse:
        async def factory() -> AccountSummaryResponse:
            async with self._request_lock:
                summary = await self._client.account_summary()
                return AccountSummaryResponse(
                    account_values=[
                        AccountValue(tag=item.tag, value=item.value, currency=item.currency, account=item.account)
                        for item in summary
                    ]
                )

        return cast(AccountSummaryResponse, await self._cached_read("account_summary", 2.0, factory))

    async def get_account_pnl(self, *, account: str | None = None, model_code: str = "") -> AccountPnLResponse:
        async with self._request_lock:
            resolved_account = account
            if not resolved_account:
                summary = await self._client.account_summary()
                resolved_account = self._preferred_account(summary)
            if not resolved_account:
                raise TradingValidationError("Unable to determine IB account for P&L subscription")
            pnl = await self._client.account_pnl(account=resolved_account, model_code=model_code)
            return AccountPnLResponse(
                account=str(getattr(pnl, "account", None) or resolved_account),
                model_code=str(getattr(pnl, "modelCode", None) or model_code),
                daily_pnl=self._normalize_optional_float(getattr(pnl, "dailyPnL", None)),
                unrealized_pnl=self._normalize_optional_float(getattr(pnl, "unrealizedPnL", None)),
                realized_pnl=self._normalize_optional_float(getattr(pnl, "realizedPnL", None)),
            )

    async def get_symbol_pnl(
        self,
        spec: InstrumentContractSpec,
        *,
        account: str | None = None,
        model_code: str = "",
    ) -> SymbolPnLResponse:
        async with self._request_lock:
            resolved_account = account
            if not resolved_account:
                summary = await self._client.account_summary()
                resolved_account = self._preferred_account(summary)
            if not resolved_account:
                raise TradingValidationError("Unable to determine IB account for symbol P&L subscription")
            contract = await self._client.qualify_contract(spec)
            pnl = await self._client.symbol_pnl_single(
                account=resolved_account,
                model_code=model_code,
                con_id=int(contract.conId),
            )
            return SymbolPnLResponse(
                instrument_type=spec.instrument_type,
                account=str(getattr(pnl, "account", None) or resolved_account),
                model_code=str(getattr(pnl, "modelCode", None) or model_code),
                con_id=int(getattr(pnl, "conId", None) or contract.conId),
                symbol=contract.symbol,
                exchange=contract.exchange,
                currency=contract.currency,
                primary_exchange=getattr(contract, "primaryExchange", None),
                daily_pnl=self._normalize_optional_float(getattr(pnl, "dailyPnL", None)),
                unrealized_pnl=self._normalize_optional_float(getattr(pnl, "unrealizedPnL", None)),
                realized_pnl=self._normalize_optional_float(getattr(pnl, "realizedPnL", None)),
                position=self._normalize_optional_float(getattr(pnl, "position", None)),
                value=self._normalize_optional_float(getattr(pnl, "value", None)),
            )

    async def get_pnl_subscriptions(self) -> PnLSubscriptionsResponse:
        async with self._request_lock:
            account_pnls, symbol_pnls = await self._client.pnl_subscriptions()
            subscriptions: list[PnLSubscriptionItem] = []
            subscriptions.extend(
                PnLSubscriptionItem(
                    kind="account",
                    account=str(getattr(pnl, "account", "")),
                    model_code=str(getattr(pnl, "modelCode", "") or ""),
                    con_id=None,
                )
                for pnl in account_pnls
            )
            subscriptions.extend(
                PnLSubscriptionItem(
                    kind="symbol",
                    account=str(getattr(pnl, "account", "")),
                    model_code=str(getattr(pnl, "modelCode", "") or ""),
                    con_id=int(getattr(pnl, "conId", 0) or 0),
                )
                for pnl in symbol_pnls
            )
            return PnLSubscriptionsResponse(subscriptions=subscriptions)

    async def get_supported_instrument_types(self) -> SupportedInstrumentTypesResponse:
        return SupportedInstrumentTypesResponse(
            supported_instrument_types=list_supported_instrument_types(),
            default_instrument_type=InstrumentType.STOCK,
            generic_tools_preferred=True,
            compatibility_wrappers={
                "stock": [
                    "trading_qualify_stock_contract",
                    "trading_stock_quote",
                    "trading_market_snapshot",
                ]
            },
        )

    async def get_news_providers(self, *, source: str = "ib") -> NewsProvidersResponse:
        async def factory() -> NewsProvidersResponse:
            async with self._request_lock:
                adapter = get_news_adapter(source)
                return await adapter.list_providers(self._client)

        return cast(NewsProvidersResponse, await self._cached_read(f"news_providers:{source}", 30.0, factory))

    async def get_historical_news(
        self,
        request: HistoricalNewsRequest,
        *,
        source: str = "ib",
    ) -> HistoricalNewsResponse:
        cache_key = (
            f"historical_news:{source}:{request.instrument_type}:{request.symbol}:{request.exchange}:"
            f"{request.currency}:{request.primary_exchange or '-'}:{'+'.join(request.provider_codes)}:"
            f"{request.start_date_time}:{request.end_date_time}:{request.total_results}"
        )

        async def factory() -> HistoricalNewsResponse:
            async with self._request_lock:
                adapter = get_news_adapter(source)
                return await adapter.get_historical_news(self._client, request)

        return cast(HistoricalNewsResponse, await self._cached_read(cache_key, 15.0, factory))

    async def get_news_article(
        self,
        *,
        provider_code: str,
        article_id: str,
        source: str = "ib",
    ) -> NewsArticleResponse:
        cache_key = f"news_article:{source}:{provider_code}:{article_id}"

        async def factory() -> NewsArticleResponse:
            async with self._request_lock:
                adapter = get_news_adapter(source)
                return await adapter.get_article(
                    self._client,
                    provider_code=provider_code,
                    article_id=article_id,
                )

        return cast(NewsArticleResponse, await self._cached_read(cache_key, 300.0, factory))

    async def get_policy_profile(self) -> PolicyProfileResponse:
        profile = self._policy_profile()
        return PolicyProfileResponse(
            policy_mode=profile.name,
            connected_mode=self._client.connected_mode,
            target_mode=self._settings.ib_target_mode,
            max_trade_notional=profile.max_trade_notional,
            max_position_notional=profile.max_position_notional,
            max_symbol_concentration_pct=profile.max_symbol_concentration_pct,
            max_daily_new_exposure=profile.max_daily_new_exposure,
            max_open_orders_per_symbol=profile.max_open_orders_per_symbol,
            block_delayed_market_orders=profile.block_delayed_market_orders,
            max_market_spread_bps=profile.max_market_spread_bps,
            require_limit_for_wide_spread=profile.require_limit_for_wide_spread,
            wide_spread_bps=profile.wide_spread_bps,
            require_approval_for_all=profile.require_approval_for_all,
            approval_trade_notional=profile.approval_trade_notional,
            paper_order_submission_enabled=self._settings.allow_paper_orders,
            live_order_submission_enabled=self._settings.allow_live_orders,
        )

    async def get_positions(self) -> list[PositionResponse]:
        async def factory() -> list[PositionResponse]:
            async with self._request_lock:
                positions = await self._client.positions()
                responses = [
                    PositionResponse(
                        instrument_type=self._instrument_type_from_contract(item.contract),
                        account=item.account,
                        symbol=item.contract.symbol,
                        exchange=item.contract.exchange,
                        currency=item.contract.currency,
                        position=float(item.position),
                        average_cost=float(item.avgCost),
                    )
                    for item in positions
                ]
                for response in responses:
                    self._record_position_snapshot(response, source="broker_positions")
                return responses

        return cast(list[PositionResponse], await self._cached_read("positions", 2.0, factory))

    async def get_open_orders(self) -> list[OpenOrderResponse]:
        async def factory() -> list[OpenOrderResponse]:
            async with self._request_lock:
                trades = await self._client.open_trades()
                return [self._open_order_response(trade) for trade in trades]

        return cast(list[OpenOrderResponse], await self._cached_read("open_orders", 2.0, factory))

    async def get_recent_executions(self) -> list[ExecutionReportResponse]:
        async with self._request_lock:
            fills = await self._client.fills()
            reports: list[ExecutionReportResponse] = []
            for fill in fills[-25:]:
                reports.append(
                    ExecutionReportResponse(
                        instrument_type=self._instrument_type_from_contract(fill.contract),
                        symbol=fill.contract.symbol,
                        side=fill.execution.side,
                        shares=float(fill.execution.shares),
                        price=float(fill.execution.price),
                        time=str(fill.execution.time),
                        order_id=str(fill.execution.orderId) if fill.execution.orderId is not None else None,
                        perm_id=str(fill.execution.permId) if fill.execution.permId is not None else None,
                    )
                )
                self._record_order_lifecycle(
                    order_id=str(fill.execution.orderId) if fill.execution.orderId is not None else "unknown",
                    source_event_type="broker_fill",
                    symbol=fill.contract.symbol,
                    action=_normalize_fill_side(fill.execution.side),
                    quantity=float(fill.execution.shares),
                    latest_status="Filled",
                    payload={
                        "symbol": fill.contract.symbol,
                        "side": fill.execution.side,
                        "shares": float(fill.execution.shares),
                        "price": float(fill.execution.price),
                        "time": str(fill.execution.time),
                        "order_id": str(fill.execution.orderId) if fill.execution.orderId is not None else None,
                        "perm_id": str(fill.execution.permId) if fill.execution.permId is not None else None,
                    },
                )
            return reports

    async def get_order_history(self, limit: int = 50, symbol: str | None = None) -> list[OrderLifecycleEventResponse]:
        query = cast(
            ModelSelect,
            OrderLifecycleRecord.select().order_by(OrderLifecycleRecord.updated_at.desc()).limit(max(limit, 0)),
        )
        if symbol:
            query = cast(ModelSelect, query.where(OrderLifecycleRecord.symbol == symbol))
        events: list[OrderLifecycleEventResponse] = []
        rows: list[OrderLifecycleRecord] = list(query)
        for row in reversed(rows):
            payload = _json_object(row.payload_json)
            events.append(
                OrderLifecycleEventResponse(
                    instrument_type=str(payload.get("instrument_type", "stock")),
                    event_id=row.event_id,
                    order_id=row.order_id,
                    symbol=row.symbol,
                    action=row.action,
                    order_type=row.order_type,
                    quantity=self._deserialize_optional_float(row.quantity),
                    limit_price=self._deserialize_optional_float(row.limit_price),
                    stop_price=self._deserialize_optional_float(row.stop_price),
                    time_in_force=row.time_in_force,
                    latest_status=row.latest_status,
                    client_request_id=row.client_request_id,
                    source_event_type=row.source_event_type,
                    updated_at=cast(datetime, row.updated_at).isoformat(),
                    payload=payload,
                )
            )
        return events

    async def get_position_history(self, limit: int = 50, symbol: str | None = None) -> list[PositionSnapshotResponse]:
        query = cast(
            ModelSelect,
            PositionSnapshotRecord.select().order_by(PositionSnapshotRecord.captured_at.desc()).limit(max(limit, 0)),
        )
        if symbol:
            query = cast(ModelSelect, query.where(PositionSnapshotRecord.symbol == symbol))
        history: list[PositionSnapshotResponse] = []
        rows: list[PositionSnapshotRecord] = list(query)
        for row in reversed(rows):
            history.append(
                PositionSnapshotResponse(
                    instrument_type="stock",
                    snapshot_id=row.snapshot_id,
                    symbol=row.symbol,
                    account=row.account,
                    exchange=row.exchange,
                    currency=row.currency,
                    position=self._deserialize_optional_float(row.position) or 0.0,
                    average_cost=self._deserialize_optional_float(row.average_cost),
                    captured_at=cast(datetime, row.captured_at).isoformat(),
                    source=row.source,
                )
            )
        return history

    async def get_execution_quality(self, order_id: str) -> ExecutionQualityResponse:
        lifecycle_query = cast(
            ModelSelect,
            OrderLifecycleRecord.select().where(OrderLifecycleRecord.order_id == order_id),
        )
        lifecycle_query = cast(ModelSelect, lifecycle_query.order_by(OrderLifecycleRecord.updated_at.desc()))
        lifecycle = cast(OrderLifecycleRecord | None, lifecycle_query.first())
        if lifecycle is None:
            raise TradingValidationError(f"Unknown order_id={order_id}")
        async with self._request_lock:
            fills = await self._client.fills()
        fill = next((item for item in reversed(fills) if str(item.execution.orderId) == order_id), None)
        if fill is None:
            raise TradingValidationError(f"No execution fill found for order_id={order_id}")
        lifecycle_symbol = cast(str | None, lifecycle.symbol)
        fill_instrument_type = self._instrument_type_from_contract(fill.contract)
        reference_price = None
        data_mode = None
        try:
            snapshot = await self.get_instrument_snapshot(
                InstrumentContractSpec(
                    instrument_type=fill_instrument_type,
                    symbol=lifecycle_symbol or fill.contract.symbol,
                    exchange=getattr(fill.contract, "exchange", None) or "SMART",
                    currency=fill.contract.currency,
                    primary_exchange=getattr(fill.contract, "primaryExchange", None),
                )
            )
            reference_price = snapshot.mid_price or snapshot.last or snapshot.close
            data_mode = snapshot.data_mode
        except Exception:
            pass
        fill_price = float(fill.execution.price)
        lifecycle_limit_price = cast(str | None, lifecycle.limit_price)
        lifecycle_action = cast(str | None, lifecycle.action)
        lifecycle_order_type = cast(str | None, lifecycle.order_type)
        lifecycle_quantity = cast(str | None, lifecycle.quantity)
        limit_price = self._deserialize_optional_float(lifecycle_limit_price)
        quantity = self._deserialize_optional_float(lifecycle_quantity)
        baseline = limit_price or reference_price
        estimated_slippage = None
        estimated_slippage_bps = None
        notes: list[str] = []
        if baseline and baseline > 0:
            if (lifecycle_action or "").upper() == "BUY":
                estimated_slippage = fill_price - baseline
            else:
                estimated_slippage = baseline - fill_price
            estimated_slippage_bps = (estimated_slippage / baseline) * 10000
        else:
            notes.append("No baseline price available for slippage estimate")
        quality = "good"
        if estimated_slippage_bps is not None and estimated_slippage_bps > 25:
            quality = "poor"
        elif estimated_slippage_bps is not None and estimated_slippage_bps > 5:
            quality = "fair"
        if data_mode == "delayed":
            notes.append("Reference price used delayed market data")
        return ExecutionQualityResponse(
            instrument_type=fill_instrument_type,
            order_id=order_id,
            symbol=lifecycle_symbol or fill.contract.symbol,
            action=lifecycle_action,
            order_type=lifecycle_order_type,
            quantity=quantity,
            submitted_limit_price=limit_price,
            fill_price=fill_price,
            reference_price=reference_price,
            estimated_slippage=estimated_slippage,
            estimated_slippage_bps=estimated_slippage_bps,
            data_mode=data_mode,
            quality=quality,
            notes=notes,
        )

    async def get_recent_audit_events(self, limit: int = 50) -> list[AuditEventResponse]:
        events: list[AuditEventResponse] = []
        query = cast(
            ModelSelect,
            AuditEventRecord.select()
            .order_by(AuditEventRecord.created_at.desc())
            .limit(max(limit, 0)),
        )
        rows: list[AuditEventRecord] = list(query)
        for row in reversed(rows):
            try:
                payload = _json_object(row.payload_json)
                actor = cast(str | None, row.actor)
                requester = cast(str | None, row.requester)
                request_source = cast(str | None, row.request_source)
                agent_id = cast(str | None, row.agent_id)
                run_id = cast(str | None, row.run_id)
                strategy_id = cast(str | None, row.strategy_id)
                symbol = cast(str | None, row.symbol)
                order_id = cast(str | None, row.order_id)
                client_request_id = cast(str | None, row.client_request_id)
                approval_id = cast(str | None, row.approval_id)
                status = cast(str | None, row.status)
                policy_decision = cast(str | None, row.policy_decision)
                events.append(
                    AuditEventResponse(
                        event_id=str(row.event_id),
                        event_type=str(row.event_type),
                        created_at=cast(datetime, row.created_at).isoformat(),
                        actor=actor,
                        requester=requester,
                        request_source=request_source,
                        agent_id=agent_id,
                        run_id=run_id,
                        strategy_id=strategy_id,
                        symbol=symbol,
                        order_id=order_id,
                        client_request_id=client_request_id,
                        approval_id=approval_id,
                        status=status,
                        policy_decision=policy_decision,
                        payload=payload,
                    )
                )
            except Exception:
                continue
        return events

    async def get_audit_behavior_summary(
        self,
        *,
        limit: int = 500,
        breakdown_by: Literal["agent_id", "run_id", "strategy_id", "request_source"] | None = None,
    ) -> AuditBehaviorSummaryResponse:
        query = cast(
            ModelSelect,
            AuditEventRecord.select()
            .order_by(AuditEventRecord.created_at.desc())
            .limit(max(limit, 0)),
        )
        rows: list[AuditEventRecord] = list(query)

        event_type_counts: dict[str, int] = {}
        agent_ids: set[str] = set()
        run_ids: set[str] = set()
        strategy_ids: set[str] = set()
        unique_symbols: set[str] = set()
        breakdown_counts: dict[str, dict[str, object]] = {}

        total_events = 0
        submitted_orders = 0
        approvals_created = 0
        approvals_approved = 0
        approvals_rejected = 0
        policy_block_events = 0

        for row in rows:
            total_events += 1
            event_type = str(row.event_type)
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1

            symbol = cast(str | None, row.symbol)
            if symbol:
                unique_symbols.add(symbol)

            agent_id = cast(str | None, row.agent_id)
            if agent_id:
                agent_ids.add(agent_id)

            run_id = cast(str | None, row.run_id)
            if run_id:
                run_ids.add(run_id)

            strategy_id = cast(str | None, row.strategy_id)
            if strategy_id:
                strategy_ids.add(strategy_id)

            status = cast(str | None, row.status)
            policy_decision = cast(str | None, row.policy_decision)

            if event_type in {"order_submitted", "approval_submitted", "position_close_requested"}:
                submitted_orders += 1
            if event_type == "approval_created":
                approvals_created += 1
            if event_type == "approval_approved":
                approvals_approved += 1
            if event_type == "approval_rejected":
                approvals_rejected += 1
            if policy_decision == "blocked" or status == "blocked" or "blocked" in event_type:
                policy_block_events += 1

            if breakdown_by is None:
                continue

            raw_key = getattr(row, breakdown_by, None)
            key = str(raw_key) if raw_key not in (None, "") else "unattributed"
            bucket = breakdown_counts.setdefault(
                key,
                {
                    "total_events": 0,
                    "submitted_orders": 0,
                    "approvals_created": 0,
                    "approvals_approved": 0,
                    "approvals_rejected": 0,
                    "policy_block_events": 0,
                    "symbols": set(),
                },
            )
            bucket["total_events"] = int(bucket["total_events"]) + 1
            if event_type in {"order_submitted", "approval_submitted", "position_close_requested"}:
                bucket["submitted_orders"] = int(bucket["submitted_orders"]) + 1
            if event_type == "approval_created":
                bucket["approvals_created"] = int(bucket["approvals_created"]) + 1
            if event_type == "approval_approved":
                bucket["approvals_approved"] = int(bucket["approvals_approved"]) + 1
            if event_type == "approval_rejected":
                bucket["approvals_rejected"] = int(bucket["approvals_rejected"]) + 1
            if policy_decision == "blocked" or status == "blocked" or "blocked" in event_type:
                bucket["policy_block_events"] = int(bucket["policy_block_events"]) + 1
            if symbol:
                cast(set[str], bucket["symbols"]).add(symbol)

        breakdown: list[AuditBehaviorBreakdownItem] = []
        for key, bucket in sorted(
            breakdown_counts.items(),
            key=lambda item: int(item[1]["total_events"]),
            reverse=True,
        ):
            breakdown.append(
                AuditBehaviorBreakdownItem(
                    key=key,
                    total_events=int(bucket["total_events"]),
                    submitted_orders=int(bucket["submitted_orders"]),
                    approvals_created=int(bucket["approvals_created"]),
                    approvals_approved=int(bucket["approvals_approved"]),
                    approvals_rejected=int(bucket["approvals_rejected"]),
                    policy_block_events=int(bucket["policy_block_events"]),
                    unique_symbols=sorted(cast(set[str], bucket["symbols"])),
                )
            )

        top_event_types = dict(
            sorted(
                event_type_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        )

        return AuditBehaviorSummaryResponse(
            total_events=total_events,
            submitted_orders=submitted_orders,
            approvals_created=approvals_created,
            approvals_approved=approvals_approved,
            approvals_rejected=approvals_rejected,
            policy_block_events=policy_block_events,
            unique_agents=len(agent_ids),
            unique_runs=len(run_ids),
            unique_strategies=len(strategy_ids),
            unique_symbols=sorted(unique_symbols),
            top_event_types=top_event_types,
            breakdown_dimension=breakdown_by,
            breakdown=breakdown,
        )

    async def get_market_session_status(self) -> MarketSessionStatusResponse:
        ny = ZoneInfo("America/New_York")
        now = datetime.now(ny)
        weekday = now.weekday()
        minutes = now.hour * 60 + now.minute
        if weekday >= 5:
            session = "weekend"
            is_open = False
            allows_market_orders = False
            allows_limit_orders = False
        elif 4 * 60 <= minutes < 9 * 60 + 30:
            session = "pre_market"
            is_open = False
            allows_market_orders = False
            allows_limit_orders = True
        elif 9 * 60 + 30 <= minutes < 16 * 60:
            session = "regular"
            is_open = True
            allows_market_orders = True
            allows_limit_orders = True
        elif 16 * 60 <= minutes < 20 * 60:
            session = "after_hours"
            is_open = False
            allows_market_orders = False
            allows_limit_orders = True
        else:
            session = "closed"
            is_open = False
            allows_market_orders = False
            allows_limit_orders = False
        return MarketSessionStatusResponse(
            market="US_EQUITIES",
            timezone="America/New_York",
            current_time=now.isoformat(),
            session=session,
            is_open=is_open,
            allows_market_orders=allows_market_orders,
            allows_limit_orders=allows_limit_orders,
            next_session_transition=None,
        )

    async def reconcile_broker_state(self) -> BrokerReconciliationResponse:
        async with self._request_lock:
            trades = await self._client.open_trades()
            positions = await self._client.positions()
        trade_rows: list[Trade] = trades
        position_rows: list[BrokerPosition] = positions
        broker_open_ids = {str(trade.order.orderId) for trade in trade_rows}
        active_statuses = {"PendingSubmit", "PreSubmitted", "Submitted"}
        latest_lifecycle_rows = self._latest_order_lifecycle_rows()
        local_active_ids = {
            cast(str, row.order_id)
            for row in latest_lifecycle_rows
            if cast(str | None, row.latest_status) in active_statuses
        }
        unknown_broker_order_ids = sorted(order_id for order_id in broker_open_ids if order_id not in local_active_ids)
        if unknown_broker_order_ids:
            trades_by_order_id = {str(trade.order.orderId): trade for trade in trade_rows}
            for order_id in unknown_broker_order_ids:
                trade = trades_by_order_id.get(order_id)
                if trade is None:
                    continue
                open_order = self._open_order_response(trade)
                self._record_order_lifecycle(
                    order_id=open_order.order_id,
                    source_event_type="broker_reconcile_open_order",
                    symbol=open_order.symbol,
                    action=open_order.action,
                    order_type=open_order.order_type,
                    quantity=open_order.total_quantity,
                    limit_price=open_order.limit_price,
                    stop_price=open_order.stop_price,
                    time_in_force=open_order.time_in_force,
                    latest_status=open_order.status,
                    payload=open_order.model_dump(),
                )
            latest_lifecycle_rows = self._latest_order_lifecycle_rows()
            local_active_ids = {
                cast(str, row.order_id)
                for row in latest_lifecycle_rows
                if cast(str | None, row.latest_status) in active_statuses
            }
            unknown_broker_order_ids = sorted(order_id for order_id in broker_open_ids if order_id not in local_active_ids)
        stale_local_active_order_ids = sorted(order_id for order_id in local_active_ids if order_id not in broker_open_ids)
        if stale_local_active_order_ids:
            latest_by_order_id = {
                cast(str, row.order_id): row
                for row in latest_lifecycle_rows
                if cast(str | None, row.order_id) is not None
            }
            for order_id in stale_local_active_order_ids:
                row = latest_by_order_id.get(order_id)
                self._record_order_lifecycle(
                    order_id=order_id,
                    source_event_type="broker_reconcile_missing",
                    symbol=cast(str | None, row.symbol) if row is not None else None,
                    action=cast(str | None, row.action) if row is not None else None,
                    order_type=cast(str | None, row.order_type) if row is not None else None,
                    quantity=self._deserialize_optional_float(cast(str | None, row.quantity)) if row is not None else None,
                    limit_price=self._deserialize_optional_float(cast(str | None, row.limit_price)) if row is not None else None,
                    stop_price=self._deserialize_optional_float(cast(str | None, row.stop_price)) if row is not None else None,
                    time_in_force=cast(str | None, row.time_in_force) if row is not None else None,
                    latest_status="BrokerMissing",
                    client_request_id=cast(str | None, row.client_request_id) if row is not None else None,
                    payload={"order_id": order_id, "status": "BrokerMissing"},
                )
            latest_lifecycle_rows = self._latest_order_lifecycle_rows()
            local_active_ids = {
                cast(str, row.order_id)
                for row in latest_lifecycle_rows
                if cast(str | None, row.latest_status) in active_statuses
            }
            stale_local_active_order_ids = sorted(order_id for order_id in local_active_ids if order_id not in broker_open_ids)

        tracked_query = cast(
            ModelSelect,
            OrderLifecycleRecord.select(OrderLifecycleRecord.symbol).where(OrderLifecycleRecord.symbol.is_null(False)),
        )
        tracked_rows: list[OrderLifecycleRecord] = list(tracked_query)
        tracked_symbols = {
            symbol
            for row in tracked_rows
            if (symbol := cast(str | None, row.symbol)) is not None
        }
        unexpected_position_symbols = sorted(
            item.contract.symbol
            for item in position_rows
            if not math.isclose(float(item.position), 0.0) and item.contract.symbol not in tracked_symbols
        )
        summary: list[str] = []
        if unknown_broker_order_ids:
            summary.append(f"Broker has {len(unknown_broker_order_ids)} open order(s) missing from local lifecycle history")
        if stale_local_active_order_ids:
            summary.append(f"Local lifecycle shows {len(stale_local_active_order_ids)} active order(s) not present at broker")
        if unexpected_position_symbols:
            summary.append(f"Broker has unexpected positions for symbols: {', '.join(unexpected_position_symbols)}")
        if not summary:
            summary.append("Broker and local lifecycle state are consistent at the current snapshot")
        return BrokerReconciliationResponse(
            connected=self._client.is_connected(),
            connected_mode=self._client.connected_mode,
            broker_open_order_count=len(broker_open_ids),
            broker_position_count=len([item for item in positions if not math.isclose(float(item.position), 0.0)]),
            unknown_broker_order_ids=unknown_broker_order_ids,
            stale_local_active_order_ids=stale_local_active_order_ids,
            unexpected_position_symbols=unexpected_position_symbols,
            healthy=not (unknown_broker_order_ids or stale_local_active_order_ids or unexpected_position_symbols),
            summary=summary,
        )


    async def get_order_status(self, order_id: str) -> OrderStatusResponse:
        lifecycle_query = cast(
            ModelSelect,
            OrderLifecycleRecord.select().where(OrderLifecycleRecord.order_id == order_id),
        )
        lifecycle_query = cast(ModelSelect, lifecycle_query.order_by(OrderLifecycleRecord.updated_at.desc()))
        lifecycle = cast(OrderLifecycleRecord | None, lifecycle_query.first())
        lifecycle_payload = _json_object(lifecycle.payload_json) if lifecycle is not None else {}

        async with self._request_lock:
            trades = await self._client.open_trades()
            for trade in trades:
                if str(trade.order.orderId) == order_id:
                    return OrderStatusResponse(
                        instrument_type=self._instrument_type_from_contract(trade.contract),
                        order_id=order_id,
                        status=str(trade.orderStatus.status),
                        symbol=trade.contract.symbol,
                        action=trade.order.action,
                        order_type=trade.order.orderType,
                        quantity=float(trade.order.totalQuantity),
                        limit_price=self._normalize_optional_float(getattr(trade.order, "lmtPrice", None)),
                        stop_price=self._normalize_optional_float(getattr(trade.order, "auxPrice", None)),
                        time_in_force=str(getattr(trade.order, "tif", "DAY")),
                        source="broker_open_trade",
                    )

            fills = await self._client.fills()
            for fill in reversed(fills):
                if str(fill.execution.orderId) == order_id:
                    return OrderStatusResponse(
                        instrument_type=self._instrument_type_from_contract(fill.contract),
                        order_id=order_id,
                        status="Filled",
                        symbol=fill.contract.symbol,
                        action=self._normalize_broker_side(fill.execution.side),
                        order_type=None,
                        quantity=float(fill.execution.shares),
                        limit_price=None,
                        stop_price=None,
                        time_in_force=None,
                        source="broker_fill",
                        message=f"Filled at {float(fill.execution.price)} on {fill.execution.time}",
                    )

        return OrderStatusResponse(
            instrument_type=self._deserialize_instrument_type(cast(str | None, lifecycle_payload.get("instrument_type")) if 'lifecycle_payload' in locals() else None),
            order_id=order_id,
            status="UNKNOWN",
            source="broker_lookup_miss",
            message="Order is not present in broker open trades or recent fills",
        )

    async def qualify_symbol(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> QualifiedStockContractResponse:
        response = await self.qualify_instrument(
            InstrumentContractSpec(
                instrument_type="stock",
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            )
        )
        return QualifiedStockContractResponse(**response.model_dump())

    async def qualify_instrument(
        self,
        spec: InstrumentContractSpec,
    ) -> QualifiedContractResponse:
        async with self._request_lock:
            contract = await self._client.qualify_contract(spec)
            return QualifiedContractResponse(
                instrument_type=spec.instrument_type,
                con_id=contract.conId,
                symbol=contract.symbol,
                exchange=contract.exchange,
                primary_exchange=getattr(contract, "primaryExchange", None),
                currency=contract.currency,
                local_symbol=getattr(contract, "localSymbol", None),
                trading_class=getattr(contract, "tradingClass", None),
            )

    async def get_stock_quote(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> MarketQuoteResponse:
        return await self.get_market_quote(
            InstrumentContractSpec(
                instrument_type="stock",
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            )
        )

    def _instrument_cache_key(self, prefix: str, spec: InstrumentContractSpec) -> str:
        return (
            f"{prefix}:{spec.instrument_type}:{spec.symbol}:{spec.exchange}:"
            f"{spec.currency}:{spec.primary_exchange or '-'}"
        )

    @staticmethod
    def _parse_ib_hours_timestamp(raw: str, default_date: str, tz: ZoneInfo) -> datetime | None:
        token = raw.strip()
        if not token:
            return None
        if ":" in token:
            normalized = token.replace(":", "")
        else:
            normalized = f"{default_date}{token}"
        try:
            parsed = datetime.strptime(normalized, "%Y%m%d%H%M")
        except ValueError:
            return None
        return parsed.replace(tzinfo=tz)

    def _contract_is_open_now(self, details: "ContractDetails") -> bool | None:
        hours_blob = getattr(details, "liquidHours", None) or getattr(details, "tradingHours", None)
        if not hours_blob:
            return None

        timezone_name = getattr(details, "timeZoneId", None) or "UTC"
        try:
            timezone = ZoneInfo(timezone_name)
        except Exception:
            timezone = ZoneInfo("UTC")

        now = datetime.now(timezone)
        saw_window = False

        for segment in str(hours_blob).split(";"):
            if not segment or ":" not in segment:
                continue
            trade_date, ranges_blob = segment.split(":", 1)
            if ranges_blob == "CLOSED":
                continue

            for window in ranges_blob.split(","):
                if "-" not in window:
                    continue
                start_raw, end_raw = window.split("-", 1)
                start_at = self._parse_ib_hours_timestamp(start_raw, trade_date, timezone)
                end_at = self._parse_ib_hours_timestamp(end_raw, trade_date, timezone)
                if start_at is None or end_at is None:
                    continue
                saw_window = True
                if start_at <= now <= end_at:
                    return True

        if saw_window:
            return False
        return None

    async def _instrument_closed_note(self, spec: InstrumentContractSpec) -> str | None:
        try:
            contract = await self._client.qualify_contract(spec)
            details = await self._client.contract_details(contract)
        except Exception:
            return None

        if details is None:
            return None

        is_open = self._contract_is_open_now(details)
        if is_open is not False:
            return None

        venue = (
            getattr(details, "marketName", None)
            or getattr(contract, "primaryExchange", None)
            or getattr(contract, "exchange", None)
            or spec.exchange
        )
        return f"{venue} is currently closed per IB trading hours"

    async def get_market_quote(
        self,
        spec: InstrumentContractSpec,
    ) -> MarketQuoteResponse:
        cache_key = self._instrument_cache_key("market_quote", spec)
        async def factory() -> MarketQuoteResponse:
            async with self._request_lock:
                self._logger.info(
                    "Starting market quote symbol=%s exchange=%s primary_exchange=%s cache_key=%s",
                    spec.symbol,
                    spec.exchange,
                    spec.primary_exchange,
                    cache_key,
                )
                closed_note = await asyncio.wait_for(
                    self._instrument_closed_note(spec),
                    timeout=self._settings.ib_market_data_timeout_seconds + 1.0,
                )
                try:
                    quote = await asyncio.wait_for(
                        self._client.market_quote(spec),
                        timeout=self._settings.ib_market_data_timeout_seconds + 1.0,
                    )
                except asyncio.TimeoutError:
                    self._logger.warning(
                        "Market quote wrapper timed out symbol=%s exchange=%s primary_exchange=%s",
                        spec.symbol,
                        spec.exchange,
                        spec.primary_exchange,
                    )
                    return MarketQuoteResponse(
                        instrument_type=spec.instrument_type,
                        symbol=spec.symbol,
                        exchange=spec.exchange,
                        currency=spec.currency,
                        data_mode="unavailable",
                        quote_available=False,
                        availability_note=self._merge_availability_notes(
                            "Timed out waiting for market data from IB Gateway; "
                            "session may be disconnected or not entitled",
                            closed_note,
                        ),
                    )
                except ValueError as exc:
                    self._logger.warning(
                        "Market quote unavailable symbol=%s exchange=%s primary_exchange=%s detail=%s",
                        spec.symbol,
                        spec.exchange,
                        spec.primary_exchange,
                        exc,
                    )
                    return MarketQuoteResponse(
                        instrument_type=spec.instrument_type,
                        symbol=spec.symbol,
                        exchange=spec.exchange,
                        currency=spec.currency,
                        data_mode="unavailable",
                        quote_available=False,
                        availability_note=self._merge_availability_notes(str(exc), closed_note),
                    )

                self._logger.info(
                    "Completed market quote symbol=%s exchange=%s primary_exchange=%s data_mode=%s bid=%s ask=%s last=%s close=%s",
                    spec.symbol,
                    spec.exchange,
                    spec.primary_exchange,
                    quote["data_mode"],
                    quote["ticker"].bid,
                    quote["ticker"].ask,
                    quote["ticker"].last,
                    quote["ticker"].close,
                )
                return MarketQuoteResponse(
                    instrument_type=spec.instrument_type,
                    symbol=spec.symbol,
                    exchange=spec.exchange,
                    currency=spec.currency,
                    data_mode=str(quote["data_mode"]),
                    quote_available=True,
                    availability_note=closed_note if quote["data_mode"] != "live" else None,
                    bid=self._normalize_optional_float(quote["ticker"].bid),
                    ask=self._normalize_optional_float(quote["ticker"].ask),
                    last=self._normalize_optional_float(quote["ticker"].last),
                    close=self._normalize_optional_float(quote["ticker"].close),
                )

        return cast(MarketQuoteResponse, await self._cached_read(cache_key, 3.0, factory))

    @staticmethod
    def _merge_availability_notes(primary: str | None, secondary: str | None) -> str | None:
        notes = [note for note in (primary, secondary) if note]
        if not notes:
            return None
        if len(notes) == 1:
            return notes[0]
        return " | ".join(notes)

    async def get_market_snapshot(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> MarketSnapshotResponse:
        return await self.get_instrument_snapshot(
            InstrumentContractSpec(
                instrument_type="stock",
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
            )
        )

    async def get_instrument_snapshot(
        self,
        spec: InstrumentContractSpec,
    ) -> MarketSnapshotResponse:
        cache_key = self._instrument_cache_key("market_snapshot", spec)
        async def factory() -> MarketSnapshotResponse:
            quote = await self.get_market_quote(spec)
            bid = quote.bid
            ask = quote.ask
            last = quote.last
            close = quote.close
            mid_price = self._mid_price(bid, ask)
            spread = ask - bid if bid is not None and ask is not None else None
            spread_bps = (spread / mid_price) * 10000 if spread is not None and mid_price not in (None, 0) else None
            reference_price = last if last is not None else mid_price
            day_change = reference_price - close if reference_price is not None and close is not None else None
            day_change_percent = (day_change / close) * 100 if day_change is not None and close not in (None, 0) else None
            return MarketSnapshotResponse(
                instrument_type=spec.instrument_type,
                symbol=spec.symbol,
                exchange=spec.exchange,
                currency=spec.currency,
                primary_exchange=spec.primary_exchange,
                data_mode=quote.data_mode,
                quote_available=quote.quote_available,
                availability_note=quote.availability_note,
                bid=bid,
                ask=ask,
                last=last,
                close=close,
                mid_price=mid_price,
                spread=spread,
                spread_bps=spread_bps,
                day_change=day_change,
                day_change_percent=day_change_percent,
                has_two_sided_market=bid is not None and ask is not None,
                quote_quality=self._quote_quality(
                    data_mode=quote.data_mode,
                    bid=bid,
                    ask=ask,
                    spread_bps=spread_bps,
                    last=last,
                ),
            )

        return cast(MarketSnapshotResponse, await self._cached_read(cache_key, 3.0, factory))

    async def get_historical_bars(
        self,
        spec: InstrumentContractSpec,
        *,
        timeframe: str,
        duration: str,
        what_to_show: str = "TRADES",
        use_rth: bool = True,
    ) -> HistoricalBarsResponse:
        cache_key = self._instrument_cache_key(
            "historical_bars",
            InstrumentContractSpec(
                instrument_type=spec.instrument_type,
                symbol=spec.symbol,
                exchange=f"{spec.exchange}:{timeframe}:{duration}:{what_to_show}:{int(use_rth)}",
                currency=spec.currency,
                primary_exchange=spec.primary_exchange,
            ),
        )

        async def factory() -> HistoricalBarsResponse:
            async with self._request_lock:
                bars = await asyncio.wait_for(
                    self._client.historical_bars(
                        spec,
                        timeframe=timeframe,
                        duration=duration,
                        what_to_show=what_to_show,
                        use_rth=use_rth,
                    ),
                    timeout=self._settings.ib_request_timeout_seconds + 1.0,
                )

            normalized_bars = [self._normalize_historical_bar(bar) for bar in bars]
            return HistoricalBarsResponse(
                instrument_type=spec.instrument_type,
                symbol=spec.symbol,
                exchange=spec.exchange,
                currency=spec.currency,
                primary_exchange=spec.primary_exchange,
                data_mode="historical",
                timeframe=timeframe,
                duration=duration,
                what_to_show=what_to_show,
                use_rth=use_rth,
                bar_count=len(normalized_bars),
                bars=normalized_bars,
            )

        return cast(HistoricalBarsResponse, await self._cached_read(cache_key, 15.0, factory))

    async def get_multi_timeframe_bars(
        self,
        spec: InstrumentContractSpec,
        *,
        what_to_show: str = "TRADES",
        use_rth: bool = True,
    ) -> MultiTimeframeBarsResponse:
        frame_specs = {
            "1m": ("1 min", "1 D"),
            "5m": ("5 mins", "2 D"),
            "15m": ("15 mins", "5 D"),
            "1d": ("1 day", "3 M"),
        }
        frames: dict[str, HistoricalBarsResponse] = {}
        for label, (timeframe, duration) in frame_specs.items():
            frames[label] = await self.get_historical_bars(
                spec,
                timeframe=timeframe,
                duration=duration,
                what_to_show=what_to_show,
                use_rth=use_rth,
            )

        return MultiTimeframeBarsResponse(
            instrument_type=spec.instrument_type,
            symbol=spec.symbol,
            exchange=spec.exchange,
            currency=spec.currency,
            primary_exchange=spec.primary_exchange,
            data_mode="historical",
            what_to_show=what_to_show,
            use_rth=use_rth,
            frames=frames,
        )

    async def get_level_map(
        self,
        spec: InstrumentContractSpec,
        *,
        intraday_timeframe: str = "5 mins",
        intraday_duration: str = "1 D",
        daily_duration: str = "10 D",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
    ) -> LevelMapResponse:
        cache_key = self._instrument_cache_key(
            "level_map",
            InstrumentContractSpec(
                instrument_type=spec.instrument_type,
                symbol=spec.symbol,
                exchange=(
                    f"{spec.exchange}:{intraday_timeframe}:{intraday_duration}:{daily_duration}:"
                    f"{what_to_show}:{int(use_rth)}"
                ),
                currency=spec.currency,
                primary_exchange=spec.primary_exchange,
            ),
        )

        async def factory() -> LevelMapResponse:
            intraday = await self.get_historical_bars(
                spec,
                timeframe=intraday_timeframe,
                duration=intraday_duration,
                what_to_show=what_to_show,
                use_rth=use_rth,
            )
            daily = await self.get_historical_bars(
                spec,
                timeframe="1 day",
                duration=daily_duration,
                what_to_show=what_to_show,
                use_rth=use_rth,
            )

            intraday_bars = intraday.bars
            daily_bars = daily.bars
            current_bar = intraday_bars[-1] if intraday_bars else None
            prior_daily_bar = daily_bars[-2] if len(daily_bars) >= 2 else None
            latest_daily_bar = daily_bars[-1] if daily_bars else None
            rolling_window = daily_bars[-5:] if daily_bars else []

            intraday_vwap = self._volume_weighted_average_price(intraday_bars)

            return LevelMapResponse(
                instrument_type=spec.instrument_type,
                symbol=spec.symbol,
                exchange=spec.exchange,
                currency=spec.currency,
                primary_exchange=spec.primary_exchange,
                data_mode="historical",
                intraday_timeframe=intraday_timeframe,
                intraday_duration=intraday_duration,
                daily_duration=daily_duration,
                what_to_show=what_to_show,
                use_rth=use_rth,
                current_price=current_bar.close if current_bar else (latest_daily_bar.close if latest_daily_bar else None),
                current_time=current_bar.time if current_bar else None,
                session_open=intraday_bars[0].open if intraday_bars else None,
                session_high=max((bar.high for bar in intraday_bars), default=None),
                session_low=min((bar.low for bar in intraday_bars), default=None),
                prior_close=prior_daily_bar.close if prior_daily_bar else None,
                prior_day_high=prior_daily_bar.high if prior_daily_bar else None,
                prior_day_low=prior_daily_bar.low if prior_daily_bar else None,
                rolling_5d_high=max((bar.high for bar in rolling_window), default=None),
                rolling_5d_low=min((bar.low for bar in rolling_window), default=None),
                intraday_vwap=intraday_vwap,
                intraday_bar_count=len(intraday_bars),
                daily_bar_count=len(daily_bars),
            )

        return cast(LevelMapResponse, await self._cached_read(cache_key, 10.0, factory))

    async def get_account_risk_snapshot(self) -> AccountRiskSnapshotResponse:
        async with self._request_lock:
            summary = await self._client.account_summary()
            positions = await self._client.positions()
            trades = await self._client.open_trades()

        account = self._preferred_account(summary)
        base_currency = self._summary_value(summary, "RealCurrency", account=account, currency="BASE")
        if base_currency is None:
            base_currency = self._summary_value(summary, "Currency", account="All", currency="BASE")
        profile = self._policy_profile()

        return AccountRiskSnapshotResponse(
            account=account,
            base_currency=base_currency,
            net_liquidation=self._summary_float(summary, "NetLiquidation", account=account),
            available_funds=self._summary_float(summary, "AvailableFunds", account=account),
            buying_power=self._summary_float(summary, "BuyingPower", account=account),
            total_cash_value=self._summary_float(summary, "TotalCashValue", account=account),
            gross_position_value=self._summary_float(summary, "GrossPositionValue", account=account),
            cushion=self._summary_float(summary, "Cushion", account=account),
            position_count=len(positions),
            open_order_count=len(trades),
            connected_mode=self._client.connected_mode,
            max_order_quantity=self._settings.max_order_quantity,
            paper_order_submission_enabled=self._settings.allow_paper_orders,
            policy_mode=profile.name,
        )

    async def get_portfolio_risk_snapshot(self) -> PortfolioRiskSnapshotResponse:
        async with self._request_lock:
            positions = await self._client.positions()
            summary = await self._client.account_summary()

        net_liquidation = self._summary_float(summary, "NetLiquidation", account=self._preferred_account(summary))
        items: list[PortfolioRiskItem] = []
        largest_position_symbol: str | None = None
        largest_position_notional: float | None = None
        total_gross_notional = 0.0

        for position in positions:
            estimated_mark_price = self._normalize_optional_float(getattr(position.contract, "strike", None))
            if estimated_mark_price in (None, 0):
                estimated_mark_price = float(position.avgCost) if float(position.avgCost) > 0 else None
            estimated_notional = abs(float(position.position)) * estimated_mark_price if estimated_mark_price else None
            total_gross_notional += estimated_notional or 0.0
            concentration_percent = (
                (estimated_notional / net_liquidation) * 100
                if estimated_notional is not None and net_liquidation not in (None, 0)
                else None
            )
            if estimated_notional is not None and (largest_position_notional is None or estimated_notional > largest_position_notional):
                largest_position_notional = estimated_notional
                largest_position_symbol = position.contract.symbol
            items.append(
                PortfolioRiskItem(
                    instrument_type=self._instrument_type_from_contract(position.contract),
                    symbol=position.contract.symbol,
                    currency=position.contract.currency,
                    position=float(position.position),
                    average_cost=float(position.avgCost),
                    estimated_mark_price=estimated_mark_price,
                    estimated_notional=estimated_notional,
                    concentration_percent=concentration_percent,
                )
            )

        largest_position_concentration_percent = (
            (largest_position_notional / net_liquidation) * 100
            if largest_position_notional is not None and net_liquidation not in (None, 0)
            else None
        )
        return PortfolioRiskSnapshotResponse(
            account=self._preferred_account(summary),
            net_liquidation=net_liquidation,
            total_gross_notional=total_gross_notional,
            largest_position_symbol=largest_position_symbol,
            largest_position_notional=largest_position_notional,
            largest_position_concentration_percent=largest_position_concentration_percent,
            items=items,
        )

    async def get_symbol_exposure(
        self,
        *,
        instrument_type: str = "stock",
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> SymbolExposureResponse:
        async with self._request_lock:
            positions = await self._client.positions()
            trades = await self._client.open_trades()

        current_position = 0.0
        average_cost: float | None = None
        for position in positions:
            if position.contract.symbol == symbol and position.contract.currency == currency:
                current_position += float(position.position)
                average_cost = float(position.avgCost)

        open_buy_quantity = 0.0
        open_sell_quantity = 0.0
        for trade in trades:
            if trade.contract.symbol != symbol or trade.contract.currency != currency:
                continue
            quantity = float(trade.order.totalQuantity)
            if trade.order.action == "BUY":
                open_buy_quantity += quantity
            elif trade.order.action == "SELL":
                open_sell_quantity += quantity

        net_open_order_quantity = open_buy_quantity - open_sell_quantity
        directional_exposure = "flat"
        combined_position = current_position + net_open_order_quantity
        if combined_position > 0:
            directional_exposure = "long"
        elif combined_position < 0:
            directional_exposure = "short"

        return SymbolExposureResponse(
            instrument_type=instrument_type,
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
            current_position=current_position,
            average_cost=average_cost,
            open_buy_quantity=open_buy_quantity,
            open_sell_quantity=open_sell_quantity,
            net_open_order_quantity=net_open_order_quantity,
            has_position=not math.isclose(current_position, 0.0),
            has_open_orders=not math.isclose(net_open_order_quantity, 0.0),
            directional_exposure=directional_exposure,
        )

    async def get_order_conflicts(
        self,
        *,
        instrument_type: str = "stock",
        symbol: str,
        action: str,
        quantity: float,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> SymbolConflictResponse:
        exposure = await self.get_symbol_exposure(
            instrument_type=instrument_type,
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
        reasons: list[str] = []
        if exposure.has_open_orders:
            reasons.append("Existing open orders already exist for this symbol")
        if action == "BUY" and exposure.open_buy_quantity > 0:
            reasons.append("Duplicate buy-side open order exists")
        if action == "SELL" and exposure.open_sell_quantity > 0:
            reasons.append("Duplicate sell-side open order exists")
        if action == "SELL" and exposure.current_position <= 0 and quantity > 0:
            reasons.append("Sell order may open a short position")
        severity = "warning" if reasons else "ok"
        if exposure.has_open_orders and len(reasons) >= 2:
            severity = "error"
        return SymbolConflictResponse(
            instrument_type=instrument_type,
            symbol=symbol,
            conflict_detected=bool(reasons),
            severity=severity,
            reasons=reasons,
            current_position=exposure.current_position,
            open_buy_quantity=exposure.open_buy_quantity,
            open_sell_quantity=exposure.open_sell_quantity,
        )

    async def get_cash_sizing(self, request: CashSizingRequest) -> CashSizingResponse:
        async with self._request_lock:
            summary = await self._client.account_summary()

        warnings: list[str] = []
        buying_power = self._summary_float(summary, "BuyingPower")
        net_liquidation = self._summary_float(summary, "NetLiquidation")

        if request.budget_type == "cash":
            notional_budget = request.budget_value
        elif request.budget_type == "buying_power_percent":
            if buying_power is None:
                raise TradingValidationError("Buying power is unavailable")
            notional_budget = buying_power * (request.budget_value / 100)
            if request.budget_value > 100:
                warnings.append("Requested buying_power_percent exceeds 100%")
        else:
            if net_liquidation is None:
                raise TradingValidationError("Net liquidation is unavailable")
            notional_budget = net_liquidation * (request.budget_value / 100)
            if request.budget_value > 100:
                warnings.append("Requested net_liquidation_percent exceeds 100%")

        max_whole_shares = max(int(notional_budget // request.reference_price), 0)
        if max_whole_shares == 0:
            warnings.append("Budget is too small to buy a single whole share at the reference price")

        return CashSizingResponse(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            reference_price=request.reference_price,
            budget_type=request.budget_type,
            budget_value=request.budget_value,
            notional_budget=notional_budget,
            max_whole_shares=max_whole_shares,
            current_position=request.current_position,
            projected_position=request.current_position + max_whole_shares,
            warnings=warnings,
        )

    async def get_execution_guardrails(self, request: OrderPreviewRequest) -> ExecutionGuardrailsResponse:
        warnings: list[str] = []
        blockers: list[str] = []
        checks: list[str] = []

        snapshot = await self.get_instrument_snapshot(
            InstrumentContractSpec(
                instrument_type=request.instrument_type,
                symbol=request.symbol,
                exchange=request.exchange,
                currency=request.currency,
                primary_exchange=request.primary_exchange,
            )
        )
        exposure = await self.get_symbol_exposure(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
        )
        conflicts = await self.get_order_conflicts(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
        )
        account_risk = await self.get_account_risk_snapshot()
        profile = self._policy_profile()

        if request.quantity > self._settings.max_order_quantity:
            blockers.append(
                f"Requested quantity {request.quantity} exceeds max_order_quantity={self._settings.max_order_quantity}"
            )
        else:
            checks.append("Quantity is within configured max_order_quantity")

        effective_limit_price = request.limit_price or request.entry_limit_price

        if request.order_type != "BRACKET" and request.take_profit_price is not None:
            blockers.append(
                "take_profit_price is only supported on BRACKET orders or the position exit OCA endpoint"
            )

        if request.order_type not in {"STP", "STP LMT", "BRACKET"} and request.stop_price is not None:
            blockers.append("stop_price is only supported on stop, stop-limit, BRACKET, or position exit OCA orders")

        if request.order_type == "LMT" and effective_limit_price is None:
            blockers.append("LMT orders require limit_price")
        elif request.order_type == "LMT":
            checks.append("Limit order includes limit_price")

        if request.order_type == "STP" and request.stop_price is None:
            blockers.append("STP orders require stop_price")
        elif request.order_type == "STP":
            checks.append("Stop order includes stop_price")

        if request.order_type == "STP LMT":
            if request.limit_price is None or request.stop_price is None:
                blockers.append("STP LMT orders require both limit_price and stop_price")
            else:
                checks.append("Stop-limit order includes both limit and stop prices")

        if request.order_type == "BRACKET":
            if request.entry_limit_price is None or request.take_profit_price is None or request.stop_price is None:
                blockers.append("BRACKET orders require entry_limit_price, take_profit_price, and stop_price")
            else:
                checks.append("Bracket order includes entry, take-profit, and stop prices")

        if snapshot.data_mode != "live":
            warnings.append(f"Quote is using {snapshot.data_mode} data rather than live market data")
        else:
            checks.append("Quote is using live market data")

        if not snapshot.quote_available:
            if self._settings.risk_allow_orders_without_quote:
                warnings.append(
                    "No usable market quote is currently available; execution is proceeding because risk_allow_orders_without_quote is enabled"
                )
            else:
                blockers.append("No usable market quote is currently available for this symbol")
            if snapshot.availability_note:
                warnings.append(snapshot.availability_note)
        else:
            checks.append("A usable market quote is available")

        if not snapshot.has_two_sided_market:
            warnings.append("Bid/ask market is incomplete; slippage risk is higher")
        else:
            checks.append("Bid/ask market is available")

        reference_price = self._reference_price_for_order(snapshot=snapshot, request=request)
        estimated_notional: float | None = None
        estimated_resulting_position_notional: float | None = None
        concentration_after_trade_percent: float | None = None
        approval_required = False

        if reference_price is None:
            blockers.append("Unable to estimate notional because no reliable reference price is available")
        else:
            estimated_notional = abs(request.quantity) * reference_price
            signed_quantity = request.quantity if request.action == "BUY" else -request.quantity
            projected_position = exposure.current_position + signed_quantity
            estimated_resulting_position_notional = abs(projected_position) * reference_price
            concentration_after_trade_percent = (
                (estimated_resulting_position_notional / account_risk.net_liquidation) * 100
                if account_risk.net_liquidation not in (None, 0)
                else None
            )

            if estimated_notional > profile.max_trade_notional:
                blockers.append(
                    f"Estimated trade notional {estimated_notional:.2f} exceeds {profile.name} max_trade_notional={profile.max_trade_notional:.2f}"
                )
            else:
                checks.append("Estimated trade notional is within policy limit")

            if estimated_resulting_position_notional > profile.max_position_notional:
                blockers.append(
                    "Estimated resulting position notional "
                    f"{estimated_resulting_position_notional:.2f} exceeds {profile.name} max_position_notional={profile.max_position_notional:.2f}"
                )
            else:
                checks.append("Estimated resulting position notional is within policy limit")

            if (
                concentration_after_trade_percent is not None
                and concentration_after_trade_percent > profile.max_symbol_concentration_pct
            ):
                blockers.append(
                    "Estimated symbol concentration after trade "
                    f"{concentration_after_trade_percent:.2f}% exceeds {profile.name} max_symbol_concentration_pct={profile.max_symbol_concentration_pct:.2f}%"
                )
            else:
                checks.append("Estimated symbol concentration is within policy limit")

            gross_position_value = account_risk.gross_position_value or 0.0
            if gross_position_value + estimated_notional > profile.max_daily_new_exposure:
                blockers.append(
                    f"Estimated new exposure exceeds {profile.name} max_daily_new_exposure={profile.max_daily_new_exposure:.2f}"
                )
            else:
                checks.append("Estimated new exposure is within policy limit")

        open_order_count_symbol = int(exposure.open_buy_quantity > 0) + int(exposure.open_sell_quantity > 0)
        if open_order_count_symbol >= profile.max_open_orders_per_symbol:
            blockers.append(
                f"Open order count for symbol exceeds {profile.name} max_open_orders_per_symbol={profile.max_open_orders_per_symbol}"
            )
        elif conflicts.conflict_detected:
            warnings.extend(conflicts.reasons)
        else:
            checks.append("No duplicate-order conflicts detected")

        if request.action == "SELL":
            remaining_reducible_position = max(exposure.current_position - exposure.open_sell_quantity, 0.0)
            if request.position_intent in {"auto", "reduce"}:
                if exposure.current_position <= 0:
                    blockers.append(
                        "Sell order would open or increase a short position. Use position_intent='open_short' only when that is deliberate."
                    )
                elif request.quantity > remaining_reducible_position:
                    blockers.append(
                        "Sell quantity exceeds currently reducible long position after accounting for existing open sell orders"
                    )
                else:
                    checks.append("Sell quantity stays within the currently held long position")
            elif request.position_intent == "open_short":
                warnings.append("Short-selling intent is explicit and will be treated as higher-risk execution")
                if request.order_type == "MKT":
                    blockers.append("Short entries must use price-controlled orders, not market orders")
                else:
                    checks.append("Explicit short intent uses a price-controlled order")

        if request.order_type == "MKT" and profile.block_delayed_market_orders and snapshot.data_mode != "live":
            blockers.append("Market orders are blocked when only delayed market data is available")

        if request.order_type == "MKT" and snapshot.spread_bps is not None and snapshot.spread_bps > profile.max_market_spread_bps:
            blockers.append(
                f"Market order blocked because spread {snapshot.spread_bps:.1f} bps exceeds policy max_market_spread_bps={profile.max_market_spread_bps:.1f}"
            )

        if (
            request.order_type == "MKT"
            and profile.require_limit_for_wide_spread
            and snapshot.spread_bps is not None
            and snapshot.spread_bps > profile.wide_spread_bps
        ):
            blockers.append(
                f"Market order blocked because spread {snapshot.spread_bps:.1f} bps exceeds policy wide_spread_bps={profile.wide_spread_bps:.1f}; use a limit order"
            )

        if request.approval_mode == "force_approval":
            approval_required = True
        elif profile.require_approval_for_all:
            approval_required = True
        elif estimated_notional is not None and estimated_notional >= profile.approval_trade_notional:
            approval_required = True
        if request.action == "SELL" and request.position_intent == "open_short":
            approval_required = True

        if not self._settings.allow_paper_orders:
            warnings.append("Order submission is currently disabled by configuration")
        else:
            checks.append("Order submission is enabled by configuration")

        if self._settings.ib_read_only:
            blockers.append("Broker connection is configured read-only; side-effecting order submission is blocked")

        policy_decision = "blocked" if blockers else "allowed_with_approval" if approval_required else "allowed"
        severity = "error" if blockers else "warning" if warnings or approval_required else "ok"
        execution_quality = snapshot.quote_quality
        response = ExecutionGuardrailsResponse(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            time_in_force=request.time_in_force,
            allowed=not blockers,
            policy_decision=policy_decision,
            approval_required=approval_required,
            severity=severity,
            warnings=warnings,
            blockers=blockers,
            checks=checks,
            estimated_notional=estimated_notional,
            estimated_resulting_position_notional=estimated_resulting_position_notional,
            concentration_after_trade_percent=concentration_after_trade_percent,
            execution_quality=execution_quality,
        )
        if blockers:
            self._remember_policy_block(response)
        return response

    async def advise_order(self, request: OrderPreviewRequest) -> OrderAdvisorResponse:
        snapshot = await self.get_instrument_snapshot(
            InstrumentContractSpec(
                instrument_type=request.instrument_type,
                symbol=request.symbol,
                exchange=request.exchange,
                currency=request.currency,
                primary_exchange=request.primary_exchange,
            )
        )
        guardrails = await self.get_execution_guardrails(request)

        rationale: list[str] = []
        warnings = list(guardrails.warnings)
        reference_price = self._reference_price_for_order(snapshot=snapshot, request=request)
        recommended_order_type = request.order_type
        suggested_limit_price: float | None = None

        if snapshot.data_mode != "live":
            if snapshot.data_mode == "unavailable":
                rationale.append("No usable market quote is available, so execution decisions are not credible")
            else:
                rationale.append("Only delayed market data is available, so price confidence is lower")
        else:
            rationale.append("Live market data is available for execution decisions")

        if request.order_type == "MKT":
            if snapshot.has_two_sided_market and snapshot.spread_bps is not None and snapshot.spread_bps <= self._policy_profile().wide_spread_bps:
                rationale.append(f"Spread is tight at {snapshot.spread_bps:.1f} bps, so market execution is acceptable")
            else:
                recommended_order_type = "LMT"
                suggested_limit_price = snapshot.ask if request.action == "BUY" else snapshot.bid
                rationale.append("Market order quality is weak, so a limit order is safer")

        if request.order_type == "BRACKET":
            rationale.append("Bracket orders reduce unattended downside by linking exit logic to entry")
        if request.order_type in {"STP", "STP LMT"}:
            rationale.append("Stop-based orders are best used as protective or breakout logic, not blind entry")

        if not guardrails.allowed:
            rationale.append("Guardrail blockers must be resolved before any submission")

        return OrderAdvisorResponse(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            recommended_order_type=recommended_order_type,
            suggested_limit_price=suggested_limit_price,
            reference_price=reference_price,
            data_mode=snapshot.data_mode,
            approval_required=guardrails.approval_required,
            rationale=rationale,
            warnings=warnings + guardrails.blockers,
            blockers=guardrails.blockers,
        )

    async def evaluate_trade_candidate(self, request: OrderPreviewRequest) -> TradeCandidateEvaluationResponse:
        market_snapshot = await self.get_instrument_snapshot(
            InstrumentContractSpec(
                instrument_type=request.instrument_type,
                symbol=request.symbol,
                exchange=request.exchange,
                currency=request.currency,
                primary_exchange=request.primary_exchange,
            )
        )
        symbol_exposure = await self.get_symbol_exposure(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
        )
        guardrails = await self.get_execution_guardrails(request)
        advice = await self.advise_order(request)
        return TradeCandidateEvaluationResponse(
            market_snapshot=market_snapshot,
            symbol_exposure=symbol_exposure,
            guardrails=guardrails,
            advice=advice,
        )

    async def preview_open_position(self, request: OpenPositionRequest) -> PositionActionPlanResponse:
        normalized = self._normalize_open_position_request(request)
        preview = await self.preview_order(normalized)
        guardrails = await self.get_execution_guardrails(normalized)
        advice = await self.advise_order(normalized)
        return PositionActionPlanResponse(
            normalized_order=normalized,
            preview=preview,
            guardrails=guardrails,
            advice=advice,
        )

    async def submit_open_position(self, request: OpenPositionRequest) -> OrderSubmissionResponse:
        normalized = self._normalize_open_position_request(request)
        return await self.submit_order(normalized)

    async def preview_reduce_position(self, request: ReducePositionRequest) -> PositionActionPlanResponse:
        normalized = await self._normalize_reduce_position_request(request)
        preview = await self.preview_order(normalized)
        guardrails = await self.get_execution_guardrails(normalized)
        advice = await self.advise_order(normalized)
        return PositionActionPlanResponse(
            normalized_order=normalized,
            preview=preview,
            guardrails=guardrails,
            advice=advice,
        )

    async def submit_reduce_position(self, request: ReducePositionRequest) -> OrderSubmissionResponse:
        normalized = await self._normalize_reduce_position_request(request)
        return await self.submit_order(normalized)

    async def submit_position_exit_oca(self, request: PositionExitOcaRequest) -> OrderSubmissionResponse:
        if not self._settings.allow_paper_orders:
            raise TradingValidationError("Order submission is disabled by configuration")
        self._assert_live_order_submission_allowed()
        if self._settings.ib_read_only:
            raise TradingValidationError(
                "Broker connection is configured read-only; side-effecting order submission is blocked"
            )
        if request.take_profit_price <= request.stop_loss_price:
            raise TradingValidationError("Long OCA exit requires take_profit_price above stop_loss_price")

        exposure = await self.get_symbol_exposure(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
        )
        if exposure.current_position <= 0:
            raise TradingValidationError(
                "Position exit OCA currently supports reducing an existing long position only"
            )
        if request.quantity > exposure.current_position:
            raise TradingValidationError(
                "Requested OCA exit quantity "
                f"{request.quantity} exceeds current long position size {exposure.current_position}"
            )
        if exposure.open_sell_quantity > 0:
            raise TradingValidationError(
                "Cannot submit OCA exit while open sell orders already exist for this symbol; cancel or replace them first"
            )

        async with self._runtime.idempotency_lock:
            replay = self._idempotent_replay(request.client_request_id)
            if replay is not None:
                return replay
            if request.client_request_id and request.client_request_id in self._runtime.pending_request_ids:
                raise TradingValidationError(
                    f"A submission with client_request_id={request.client_request_id} is already in progress"
                )
            if request.client_request_id:
                self._runtime.pending_request_ids.add(request.client_request_id)

        try:
            async with self._request_lock:
                oca_group, take_profit_trade, stop_loss_trade = await self._client.place_position_exit_oca(
                    instrument_type=request.instrument_type,
                    symbol=request.symbol,
                    quantity=request.quantity,
                    exchange=request.exchange,
                    currency=request.currency,
                    primary_exchange=request.primary_exchange,
                    take_profit_price=request.take_profit_price,
                    stop_loss_price=request.stop_loss_price,
                    time_in_force=request.time_in_force,
                )
            order_id = f"{take_profit_trade.order.orderId}:{stop_loss_trade.order.orderId}"
            status = f"{take_profit_trade.orderStatus.status}/{stop_loss_trade.orderStatus.status}"
            response = OrderSubmissionResponse(
                instrument_type=request.instrument_type,
                order_id=order_id,
                status=status,
                symbol=request.symbol,
                action="SELL",
                quantity=request.quantity,
                order_type="OCA",
                limit_price=request.take_profit_price,
                stop_price=request.stop_loss_price,
                take_profit_price=request.take_profit_price,
                time_in_force=request.time_in_force,
                client_request_id=request.client_request_id,
                idempotent_replay=False,
            )
            await self._write_audit_event(
                "position_exit_oca_submitted",
                {
                    "symbol": request.symbol,
                    "order_id": order_id,
                    "oca_group": oca_group,
                    "take_profit_order_id": str(take_profit_trade.order.orderId),
                    "stop_loss_order_id": str(stop_loss_trade.order.orderId),
                    "response": response.model_dump(),
                    "requester": request.requester,
                    "request_source": request.request_source,
                    "agent_id": request.agent_id,
                    "run_id": request.run_id,
                    "strategy_id": request.strategy_id,
                    "client_request_id": request.client_request_id,
                },
            )
            self._record_order_lifecycle_from_submission(response, "position_exit_oca_submitted")
            self._store_idempotency_result(request.client_request_id, response)
            return response
        finally:
            if request.client_request_id:
                async with self._runtime.idempotency_lock:
                    self._runtime.pending_request_ids.discard(request.client_request_id)

    async def preview_order(self, request: OrderPreviewRequest) -> OrderPreviewResponse:
        guardrails = await self.get_execution_guardrails(request)
        warnings = list(guardrails.warnings) + list(guardrails.blockers)
        return OrderPreviewResponse(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            take_profit_price=request.take_profit_price,
            entry_limit_price=request.entry_limit_price,
            time_in_force=request.time_in_force,
            warnings=warnings,
            eligible_for_submission=(guardrails.policy_decision == "allowed" and self._settings.allow_paper_orders),
        )

    async def submit_order(self, request: OrderPreviewRequest) -> OrderSubmissionResponse:
        if not self._settings.allow_paper_orders:
            raise TradingValidationError("Order submission is disabled by configuration")
        self._assert_live_order_submission_allowed()

        async with self._runtime.idempotency_lock:
            replay = self._idempotent_replay(request.client_request_id)
            if replay is not None:
                return replay
            if request.client_request_id and request.client_request_id in self._runtime.pending_request_ids:
                raise TradingValidationError(
                    f"A submission with client_request_id={request.client_request_id} is already in progress"
                )
            if request.client_request_id:
                self._runtime.pending_request_ids.add(request.client_request_id)

        try:
            guardrails = await self.get_execution_guardrails(request)
            if guardrails.policy_decision == "blocked":
                raise TradingValidationError("; ".join(guardrails.blockers) or "Order blocked by guardrails")
            if guardrails.policy_decision == "allowed_with_approval":
                mandate = await self._consume_matching_approval_mandate(request, guardrails)
                if mandate is None:
                    raise TradingValidationError("Order requires approval before submission")

            submission = await self._submit_normalized_order(request)
            self._store_idempotency_result(request.client_request_id, submission)
            await self._write_audit_event(
                "order_submitted",
                {
                    **self._audit_context_from_request(request),
                    "client_request_id": request.client_request_id,
                    "response": submission.model_dump(),
                },
            )
            self._record_order_lifecycle_from_submission(submission, "order_submitted")
            return submission
        finally:
            if request.client_request_id:
                async with self._runtime.idempotency_lock:
                    self._runtime.pending_request_ids.discard(request.client_request_id)

    async def create_approval_mandate(self, request: ApprovalMandateRequest) -> ApprovalMandateResponse:
        now = datetime.now(UTC)
        expires_at = now + timedelta(
            seconds=request.expires_in_seconds if request.expires_in_seconds is not None else self._settings.approval_ttl_seconds
        )
        mandate = ApprovalMandate(
            mandate_id=str(uuid4()),
            status="pending",
            created_at=now,
            expires_at=expires_at,
            instrument_type=request.instrument_type,
            target_mode=request.target_mode,
            symbols=[symbol.upper() for symbol in request.symbols],
            actions=[action.upper() for action in request.actions],
            max_order_notional=request.max_order_notional,
            max_uses=request.max_uses,
            uses_consumed=0,
            requester=request.requester,
            request_context={
                "requester": request.requester,
                "request_source": request.request_source,
                "agent_id": request.agent_id,
                "run_id": request.run_id,
                "strategy_id": request.strategy_id,
            },
        )
        async with self._runtime.approval_lock:
            self._runtime.approval_mandates[mandate.mandate_id] = mandate
        self._persist_approval_mandate(mandate)
        await self._write_audit_event(
            "approval_mandate_created",
            {
                **mandate.request_context,
                "mandate_id": mandate.mandate_id,
                "target_mode": mandate.target_mode,
                "max_order_notional": mandate.max_order_notional,
                "max_uses": mandate.max_uses,
            },
        )
        return self._approval_mandate_response(mandate)

    async def get_approval_mandate(self, mandate_id: str) -> ApprovalMandateResponse:
        return self._approval_mandate_response(self._approval_mandate_record(mandate_id))

    async def approve_mandate(self, mandate_id: str, decision: ApprovalDecisionRequest) -> ApprovalMandateResponse:
        async with self._runtime.approval_lock:
            mandate = self._approval_mandate_record(mandate_id)
            self._assert_mandate_pending(mandate)
            mandate.status = "approved"
            mandate.note = decision.note
            mandate.approved_by = decision.actor
            self._persist_approval_mandate(mandate)
        await self._write_audit_event(
            "approval_mandate_approved",
            {"mandate_id": mandate_id, "actor": decision.actor, "note": decision.note},
        )
        return self._approval_mandate_response(mandate)

    async def reject_mandate(self, mandate_id: str, decision: ApprovalDecisionRequest) -> ApprovalMandateResponse:
        async with self._runtime.approval_lock:
            mandate = self._approval_mandate_record(mandate_id)
            self._assert_mandate_pending(mandate)
            mandate.status = "rejected"
            mandate.note = decision.note
            mandate.approved_by = decision.actor
            self._persist_approval_mandate(mandate)
        await self._write_audit_event(
            "approval_mandate_rejected",
            {"mandate_id": mandate_id, "actor": decision.actor, "note": decision.note},
        )
        return self._approval_mandate_response(mandate)

    async def revoke_mandate(self, mandate_id: str, decision: ApprovalDecisionRequest) -> ApprovalMandateResponse:
        async with self._runtime.approval_lock:
            mandate = self._approval_mandate_record(mandate_id)
            if mandate.status not in {"approved", "pending"}:
                raise TradingValidationError(f"Approval mandate cannot be revoked from status={mandate.status}")
            mandate.status = "revoked"
            mandate.note = decision.note
            mandate.approved_by = decision.actor
            self._persist_approval_mandate(mandate)
        await self._write_audit_event(
            "approval_mandate_revoked",
            {"mandate_id": mandate_id, "actor": decision.actor, "note": decision.note},
        )
        return self._approval_mandate_response(mandate)

    async def cancel_order(self, order_id: str) -> OrderCancellationResponse:
        try:
            async with self._request_lock:
                trade = await self._client.cancel_order(order_id=int(order_id))
        except ValueError as exc:
            raise TradingValidationError(str(exc)) from exc
        status = str(trade.orderStatus.status)
        self._audit_logger.info("order_canceled order_id=%s status=%s", order_id, status)
        await self._write_audit_event(
            "order_canceled",
            {"order_id": order_id, "status": status},
        )
        self._record_order_lifecycle(
            order_id=order_id,
            source_event_type="order_canceled",
            symbol=trade.contract.symbol,
            action=trade.order.action,
            order_type=trade.order.orderType,
            quantity=float(trade.order.totalQuantity),
            limit_price=self._normalize_optional_float(getattr(trade.order, "lmtPrice", None)),
            stop_price=self._normalize_optional_float(getattr(trade.order, "auxPrice", None)),
            time_in_force=str(getattr(trade.order, "tif", "DAY")),
            latest_status=status,
            payload={"order_id": order_id, "status": status},
        )
        return OrderCancellationResponse(order_id=order_id, status=status)

    async def cancel_all_open_orders(self) -> CancelAllOrdersResponse:
        async with self._request_lock:
            trades = await self._client.open_trades()
            canceled_ids: list[str] = []
            for trade in trades:
                self._client.ib.cancelOrder(trade.order)
                order_id = str(trade.order.orderId)
                canceled_ids.append(order_id)
                self._record_order_lifecycle(
                    order_id=order_id,
                    source_event_type="orders_canceled_all",
                    symbol=trade.contract.symbol,
                    action=trade.order.action,
                    order_type=trade.order.orderType,
                    quantity=float(trade.order.totalQuantity),
                    limit_price=self._normalize_optional_float(getattr(trade.order, "lmtPrice", None)),
                    stop_price=self._normalize_optional_float(getattr(trade.order, "auxPrice", None)),
                    time_in_force=str(getattr(trade.order, "tif", "DAY")),
                    latest_status="PendingCancel",
                    payload={"order_id": order_id, "status": "PendingCancel"},
                )

        self._audit_logger.info("orders_canceled_all count=%s", len(canceled_ids))
        await self._write_audit_event(
            "orders_canceled_all",
            {"count": len(canceled_ids), "canceled_order_ids": canceled_ids},
        )
        return CancelAllOrdersResponse(canceled_order_ids=canceled_ids, count=len(canceled_ids))

    async def flatten_all_positions(self) -> list[OrderSubmissionResponse]:
        positions = await self.get_positions()
        submissions: list[OrderSubmissionResponse] = []
        for position in positions:
            if math.isclose(position.position, 0.0):
                continue
            submissions.append(
                await self.close_symbol_position(
                    ClosePositionRequest(
                        instrument_type=position.instrument_type,
                        symbol=position.symbol,
                        exchange=position.exchange or "SMART",
                        currency=position.currency,
                        primary_exchange=None,
                        time_in_force="DAY",
                        client_request_id=f"flatten-{position.symbol}-{uuid4()}",
                    )
                )
            )
        await self._write_audit_event(
            "positions_flattened_all",
            {"count": len(submissions), "order_ids": [item.order_id for item in submissions]},
        )
        return submissions

    async def close_symbol_position(self, request: ClosePositionRequest) -> OrderSubmissionResponse:
        exposure = await self.get_symbol_exposure(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
        )
        if math.isclose(exposure.current_position, 0.0):
            raise TradingValidationError("No open position exists for this symbol")
        if exposure.has_open_orders:
            raise TradingValidationError("Cannot close position while open orders already exist for this symbol")

        snapshot = await self.get_instrument_snapshot(
            InstrumentContractSpec(
                instrument_type=request.instrument_type,
                symbol=request.symbol,
                exchange=request.exchange,
                currency=request.currency,
                primary_exchange=request.primary_exchange,
            )
        )
        if not snapshot.has_two_sided_market:
            raise TradingValidationError("Cannot derive a safe close price because bid/ask market is incomplete")

        action = "SELL" if exposure.current_position > 0 else "BUY"
        quantity = abs(exposure.current_position)
        limit_price = snapshot.bid if action == "SELL" else snapshot.ask
        if limit_price is None:
            raise TradingValidationError("Cannot derive a safe close limit price from the current market snapshot")

        close_request = OrderPreviewRequest(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=action,
            quantity=quantity,
            position_intent="reduce" if action == "SELL" else "auto",
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
            order_type="LMT",
            limit_price=limit_price,
            time_in_force=request.time_in_force,
            requester=request.requester or "system:close_symbol_position",
            request_source=request.request_source,
            agent_id=request.agent_id,
            run_id=request.run_id,
            strategy_id=request.strategy_id,
            client_request_id=request.client_request_id,
        )
        submission = await self.submit_order(close_request)
        await self._write_audit_event(
            "position_close_requested",
            {
                **self._audit_context_from_request(close_request),
                "symbol": request.symbol,
                "action": action,
                "quantity": quantity,
                "limit_price": limit_price,
                "client_request_id": request.client_request_id,
                "response": submission.model_dump(),
            },
        )
        return submission

    def _normalize_open_position_request(self, request: OpenPositionRequest) -> OrderPreviewRequest:
        action = "BUY" if request.side == "long" else "SELL"
        position_intent = "auto" if request.side == "long" else "open_short"

        if request.entry_order_type == "BRACKET":
            if request.entry_limit_price is None or request.take_profit_price is None or request.stop_price is None:
                raise TradingValidationError(
                    "BRACKET open_position requires entry_limit_price, take_profit_price, and stop_price"
                )
        elif (request.take_profit_price is not None or request.stop_price is not None) and request.entry_order_type != "BRACKET":
            raise TradingValidationError(
                "Attached stop-loss/take-profit for open_position is only supported through BRACKET orders"
            )

        return OrderPreviewRequest(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=action,
            quantity=request.quantity,
            position_intent=position_intent,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
            order_type=request.entry_order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            take_profit_price=request.take_profit_price,
            entry_limit_price=request.entry_limit_price,
            time_in_force=request.time_in_force,
            requester=request.requester,
            request_source=request.request_source,
            agent_id=request.agent_id,
            run_id=request.run_id,
            strategy_id=request.strategy_id,
            approval_mode=request.approval_mode,
            client_request_id=request.client_request_id,
        )

    async def _normalize_reduce_position_request(self, request: ReducePositionRequest) -> OrderPreviewRequest:
        exposure = await self.get_symbol_exposure(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
        )
        if math.isclose(exposure.current_position, 0.0):
            raise TradingValidationError("No open position exists for this symbol")
        if request.quantity > abs(exposure.current_position):
            raise TradingValidationError(
                f"Requested reduce quantity {request.quantity} exceeds current position size {abs(exposure.current_position)}"
            )
        if exposure.has_open_orders:
            raise TradingValidationError("Cannot reduce position while open orders already exist for this symbol")

        snapshot = await self.get_instrument_snapshot(
            InstrumentContractSpec(
                instrument_type=request.instrument_type,
                symbol=request.symbol,
                exchange=request.exchange,
                currency=request.currency,
                primary_exchange=request.primary_exchange,
            )
        )
        if not snapshot.has_two_sided_market:
            raise TradingValidationError("Cannot derive a safe reduce price because bid/ask market is incomplete")

        action = "SELL" if exposure.current_position > 0 else "BUY"
        limit_price = snapshot.bid if action == "SELL" else snapshot.ask
        if limit_price is None:
            raise TradingValidationError("Cannot derive a safe reduce limit price from the current market snapshot")

        return OrderPreviewRequest(
            instrument_type=request.instrument_type,
            symbol=request.symbol,
            action=action,
            quantity=request.quantity,
            position_intent="reduce" if action == "SELL" else "auto",
            exchange=request.exchange,
            currency=request.currency,
            primary_exchange=request.primary_exchange,
            order_type="LMT",
            limit_price=limit_price,
            time_in_force=request.time_in_force,
            requester=request.requester or "system:reduce_position",
            request_source=request.request_source,
            agent_id=request.agent_id,
            run_id=request.run_id,
            strategy_id=request.strategy_id,
            approval_mode="policy",
            client_request_id=request.client_request_id,
        )


    async def replace_order(self, request: OrderReplaceRequest) -> OrderSubmissionResponse:
        try:
            async with self._request_lock:
                trade = await self._client.replace_order(
                    order_id=int(request.order_id),
                    quantity=request.quantity,
                    limit_price=request.limit_price,
                    stop_price=request.stop_price,
                    time_in_force=request.time_in_force,
                )
        except ValueError as exc:
            raise TradingValidationError(str(exc)) from exc
        response = OrderSubmissionResponse(
            instrument_type=self._instrument_type_from_contract(trade.contract),
            order_id=str(trade.order.orderId),
            status=str(trade.orderStatus.status),
            symbol=trade.contract.symbol,
            action=trade.order.action,
            quantity=float(trade.order.totalQuantity),
            order_type=trade.order.orderType,
            limit_price=self._normalize_optional_float(getattr(trade.order, "lmtPrice", None)),
            stop_price=self._normalize_optional_float(getattr(trade.order, "auxPrice", None)),
            time_in_force=str(getattr(trade.order, "tif", "DAY")),
        )
        self._audit_logger.info("order_replaced order_id=%s", request.order_id)
        await self._write_audit_event(
            "order_replaced",
            {
                "order_id": request.order_id,
                "quantity": request.quantity,
                "limit_price": request.limit_price,
                "stop_price": request.stop_price,
                "time_in_force": request.time_in_force,
            },
        )
        self._record_order_lifecycle_from_submission(response, "order_replaced")
        return response

    async def _submit_normalized_order(self, request: OrderPreviewRequest) -> OrderSubmissionResponse:
        async with self._request_lock:
            if request.order_type == "BRACKET":
                trades = await self._client.place_bracket_order(
                    instrument_type=request.instrument_type,
                    symbol=request.symbol,
                    action=request.action,
                    quantity=request.quantity,
                    exchange=request.exchange,
                    currency=request.currency,
                    primary_exchange=request.primary_exchange,
                    entry_limit_price=request.entry_limit_price or 0.0,
                    take_profit_price=request.take_profit_price or 0.0,
                    stop_loss_price=request.stop_price or 0.0,
                    time_in_force=request.time_in_force,
                )
                parent = trades[0]
                order_id = f"{parent.order.orderId}:{len(trades)}"
                status = str(parent.orderStatus.status)
                bracket_trades = trades
            else:
                trade = await self._client.place_order(
                    instrument_type=request.instrument_type,
                    symbol=request.symbol,
                    action=request.action,
                    quantity=request.quantity,
                    exchange=request.exchange,
                    currency=request.currency,
                    primary_exchange=request.primary_exchange,
                    order_type=request.order_type,
                    limit_price=request.limit_price or request.entry_limit_price,
                    stop_price=request.stop_price,
                    time_in_force=request.time_in_force,
                )
                order_id = str(trade.order.orderId)
                status = str(trade.orderStatus.status)
                bracket_trades = None

        self._audit_logger.info(
            "order_submitted symbol=%s action=%s quantity=%s order_type=%s order_id=%s",
            request.symbol,
            request.action,
            request.quantity,
            request.order_type,
            order_id,
        )
        response = OrderSubmissionResponse(
            instrument_type=request.instrument_type,
            order_id=order_id,
            status=status,
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price or request.entry_limit_price,
            stop_price=request.stop_price,
            take_profit_price=request.take_profit_price,
            time_in_force=request.time_in_force,
            client_request_id=request.client_request_id,
            idempotent_replay=False,
        )
        if bracket_trades is not None:
            self._record_bracket_trade_lifecycle(
                trades=bracket_trades,
                source_event_type="bracket_order_child_submitted",
                client_request_id=request.client_request_id,
            )
        return response

    def _policy_profile(self) -> PolicyProfile:
        resolved_mode: Literal["paper", "live"]
        if self._client.connected_mode in {"paper", "live"}:
            resolved_mode = self._client.connected_mode
        elif self._settings.ib_target_mode == "live":
            resolved_mode = "live"
        elif self._settings.ib_target_mode == "paper":
            resolved_mode = "paper"
        else:
            resolved_mode = self._settings.ib_preferred_mode

        live = resolved_mode == "live"
        if live:
            return PolicyProfile(
                name="live",
                max_trade_notional=self._settings.risk_live_trade_notional,
                max_position_notional=self._settings.risk_live_position_notional,
                max_symbol_concentration_pct=self._settings.risk_live_symbol_concentration_pct,
                max_daily_new_exposure=self._settings.risk_live_daily_new_exposure,
                max_open_orders_per_symbol=self._settings.risk_live_max_open_orders_per_symbol,
                block_delayed_market_orders=self._settings.risk_block_delayed_market_orders,
                max_market_spread_bps=self._settings.risk_max_market_spread_bps,
                require_limit_for_wide_spread=self._settings.risk_require_limit_for_wide_spread,
                wide_spread_bps=self._settings.risk_wide_spread_bps,
                require_approval_for_all=self._settings.risk_live_require_approval,
                approval_trade_notional=self._settings.risk_live_approval_trade_notional,
            )
        return PolicyProfile(
            name="paper",
            max_trade_notional=self._settings.risk_max_trade_notional,
            max_position_notional=self._settings.risk_max_position_notional,
            max_symbol_concentration_pct=self._settings.risk_max_symbol_concentration_pct,
            max_daily_new_exposure=self._settings.risk_max_daily_new_exposure,
            max_open_orders_per_symbol=self._settings.risk_max_open_orders_per_symbol,
            block_delayed_market_orders=self._settings.risk_block_delayed_market_orders,
            max_market_spread_bps=self._settings.risk_max_market_spread_bps,
            require_limit_for_wide_spread=self._settings.risk_require_limit_for_wide_spread,
            wide_spread_bps=self._settings.risk_wide_spread_bps,
            require_approval_for_all=False,
            approval_trade_notional=self._settings.risk_paper_approval_trade_notional,
        )

    def _execution_mode(self) -> Literal["paper", "live"]:
        if self._client.connected_mode in {"paper", "live"}:
            return self._client.connected_mode
        if self._settings.ib_target_mode == "live":
            return "live"
        if self._settings.ib_target_mode == "paper":
            return "paper"
        return self._settings.ib_preferred_mode

    def _assert_live_order_submission_allowed(self) -> None:
        if self._execution_mode() == "live" and not self._settings.allow_live_orders:
            raise TradingValidationError(
                "Live order submission is disabled by configuration. Set ALLOW_LIVE_ORDERS=true only after completing the live trading runbook."
            )

    def _approval_mandate_response(self, mandate: ApprovalMandate) -> ApprovalMandateResponse:
        return ApprovalMandateResponse(
            instrument_type=mandate.instrument_type,
            mandate_id=mandate.mandate_id,
            status=mandate.status,
            created_at=mandate.created_at.isoformat(),
            expires_at=mandate.expires_at.isoformat(),
            target_mode=mandate.target_mode,
            symbols=mandate.symbols,
            actions=mandate.actions,
            max_order_notional=mandate.max_order_notional,
            max_uses=mandate.max_uses,
            uses_consumed=mandate.uses_consumed,
            note=mandate.note,
            requester=mandate.requester,
            approved_by=mandate.approved_by,
        )

    def _approval_mandate_record(self, mandate_id: str) -> ApprovalMandate:
        mandate = self._runtime.approval_mandates.get(mandate_id)
        if mandate is None:
            raise TradingValidationError(f"Unknown mandate_id={mandate_id}")
        if mandate.status not in {"consumed", "expired", "rejected", "revoked"} and mandate.expires_at <= datetime.now(UTC):
            mandate.status = "expired"
            self._persist_approval_mandate(mandate)
        if mandate.status == "approved" and mandate.uses_consumed >= mandate.max_uses:
            mandate.status = "consumed"
            self._persist_approval_mandate(mandate)
        return mandate

    @staticmethod
    def _assert_mandate_pending(mandate: ApprovalMandate) -> None:
        if mandate.status != "pending":
            raise TradingValidationError(f"Approval mandate is not pending: status={mandate.status}")
        if mandate.expires_at <= datetime.now(UTC):
            mandate.status = "expired"
            raise TradingValidationError("Approval mandate has expired")

    def _approval_queue_count(self) -> int:
        now = datetime.now(UTC)
        count = 0
        for mandate in self._runtime.approval_mandates.values():
            if mandate.status == "pending" and mandate.expires_at > now:
                count += 1
        return count

    def _idempotent_replay(self, client_request_id: str | None) -> OrderSubmissionResponse | None:
        if not client_request_id:
            return None
        existing = self._runtime.idempotency_records.get(client_request_id)
        if existing is not None:
            return existing.model_copy(update={"idempotent_replay": True})
        try:
            record = IdempotencyRecord.get_or_none(IdempotencyRecord.client_request_id == client_request_id)
            if record is not None:
                restored = OrderSubmissionResponse(**json.loads(record.response_json))
                self._runtime.idempotency_records[client_request_id] = restored
                return restored.model_copy(update={"idempotent_replay": True})
        except Exception:
            return None
        return None

    def _store_idempotency_result(self, client_request_id: str | None, response: OrderSubmissionResponse) -> None:
        if not client_request_id:
            return
        self._runtime.idempotency_records[client_request_id] = response
        response_payload = _model_payload(response)
        IdempotencyRecord.insert(
            client_request_id=client_request_id,
            response_json=dump_json(response_payload),
        ).on_conflict(
            conflict_target=[IdempotencyRecord.client_request_id],
            update={IdempotencyRecord.response_json: dump_json(response_payload)},
        ).execute()

    @staticmethod
    def _persist_approval_mandate(mandate: ApprovalMandate) -> None:
        request_payload = _model_payload(mandate.request) if mandate.request is not None else None
        guardrails_payload = _model_payload(mandate.guardrails) if mandate.guardrails is not None else None
        ApprovalMandateStore.insert(
            mandate_id=mandate.mandate_id,
            status=mandate.status,
            created_at=mandate.created_at,
            expires_at=mandate.expires_at,
            instrument_type=str(mandate.instrument_type),
            target_mode=mandate.target_mode,
            symbols_json=dump_json({"symbols": mandate.symbols}),
            actions_json=dump_json({"actions": mandate.actions}),
            max_order_notional=str(mandate.max_order_notional),
            max_uses=str(mandate.max_uses),
            uses_consumed=str(mandate.uses_consumed),
            note=mandate.note,
            requester=mandate.requester,
            approved_by=mandate.approved_by,
            request_json=dump_json(request_payload) if request_payload is not None else None,
            policy_decision=mandate.policy_decision,
            approval_required=mandate.approval_required,
            guardrails_json=dump_json(guardrails_payload) if guardrails_payload is not None else None,
            request_context_json=dump_json(mandate.request_context),
        ).on_conflict(
            conflict_target=[ApprovalMandateStore.mandate_id],
            update={
                ApprovalMandateStore.status: mandate.status,
                ApprovalMandateStore.expires_at: mandate.expires_at,
                ApprovalMandateStore.symbols_json: dump_json({"symbols": mandate.symbols}),
                ApprovalMandateStore.actions_json: dump_json({"actions": mandate.actions}),
                ApprovalMandateStore.max_order_notional: str(mandate.max_order_notional),
                ApprovalMandateStore.max_uses: str(mandate.max_uses),
                ApprovalMandateStore.uses_consumed: str(mandate.uses_consumed),
                ApprovalMandateStore.note: mandate.note,
                ApprovalMandateStore.requester: mandate.requester,
                ApprovalMandateStore.approved_by: mandate.approved_by,
                ApprovalMandateStore.request_json: dump_json(request_payload) if request_payload is not None else None,
                ApprovalMandateStore.policy_decision: mandate.policy_decision,
                ApprovalMandateStore.approval_required: mandate.approval_required,
                ApprovalMandateStore.guardrails_json: dump_json(guardrails_payload) if guardrails_payload is not None else None,
                ApprovalMandateStore.request_context_json: dump_json(mandate.request_context),
            },
        ).execute()

    async def _write_audit_event(self, event_type: str, payload: dict[str, object]) -> None:
        event_id = str(uuid4())
        created_at = datetime.now(UTC)
        audit_fields = self._extract_audit_fields(event_type, payload)
        async with self._runtime.audit_lock:
            AuditEventRecord.insert(
                event_id=event_id,
                event_type=event_type,
                created_at=created_at,
                actor=audit_fields["actor"],
                requester=audit_fields["requester"],
                request_source=audit_fields["request_source"],
                agent_id=audit_fields["agent_id"],
                run_id=audit_fields["run_id"],
                strategy_id=audit_fields["strategy_id"],
                symbol=audit_fields["symbol"],
                order_id=audit_fields["order_id"],
                client_request_id=audit_fields["client_request_id"],
                approval_id=audit_fields["approval_id"],
                status=audit_fields["status"],
                policy_decision=audit_fields["policy_decision"],
                payload_json=dump_json(payload),
            ).execute()

    async def _consume_matching_approval_mandate(
        self,
        request: OrderPreviewRequest,
        guardrails: ExecutionGuardrailsResponse,
    ) -> ApprovalMandate | None:
        connected_mode = self._client.connected_mode or self._settings.target_mode
        estimated_notional = guardrails.estimated_notional
        if estimated_notional is None or estimated_notional <= 0:
            return None

        async with self._runtime.approval_lock:
            for mandate in self._runtime.approval_mandates.values():
                if not self._mandate_matches_request(mandate, request, connected_mode, estimated_notional):
                    continue
                mandate.uses_consumed += 1
                if mandate.uses_consumed >= mandate.max_uses:
                    mandate.status = "consumed"
                self._persist_approval_mandate(mandate)
                await self._write_audit_event(
                    "approval_mandate_consumed",
                    {
                        **mandate.request_context,
                        **self._audit_context_from_request(request),
                        "mandate_id": mandate.mandate_id,
                        "symbol": request.symbol,
                        "client_request_id": request.client_request_id,
                        "policy_decision": guardrails.policy_decision,
                        "status": mandate.status,
                    },
                )
                return mandate
        return None

    def _mandate_matches_request(
        self,
        mandate: ApprovalMandate,
        request: OrderPreviewRequest,
        connected_mode: str | None,
        estimated_notional: float,
    ) -> bool:
        now = datetime.now(UTC)
        if mandate.status != "approved":
            return False
        if mandate.expires_at <= now:
            mandate.status = "expired"
            self._persist_approval_mandate(mandate)
            return False
        if mandate.uses_consumed >= mandate.max_uses:
            mandate.status = "consumed"
            self._persist_approval_mandate(mandate)
            return False
        if mandate.instrument_type != request.instrument_type:
            return False
        if mandate.target_mode != "auto" and connected_mode is not None and mandate.target_mode != connected_mode:
            return False
        if mandate.symbols and request.symbol.upper() not in mandate.symbols:
            return False
        if mandate.actions and request.action.upper() not in mandate.actions:
            return False
        if estimated_notional > mandate.max_order_notional:
            return False
        return True

    @staticmethod
    def _extract_audit_fields(event_type: str, payload: dict[str, object]) -> dict[str, str | None]:
        response = payload.get("response")
        response_dict = response if isinstance(response, dict) else {}

        actor = _string_or_none(payload.get("actor"))
        requester = _string_or_none(payload.get("requester"))
        request_source = _string_or_none(payload.get("request_source"))
        agent_id = _string_or_none(payload.get("agent_id"))
        run_id = _string_or_none(payload.get("run_id"))
        strategy_id = _string_or_none(payload.get("strategy_id"))
        symbol = _string_or_none(payload.get("symbol")) or _string_or_none(response_dict.get("symbol"))
        order_id = _string_or_none(payload.get("order_id")) or _string_or_none(response_dict.get("order_id"))
        client_request_id = _string_or_none(payload.get("client_request_id")) or _string_or_none(
            response_dict.get("client_request_id")
        )
        approval_id = _string_or_none(payload.get("approval_id")) or _string_or_none(payload.get("mandate_id"))
        status = _string_or_none(payload.get("status")) or _string_or_none(response_dict.get("status"))
        policy_decision = _string_or_none(payload.get("policy_decision"))

        if event_type.startswith("approval_") and actor is None:
            actor = _string_or_none(payload.get("requester"))

        return {
            "actor": actor,
            "requester": requester,
            "request_source": request_source,
            "agent_id": agent_id,
            "run_id": run_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "order_id": order_id,
            "client_request_id": client_request_id,
            "approval_id": approval_id,
            "status": status,
            "policy_decision": policy_decision,
        }

    @staticmethod
    def _audit_context_from_request(request: OrderPreviewRequest) -> dict[str, object]:
        return {
            "requester": request.requester,
            "request_source": request.request_source,
            "agent_id": request.agent_id,
            "run_id": request.run_id,
            "strategy_id": request.strategy_id,
        }

    def _record_order_lifecycle_from_submission(self, response: OrderSubmissionResponse, source_event_type: str) -> None:
        self._record_order_lifecycle(
            order_id=response.order_id,
            source_event_type=source_event_type,
            symbol=response.symbol,
            action=response.action,
            order_type=response.order_type,
            quantity=response.quantity,
            limit_price=response.limit_price,
            stop_price=response.stop_price,
            time_in_force=response.time_in_force,
            latest_status=response.status,
            client_request_id=response.client_request_id,
            payload=_model_payload(response),
        )

    def _record_bracket_trade_lifecycle(
        self,
        *,
        trades: list[Trade],
        source_event_type: str,
        client_request_id: str | None,
    ) -> None:
        for index, trade in enumerate(trades):
            role = ("parent", "take_profit", "stop_loss")[index] if index < 3 else f"leg_{index}"
            open_order = self._open_order_response(trade)
            self._record_order_lifecycle(
                order_id=open_order.order_id,
                source_event_type=source_event_type,
                symbol=open_order.symbol,
                action=open_order.action,
                order_type=open_order.order_type,
                quantity=open_order.total_quantity,
                limit_price=open_order.limit_price,
                stop_price=open_order.stop_price,
                time_in_force=open_order.time_in_force,
                latest_status=open_order.status,
                client_request_id=client_request_id,
                payload={**open_order.model_dump(), "bracket_role": role},
            )

    @staticmethod
    def _record_order_lifecycle(
        *,
        order_id: str,
        source_event_type: str,
        payload: dict[str, object],
        symbol: str | None = None,
        action: str | None = None,
        order_type: str | None = None,
        quantity: float | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str | None = None,
        latest_status: str | None = None,
        client_request_id: str | None = None,
    ) -> None:
        OrderLifecycleRecord.insert(
            event_id=str(uuid4()),
            order_id=order_id,
            symbol=symbol,
            action=action,
            order_type=order_type,
            quantity=str(quantity) if quantity is not None else None,
            limit_price=str(limit_price) if limit_price is not None else None,
            stop_price=str(stop_price) if stop_price is not None else None,
            time_in_force=time_in_force,
            latest_status=latest_status,
            client_request_id=client_request_id,
            source_event_type=source_event_type,
            updated_at=datetime.now(UTC),
            payload_json=dump_json(payload),
        ).execute()

    def _record_position_snapshot(self, position: PositionResponse, *, source: str) -> None:
        PositionSnapshotRecord.insert(
            snapshot_id=str(uuid4()),
            symbol=position.symbol,
            account=position.account,
            exchange=position.exchange,
            currency=position.currency,
            position=str(position.position),
            average_cost=str(position.average_cost),
            captured_at=datetime.now(UTC),
            source=source,
        ).execute()

    def _latest_order_lifecycle_rows(self) -> list[OrderLifecycleRecord]:
        query = cast(
            ModelSelect,
            OrderLifecycleRecord.select().order_by(OrderLifecycleRecord.updated_at.desc()),
        )
        latest_by_order_id: dict[str, OrderLifecycleRecord] = {}
        for row in cast(list[OrderLifecycleRecord], list(query)):
            order_id = cast(str | None, row.order_id)
            if order_id is None or order_id in latest_by_order_id:
                continue
            latest_by_order_id[order_id] = row
        return list(latest_by_order_id.values())

    def _load_persistent_state(self) -> None:
        self._runtime.idempotency_records.clear()
        self._runtime.approval_mandates.clear()

        for row in IdempotencyRecord.select():
            try:
                response = OrderSubmissionResponse(**json.loads(row.response_json))
                self._runtime.idempotency_records[row.client_request_id] = response
            except Exception:
                continue

        for row in ApprovalMandateStore.select():
            try:
                symbols = _json_object(row.symbols_json).get("symbols", [])
                actions = _json_object(row.actions_json).get("actions", [])
                request = OrderPreviewRequest(**json.loads(row.request_json)) if row.request_json else None
                guardrails = ExecutionGuardrailsResponse(**json.loads(row.guardrails_json)) if row.guardrails_json else None
                self._runtime.approval_mandates[row.mandate_id] = ApprovalMandate(
                    mandate_id=row.mandate_id,
                    status=row.status,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                    instrument_type=InstrumentType(row.instrument_type),
                    target_mode=row.target_mode,
                    symbols=[str(symbol).upper() for symbol in symbols if isinstance(symbol, str)],
                    actions=[str(action).upper() for action in actions if isinstance(action, str)],
                    max_order_notional=float(row.max_order_notional),
                    max_uses=int(row.max_uses),
                    uses_consumed=int(row.uses_consumed),
                    note=row.note,
                    requester=row.requester,
                    approved_by=row.approved_by,
                    request=request,
                    policy_decision=row.policy_decision,
                    approval_required=bool(row.approval_required) if row.approval_required is not None else None,
                    guardrails=guardrails,
                    request_context=_json_object(row.request_context_json),
                )
            except Exception:
                continue

    def _remember_policy_block(self, response: ExecutionGuardrailsResponse) -> None:
        summary = f"{response.symbol}:{response.order_type}:{'; '.join(response.blockers[:2])}"
        self._runtime.recent_policy_blocks.appendleft(summary)
        self._audit_logger.warning("policy_block symbol=%s order_type=%s blockers=%s", response.symbol, response.order_type, response.blockers)

    @staticmethod
    def _open_order_response(trade: Trade) -> OpenOrderResponse:
        return OpenOrderResponse(
            instrument_type=TradingService._instrument_type_from_contract(trade.contract),
            order_id=str(trade.order.orderId),
            perm_id=str(trade.order.permId),
            client_id=trade.order.clientId,
            symbol=trade.contract.symbol,
            exchange=trade.contract.exchange,
            currency=trade.contract.currency,
            action=trade.order.action,
            order_type=trade.order.orderType,
            total_quantity=float(trade.order.totalQuantity),
            limit_price=TradingService._normalize_optional_float(getattr(trade.order, "lmtPrice", None)),
            stop_price=TradingService._normalize_optional_float(getattr(trade.order, "auxPrice", None)),
            time_in_force=getattr(trade.order, "tif", None),
            status=trade.orderStatus.status,
        )

    @staticmethod
    def _instrument_type_from_contract(contract) -> InstrumentType:
        sec_type = str(getattr(contract, "secType", "")).upper()
        if sec_type in {"CASH", "FOREX"}:
            return InstrumentType.FOREX
        return InstrumentType.STOCK

    @staticmethod
    def _deserialize_instrument_type(value: object) -> InstrumentType:
        if value is None:
            return InstrumentType.STOCK
        return InstrumentType(str(value).strip().lower())

    @staticmethod
    def _normalize_broker_side(side: str | None) -> str | None:
        if side == "BOT":
            return "BUY"
        if side == "SLD":
            return "SELL"
        return side

    @staticmethod
    def _format_exception_detail(exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return f"{exc.__class__.__name__}: {message}"
        return exc.__class__.__name__

    @staticmethod
    def _normalize_optional_float(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            numeric = float(value)
            if not math.isfinite(numeric):
                return None
            # IB uses extreme sentinel values for unset numeric fields such as auxPrice.
            if abs(numeric) >= 1e100:
                return None
            return numeric
        return None

    @classmethod
    def _normalize_historical_bar(cls, bar: object) -> HistoricalBarResponse:
        raw_time = getattr(bar, "date", None) or getattr(bar, "time", None)
        if isinstance(raw_time, datetime):
            time_value = raw_time.isoformat()
        else:
            time_value = str(raw_time)
        return HistoricalBarResponse(
            time=time_value,
            open=float(getattr(bar, "open", getattr(bar, "open_", 0.0))),
            high=float(getattr(bar, "high", 0.0)),
            low=float(getattr(bar, "low", 0.0)),
            close=float(getattr(bar, "close", 0.0)),
            volume=cls._normalize_optional_float(getattr(bar, "volume", None)),
            average=cls._normalize_optional_float(getattr(bar, "average", getattr(bar, "wap", None))),
            bar_count=cast(int | None, getattr(bar, "barCount", getattr(bar, "count", None))),
        )

    @staticmethod
    def _volume_weighted_average_price(bars: list[HistoricalBarResponse]) -> float | None:
        weighted_total = 0.0
        total_volume = 0.0
        for bar in bars:
            volume = bar.volume
            if volume is None or volume <= 0:
                continue
            typical_price = (bar.high + bar.low + bar.close) / 3
            weighted_total += typical_price * volume
            total_volume += volume
        if total_volume <= 0:
            return None
        return weighted_total / total_volume

    @staticmethod
    def _mid_price(bid: float | None, ask: float | None) -> float | None:
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    @staticmethod
    def _reference_price_for_order(*, snapshot: MarketSnapshotResponse, request: OrderPreviewRequest) -> float | None:
        if request.order_type == "BRACKET" and request.entry_limit_price is not None:
            return request.entry_limit_price
        if request.order_type in {"LMT", "STP LMT"}:
            return request.limit_price or request.entry_limit_price
        if request.order_type == "STP" and request.stop_price is not None:
            return request.stop_price
        if snapshot.last is not None:
            return snapshot.last
        if snapshot.mid_price is not None:
            return snapshot.mid_price
        if request.action == "BUY":
            return snapshot.ask or snapshot.close
        return snapshot.bid or snapshot.close

    @staticmethod
    def _quote_quality(*, data_mode: str, bid: float | None, ask: float | None, spread_bps: float | None, last: float | None) -> str:
        if data_mode == "unavailable":
            return "unavailable"
        if data_mode != "live":
            return "delayed"
        if bid is None or ask is None:
            return "partial"
        if spread_bps is not None and spread_bps > 25:
            return "wide"
        if last is None:
            return "partial"
        return "good"

    @staticmethod
    def _preferred_account(summary: list[BrokerAccountValue]) -> str | None:
        for item in summary:
            account = item.account
            if account and account != "All":
                return str(account)
        return None

    @staticmethod
    def _summary_value(
        summary: list[BrokerAccountValue],
        tag: str,
        *,
        account: str | None = None,
        currency: str | None = None,
    ) -> str | None:
        for item in summary:
            if item.tag != tag:
                continue
            if account is not None and item.account != account:
                continue
            if currency is not None and item.currency != currency:
                continue
            value = item.value
            if value is not None:
                return str(value)
        return None

    @classmethod
    def _summary_float(
        cls,
        summary: list[BrokerAccountValue],
        tag: str,
        *,
        account: str | None = None,
        currency: str | None = None,
    ) -> float | None:
        value = cls._summary_value(summary, tag, account=account, currency=currency)
        if value is None:
            return None
        try:
            numeric = float(value)
        except ValueError:
            return None
        return numeric if math.isfinite(numeric) else None

    @staticmethod
    def _deserialize_optional_float(value: str | None) -> float | None:
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_fill_side(side: str | None) -> str | None:
    if side == "BOT":
        return "BUY"
    if side == "SLD":
        return "SELL"
    return side


@asynccontextmanager
async def trading_service_lifespan(settings: Settings) -> AsyncIterator[TradingService]:
    service = TradingService(settings)
    await service.startup()
    try:
        yield service
    finally:
        await service.shutdown()
