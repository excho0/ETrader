from contextlib import asynccontextmanager
from typing import Literal

import anyio
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.core.config import get_settings
from app.core.security import (
    DIAGNOSTICS_SCOPE,
    EXECUTE_SCOPE,
    PREVIEW_SCOPE,
    READ_SCOPE,
    build_token_verifier,
    require_mcp_scopes,
)
from app.models.health import ReadinessResponse
from app.models.trading import (
    AccountSummaryResponse,
    AccountRiskSnapshotResponse,
    ApprovalDecisionRequest,
    ApprovalRequestResponse,
    AuditBehaviorSummaryResponse,
    AuditEventResponse,
    CashSizingRequest,
    CashSizingResponse,
    CancelAllOrdersResponse,
    ClosePositionRequest,
    ConnectivityProbeResponse,
    ExecutionReportResponse,
    ExecutionQualityResponse,
    ExecutionGuardrailsResponse,
    MarketSnapshotResponse,
    MarketSessionStatusResponse,
    MarketQuoteResponse,
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
    PortfolioRiskSnapshotResponse,
    PositionActionPlanResponse,
    PositionSnapshotResponse,
    PositionResponse,
    QualifiedStockContractResponse,
    ReducePositionRequest,
    BrokerReconciliationResponse,
    SymbolConflictResponse,
    SymbolExposureResponse,
    TradeCandidateEvaluationResponse,
)
from app.services.trading import TradingService, trading_service_lifespan

settings = get_settings()
_active_trading_service: TradingService | None = None

mcp = FastMCP(
    "etrader-trading",
    host=settings.mcp_http_host,
    port=settings.mcp_http_port,
    streamable_http_path="/",
    auth=AuthSettings(
        issuer_url=settings.mcp_http_issuer_url,
        resource_server_url=settings.mcp_http_resource_server_url,
        required_scopes=[READ_SCOPE],
    ),
    token_verifier=build_token_verifier(settings),
)


def build_mcp_server(*, secure_http: bool) -> FastMCP:
    return mcp


def build_secure_http_mcp_app():
    app = mcp.streamable_http_app()
    app.state.mcp_session_manager = mcp.session_manager
    return app


def set_active_trading_service(service: TradingService | None) -> None:
    global _active_trading_service
    _active_trading_service = service


@asynccontextmanager
async def current_trading_service():
    if _active_trading_service is not None:
        yield _active_trading_service
        return
    async with current_trading_service() as service:
        yield service

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

DIAGNOSTIC = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

EXECUTION_PREVIEW = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

EXECUTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


@mcp.tool(
    name="trading_health_ready",
    title="Trading Bridge Readiness",
    description=(
        "Return detailed readiness for the trading bridge, including current IB Gateway "
        "connectivity state, configured host and port, client ID, and managed accounts "
        "visible through the current API session."
    ),
    annotations=DIAGNOSTIC,
    structured_output=True,
    meta={
        "category": "diagnostics",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def health_ready() -> ReadinessResponse:
    """Return detailed readiness for the trading bridge, including IB connectivity state and managed accounts."""
    require_mcp_scopes(DIAGNOSTICS_SCOPE)
    async with current_trading_service() as service:
        return await service.readiness()


@mcp.tool(
    name="trading_account_summary",
    title="Account Summary",
    description=(
        "Return the full Interactive Brokers account summary across account scopes and "
        "currencies. Use this to inspect buying power, net liquidation, cash balances, "
        "and other account-level risk and capital metrics."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "portfolio",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def account_summary() -> AccountSummaryResponse:
    """Return the full Interactive Brokers account summary payload across currencies and aggregate account scopes."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_account_summary()


@mcp.tool(
    name="trading_account_risk_snapshot",
    title="Account Risk Snapshot",
    description=(
        "Return a compact risk-focused account summary with net liquidation, buying power, "
        "available funds, gross position value, open order count, and whether paper order "
        "submission is currently enabled."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "risk",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def account_risk_snapshot() -> AccountRiskSnapshotResponse:
    """Return a compact account-level risk summary optimized for trading decisions and sizing."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_account_risk_snapshot()


@mcp.tool(
    name="trading_portfolio_risk_snapshot",
    title="Portfolio Risk Snapshot",
    description="Return a portfolio-wide risk snapshot with estimated concentration and largest-position information.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "risk", "risk_tier": "safe", "side_effects": "none"},
)
async def portfolio_risk_snapshot() -> PortfolioRiskSnapshotResponse:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_portfolio_risk_snapshot()


@mcp.tool(
    name="trading_positions",
    title="Positions",
    description=(
        "Return all current portfolio positions with account, symbol, exchange, currency, "
        "position size, and average cost. Use this before proposing hedges, exits, or "
        "new orders to avoid conflicting with current exposure."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "portfolio",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def positions() -> list[PositionResponse]:
    """Return all current portfolio positions with account, symbol, exchange, currency, position size, and average cost."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_positions()


@mcp.tool(
    name="trading_connectivity_probe",
    title="Connectivity Probe",
    description=(
        "Run a connectivity probe that distinguishes raw TCP reachability from successful "
        "IB API handshake readiness. Use this to diagnose whether failures come from "
        "networking, API policy, or session-level handshake issues."
    ),
    annotations=DIAGNOSTIC,
    structured_output=True,
    meta={
        "category": "diagnostics",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def connectivity_probe() -> ConnectivityProbeResponse:
    """Run a low-level connectivity probe that distinguishes raw TCP reachability from successful IB API handshake readiness."""
    require_mcp_scopes(DIAGNOSTICS_SCOPE)
    async with current_trading_service() as service:
        return await service.probe()


@mcp.tool(
    name="trading_open_orders",
    title="Open Orders",
    description=(
        "Return all currently open orders and active trades visible through the current "
        "IB API session, including identifiers, side, quantity, order type, exchange, "
        "and current broker-reported status."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "orders",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def open_orders() -> list[OpenOrderResponse]:
    """Return all currently open orders and active trades visible through the current IB API session."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_open_orders()


@mcp.tool(
    name="trading_recent_executions",
    title="Recent Executions",
    description="Return recent broker-reported execution fills visible to the active session.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "orders", "risk_tier": "safe", "side_effects": "none"},
)
async def recent_executions() -> list[ExecutionReportResponse]:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_recent_executions()


@mcp.tool(
    name="trading_order_history",
    title="Order History",
    description="Return durable local order lifecycle history captured by the service across submissions, replacements, cancels, and fills.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "orders", "risk_tier": "safe", "side_effects": "none"},
)
async def order_history(limit: int = 50, symbol: str | None = None) -> list[OrderLifecycleEventResponse]:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_order_history(limit=limit, symbol=symbol)


@mcp.tool(
    name="trading_position_history",
    title="Position History",
    description="Return durable position snapshots recorded by the service so agents can inspect how exposure changed over time.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "portfolio", "risk_tier": "safe", "side_effects": "none"},
)
async def position_history(limit: int = 50, symbol: str | None = None) -> list[PositionSnapshotResponse]:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_position_history(limit=limit, symbol=symbol)


@mcp.tool(
    name="trading_recent_audit_events",
    title="Recent Audit Events",
    description="Return recent durable trading audit events recorded by the service.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "audit", "risk_tier": "safe", "side_effects": "none"},
)
async def recent_audit_events(limit: int = 50) -> list[AuditEventResponse]:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_recent_audit_events(limit=limit)


@mcp.tool(
    name="trading_audit_behavior_summary",
    title="Audit Behavior Summary",
    description="Summarize recent audit activity so agents or operators can inspect behavior by agent, run, strategy, or request source without querying raw events manually.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "audit", "risk_tier": "safe", "side_effects": "none"},
)
async def audit_behavior_summary(
    limit: int = 500,
    breakdown_by: Literal["agent_id", "run_id", "strategy_id", "request_source"] | None = None,
) -> AuditBehaviorSummaryResponse:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_audit_behavior_summary(limit=limit, breakdown_by=breakdown_by)


@mcp.tool(
    name="trading_order_status",
    title="Order Status",
    description="Return the last known state for a broker order id from open trades, fills, or the local order-status cache.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "orders", "risk_tier": "safe", "side_effects": "none"},
)
async def order_status(order_id: str) -> OrderStatusResponse:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_order_status(order_id)


@mcp.tool(
    name="trading_execution_quality",
    title="Execution Quality",
    description="Estimate execution quality for a filled order using persisted lifecycle data, fill price, and current market reference context.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "orders", "risk_tier": "safe", "side_effects": "none"},
)
async def execution_quality(order_id: str) -> ExecutionQualityResponse:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_execution_quality(order_id)


@mcp.tool(
    name="trading_qualify_stock_contract",
    title="Qualify Stock Contract",
    description=(
        "Resolve and validate an equity contract before requesting quotes or placing "
        "orders. Use this when exchange routing or primary exchange selection is "
        "ambiguous, especially for US stocks routed through SMART."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "contracts",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def qualify_stock_contract(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> QualifiedStockContractResponse:
    """Resolve and validate a stock contract before requesting quotes or placing orders. Use this when contract routing is ambiguous."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.qualify_symbol(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )


@mcp.tool(
    name="trading_stock_quote",
    title="Stock Quote",
    description=(
        "Fetch a stock quote from Interactive Brokers. The tool first attempts live "
        "market data and automatically falls back to delayed market data when live "
        "entitlements are unavailable. The response includes the actual data mode used."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "market_data",
        "risk_tier": "safe",
        "side_effects": "none",
        "fallback_behavior": "live_then_delayed",
    },
)
async def stock_quote(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> MarketQuoteResponse:
    """Fetch a stock quote from Interactive Brokers, automatically falling back from live to delayed market data when live entitlements are unavailable."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_stock_quote(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )


@mcp.tool(
    name="trading_market_snapshot",
    title="Market Snapshot",
    description=(
        "Return a decision-ready market snapshot for one symbol, including live or delayed "
        "data mode, bid, ask, last, close, mid price, spread, spread in basis points, and "
        "a quote-quality classification."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "market_data",
        "risk_tier": "safe",
        "side_effects": "none",
        "fallback_behavior": "live_then_delayed",
    },
)
async def market_snapshot(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> MarketSnapshotResponse:
    """Return a richer one-shot market snapshot for decision support, not just a raw quote."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_market_snapshot(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )


@mcp.tool(
    name="trading_market_session_status",
    title="Market Session Status",
    description="Return current US equities session state, including whether market or limit orders are sensible at the moment.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "market_data", "risk_tier": "safe", "side_effects": "none"},
)
async def market_session_status() -> MarketSessionStatusResponse:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_market_session_status()


@mcp.tool(
    name="trading_symbol_exposure",
    title="Symbol Exposure",
    description=(
        "Return current portfolio and open-order exposure for a symbol so an agent can "
        "see whether it is adding to a long, reducing a long, opening a short, or stacking "
        "duplicate open orders."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "risk",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def symbol_exposure(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> SymbolExposureResponse:
    """Return position plus open-order exposure for one symbol."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_symbol_exposure(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )


@mcp.tool(
    name="trading_order_conflicts",
    title="Order Conflicts",
    description="Detect duplicate-order and exposure conflicts for a proposed order before execution.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "risk", "risk_tier": "safe", "side_effects": "none"},
)
async def order_conflicts(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> SymbolConflictResponse:
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_order_conflicts(
            symbol=symbol,
            action=action,
            quantity=quantity,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )


@mcp.tool(
    name="trading_cash_sizing_advisor",
    title="Cash Sizing Advisor",
    description=(
        "Convert a cash budget or a percentage of buying power or net liquidation into a "
        "maximum whole-share quantity at a given reference price. Use this before preview "
        "or execution to avoid naive position sizing."
    ),
    annotations=READ_ONLY,
    structured_output=True,
    meta={
        "category": "sizing",
        "risk_tier": "safe",
        "side_effects": "none",
    },
)
async def cash_sizing_advisor(
    symbol: str,
    reference_price: float,
    budget_type: str,
    budget_value: float,
    current_position: float = 0,
) -> CashSizingResponse:
    """Convert a sizing budget into a maximum whole-share quantity using current account metrics."""
    require_mcp_scopes(READ_SCOPE)
    async with current_trading_service() as service:
        return await service.get_cash_sizing(
            CashSizingRequest(
                symbol=symbol,
                reference_price=reference_price,
                budget_type=budget_type,
                budget_value=budget_value,
                current_position=current_position,
            )
        )


@mcp.tool(
    name="trading_preview_market_order",
    title="Preview Market Order",
    description=(
        "Preview a market order against service guardrails without sending anything to "
        "Interactive Brokers. Use this before any execution step to validate quantity, "
        "order type, and current configuration constraints."
    ),
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={
        "category": "execution_preview",
        "risk_tier": "medium",
        "side_effects": "none",
        "requires_confirmation": False,
    },
)
async def preview_market_order(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> OrderPreviewResponse:
    """Preview a market order against trading guardrails without submitting anything to IB. Use this before any execution request."""
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.preview_order(
            OrderPreviewRequest(
                symbol=symbol,
                action=action,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                order_type="MKT",
                time_in_force="DAY",
            )
        )


@mcp.tool(
    name="trading_preview_open_position",
    title="Preview Open Position",
    description="Preview a trader-native long or short position entry using the service guardrails and execution advisor.",
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={"category": "execution_preview", "risk_tier": "medium", "side_effects": "none"},
)
async def preview_open_position(
    symbol: str,
    side: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    entry_order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "policy",
    client_request_id: str | None = None,
) -> PositionActionPlanResponse:
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.preview_open_position(
            OpenPositionRequest(
                symbol=symbol,
                side=side,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                entry_order_type=entry_order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
                client_request_id=client_request_id,
            )
        )


@mcp.tool(
    name="trading_submit_open_position",
    title="Submit Open Position",
    description="Submit a trader-native long or short position entry through the guarded execution path.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "submits_broker_order"},
)
async def submit_open_position(
    symbol: str,
    side: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    entry_order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "policy",
    client_request_id: str | None = None,
) -> OrderSubmissionResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.submit_open_position(
            OpenPositionRequest(
                symbol=symbol,
                side=side,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                entry_order_type=entry_order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
                client_request_id=client_request_id,
            )
        )


@mcp.tool(
    name="trading_preview_reduce_position",
    title="Preview Reduce Position",
    description="Preview a safe, price-controlled reduction of an existing position.",
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={"category": "execution_preview", "risk_tier": "medium", "side_effects": "none"},
)
async def preview_reduce_position(
    symbol: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    time_in_force: str = "DAY",
    client_request_id: str | None = None,
) -> PositionActionPlanResponse:
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.preview_reduce_position(
            ReducePositionRequest(
                symbol=symbol,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                time_in_force=time_in_force,
                client_request_id=client_request_id,
            )
        )


@mcp.tool(
    name="trading_submit_reduce_position",
    title="Submit Reduce Position",
    description="Submit a safe, price-controlled reduction of an existing position.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "submits_broker_order"},
)
async def submit_reduce_position(
    symbol: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    time_in_force: str = "DAY",
    client_request_id: str | None = None,
) -> OrderSubmissionResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.submit_reduce_position(
            ReducePositionRequest(
                symbol=symbol,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                time_in_force=time_in_force,
                client_request_id=client_request_id,
            )
        )


@mcp.tool(
    name="trading_execution_guardrails",
    title="Execution Guardrails",
    description=(
        "Evaluate a proposed order against service-level guardrails, current market quality, "
        "existing exposure, and open-order conflicts. Use this before any execution request."
    ),
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={
        "category": "risk_controls",
        "risk_tier": "medium",
        "side_effects": "none",
    },
)
async def execution_guardrails(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "policy",
) -> ExecutionGuardrailsResponse:
    """Check a proposed order against guardrails, market quality, and existing exposure."""
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.get_execution_guardrails(
            OrderPreviewRequest(
                symbol=symbol,
                action=action,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
            )
        )


@mcp.tool(
    name="trading_order_advisor",
    title="Order Advisor",
    description=(
        "Recommend whether a proposed stock order should be market or limit based on quote "
        "quality, spread, delayed versus live data, and current guardrails. This is a "
        "decision-support tool that does not submit anything."
    ),
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={
        "category": "execution_advice",
        "risk_tier": "medium",
        "side_effects": "none",
    },
)
async def order_advisor(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "policy",
) -> OrderAdvisorResponse:
    """Recommend a safer execution style for a proposed order based on current market conditions."""
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.advise_order(
            OrderPreviewRequest(
                symbol=symbol,
                action=action,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
            )
        )


@mcp.tool(
    name="trading_trade_candidate_evaluation",
    title="Trade Candidate Evaluation",
    description="Run market snapshot, exposure, guardrails, and advice in one decision-ready evaluation.",
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={"category": "execution_advice", "risk_tier": "medium", "side_effects": "none"},
)
async def trade_candidate_evaluation(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "policy",
) -> TradeCandidateEvaluationResponse:
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.evaluate_trade_candidate(
            OrderPreviewRequest(
                symbol=symbol,
                action=action,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
            )
        )


@mcp.tool(
    name="trading_submit_order",
    title="Submit Order",
    description=(
        "Submit a guarded paper order through Interactive Brokers only when order "
        "submission has been explicitly enabled in service configuration. Supports core "
        "order types such as MKT, LMT, and STP. This tool is side-effecting and should "
        "only be used after guardrails and preview succeed."
    ),
    annotations=EXECUTION,
    structured_output=True,
    meta={
        "category": "execution",
        "risk_tier": "high",
        "side_effects": "submits_broker_order",
        "requires_confirmation": True,
        "paper_trading_only_by_default": True,
    },
)
async def submit_order(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "policy",
) -> OrderSubmissionResponse:
    """Submit a guarded paper order using the configured execution policy and core supported order types."""
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.submit_order(
            OrderPreviewRequest(
                symbol=symbol,
                action=action,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
            )
        )


@mcp.tool(
    name="trading_create_approval_request",
    title="Create Approval Request",
    description="Create an approval request for a proposed order that should not auto-submit yet.",
    annotations=EXECUTION_PREVIEW,
    structured_output=True,
    meta={"category": "approval", "risk_tier": "medium", "side_effects": "creates_approval_record"},
)
async def create_approval_request(
    symbol: str,
    action: str,
    quantity: float,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    order_type: str = "MKT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    entry_limit_price: float | None = None,
    time_in_force: str = "DAY",
    requester: str | None = None,
    approval_mode: str = "force_approval",
) -> ApprovalRequestResponse:
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.create_approval_request(
            OrderPreviewRequest(
                symbol=symbol,
                action=action,
                quantity=quantity,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                entry_limit_price=entry_limit_price,
                time_in_force=time_in_force,
                requester=requester,
                approval_mode=approval_mode,
            )
        )


@mcp.tool(
    name="trading_get_approval_request",
    title="Get Approval Request",
    description="Fetch an approval request by id.",
    annotations=READ_ONLY,
    structured_output=True,
    meta={"category": "approval", "risk_tier": "safe", "side_effects": "none"},
)
async def get_approval_request(approval_id: str) -> ApprovalRequestResponse:
    require_mcp_scopes(PREVIEW_SCOPE)
    async with current_trading_service() as service:
        return await service.get_approval_request(approval_id)


@mcp.tool(
    name="trading_approve_request",
    title="Approve Request",
    description="Approve a pending approval request so it can later be submitted.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "approval", "risk_tier": "high", "side_effects": "approves_approval_record"},
)
async def approve_request(approval_id: str, actor: str | None = None, note: str | None = None) -> ApprovalRequestResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.approve_request(approval_id, ApprovalDecisionRequest(actor=actor, note=note))


@mcp.tool(
    name="trading_reject_request",
    title="Reject Request",
    description="Reject a pending approval request.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "approval", "risk_tier": "high", "side_effects": "rejects_approval_record"},
)
async def reject_request(approval_id: str, actor: str | None = None, note: str | None = None) -> ApprovalRequestResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.reject_request(approval_id, ApprovalDecisionRequest(actor=actor, note=note))


@mcp.tool(
    name="trading_submit_approved_request",
    title="Submit Approved Request",
    description="Submit an already-approved request through the guarded execution path.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "submits_broker_order"},
)
async def submit_approved_request(approval_id: str) -> OrderSubmissionResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.submit_approved_request(approval_id)


@mcp.tool(
    name="trading_cancel_order",
    title="Cancel Order",
    description="Cancel an open broker order by order id.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "cancels_broker_order"},
)
async def cancel_order(order_id: str) -> OrderCancellationResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.cancel_order(order_id)


@mcp.tool(
    name="trading_cancel_all_open_orders",
    title="Cancel All Open Orders",
    description="Cancel every currently open broker order visible to the app-owned trading session.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "cancels_multiple_broker_orders"},
)
async def cancel_all_open_orders() -> CancelAllOrdersResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.cancel_all_open_orders()


@mcp.tool(
    name="trading_flatten_all_positions",
    title="Flatten All Positions",
    description="Submit price-controlled close orders for every current non-zero position. Use only as an emergency flattening action.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "submits_multiple_broker_close_orders"},
)
async def flatten_all_positions() -> list[OrderSubmissionResponse]:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.flatten_all_positions()


@mcp.tool(
    name="trading_close_symbol_position",
    title="Close Symbol Position",
    description="Submit a price-controlled limit order to flatten the current position in one symbol.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "submits_broker_close_order"},
)
async def close_symbol_position(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    time_in_force: str = "DAY",
    client_request_id: str | None = None,
) -> OrderSubmissionResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.close_symbol_position(
            ClosePositionRequest(
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                time_in_force=time_in_force,
                client_request_id=client_request_id,
            )
        )


@mcp.tool(
    name="trading_replace_order",
    title="Replace Order",
    description="Modify an open broker order by order id.",
    annotations=EXECUTION,
    structured_output=True,
    meta={"category": "execution", "risk_tier": "high", "side_effects": "modifies_broker_order"},
)
async def replace_order(
    order_id: str,
    quantity: float | None = None,
    limit_price: float | None = None,
    stop_price: float | None = None,
    time_in_force: str | None = None,
) -> OrderSubmissionResponse:
    require_mcp_scopes(EXECUTE_SCOPE)
    async with current_trading_service() as service:
        return await service.replace_order(
            OrderReplaceRequest(
                order_id=order_id,
                quantity=quantity,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force,
            )
        )


@mcp.tool(
    name="trading_reconcile_broker_state",
    title="Reconcile Broker State",
    description="Compare broker open orders and positions against the local durable lifecycle history to detect drift and unknown state.",
    annotations=DIAGNOSTIC,
    structured_output=True,
    meta={"category": "diagnostics", "risk_tier": "safe", "side_effects": "none"},
)
async def reconcile_broker_state() -> BrokerReconciliationResponse:
    require_mcp_scopes(DIAGNOSTICS_SCOPE)
    async with current_trading_service() as service:
        return await service.reconcile_broker_state()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
