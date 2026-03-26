from fastapi import APIRouter, Depends, Query

from app.api.deps import get_trading_service
from app.core.security import (
    DIAGNOSTICS_SCOPE,
    EXECUTE_SCOPE,
    PREVIEW_SCOPE,
    READ_SCOPE,
    require_http_scopes,
)
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
    InstrumentContractSpec,
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
    QualifiedContractResponse,
    QualifiedStockContractResponse,
    ReducePositionRequest,
    BrokerReconciliationResponse,
    SymbolConflictResponse,
    SymbolExposureResponse,
    TradeCandidateEvaluationResponse,
)
from app.services.trading import TradingService

router = APIRouter(prefix="/trading", tags=["trading"])


@router.post("/connect", response_model=dict[str, str])
async def connect(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(DIAGNOSTICS_SCOPE)),
) -> dict[str, str]:
    await trading_service.ensure_connected()
    return {"status": "connected"}


@router.get("/probe", response_model=ConnectivityProbeResponse)
async def probe(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(DIAGNOSTICS_SCOPE)),
) -> ConnectivityProbeResponse:
    return await trading_service.probe()


@router.post("/disconnect", response_model=dict[str, str])
async def disconnect(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(DIAGNOSTICS_SCOPE)),
) -> dict[str, str]:
    await trading_service.disconnect()
    return {"status": "disconnected"}


@router.get("/account", response_model=AccountSummaryResponse)
async def account_summary(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> AccountSummaryResponse:
    return await trading_service.get_account_summary()


@router.get("/account/risk", response_model=AccountRiskSnapshotResponse)
async def account_risk_snapshot(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> AccountRiskSnapshotResponse:
    return await trading_service.get_account_risk_snapshot()


@router.get("/account/risk/portfolio", response_model=PortfolioRiskSnapshotResponse)
async def portfolio_risk_snapshot(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> PortfolioRiskSnapshotResponse:
    return await trading_service.get_portfolio_risk_snapshot()


@router.get("/positions", response_model=list[PositionResponse])
async def positions(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> list[PositionResponse]:
    return await trading_service.get_positions()


@router.get("/orders/open", response_model=list[OpenOrderResponse])
async def open_orders(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> list[OpenOrderResponse]:
    return await trading_service.get_open_orders()


@router.get("/orders/executions", response_model=list[ExecutionReportResponse])
async def executions(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> list[ExecutionReportResponse]:
    return await trading_service.get_recent_executions()


@router.get("/orders/history", response_model=list[OrderLifecycleEventResponse])
async def order_history(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> list[OrderLifecycleEventResponse]:
    return await trading_service.get_order_history(limit=limit, symbol=symbol)


@router.get("/positions/history", response_model=list[PositionSnapshotResponse])
async def position_history(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> list[PositionSnapshotResponse]:
    return await trading_service.get_position_history(limit=limit, symbol=symbol)


@router.get("/orders/audit", response_model=list[AuditEventResponse])
async def audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> list[AuditEventResponse]:
    return await trading_service.get_recent_audit_events(limit=limit)


@router.get("/orders/audit/summary", response_model=AuditBehaviorSummaryResponse)
async def audit_summary(
    limit: int = Query(default=500, ge=1, le=2000),
    breakdown_by: str | None = Query(default=None, pattern="^(agent_id|run_id|strategy_id|request_source)$"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> AuditBehaviorSummaryResponse:
    return await trading_service.get_audit_behavior_summary(limit=limit, breakdown_by=breakdown_by)


@router.get("/orders/status/{order_id}", response_model=OrderStatusResponse)
async def order_status(
    order_id: str,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> OrderStatusResponse:
    return await trading_service.get_order_status(order_id)


@router.get("/orders/execution-quality/{order_id}", response_model=ExecutionQualityResponse)
async def execution_quality(
    order_id: str,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> ExecutionQualityResponse:
    return await trading_service.get_execution_quality(order_id)


@router.get("/contracts/stock/{symbol}", response_model=QualifiedStockContractResponse)
async def qualify_stock_contract(
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> QualifiedStockContractResponse:
    return await trading_service.qualify_symbol(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        primary_exchange=primary_exchange,
    )


@router.get("/contracts/{instrument_type}/{symbol}", response_model=QualifiedContractResponse)
async def qualify_contract(
    instrument_type: str,
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> QualifiedContractResponse:
    return await trading_service.qualify_instrument(
        InstrumentContractSpec(
            instrument_type=instrument_type,
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
    )


@router.get("/quote/{symbol}", response_model=MarketQuoteResponse)
async def quote(
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> MarketQuoteResponse:
    return await trading_service.get_stock_quote(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        primary_exchange=primary_exchange,
    )


@router.get("/quote/{instrument_type}/{symbol}", response_model=MarketQuoteResponse)
async def instrument_quote(
    instrument_type: str,
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> MarketQuoteResponse:
    return await trading_service.get_market_quote(
        InstrumentContractSpec(
            instrument_type=instrument_type,
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
    )


@router.get("/market-snapshot/{symbol}", response_model=MarketSnapshotResponse)
async def market_snapshot(
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> MarketSnapshotResponse:
    return await trading_service.get_market_snapshot(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        primary_exchange=primary_exchange,
    )


@router.get("/market-snapshot/{instrument_type}/{symbol}", response_model=MarketSnapshotResponse)
async def instrument_market_snapshot(
    instrument_type: str,
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> MarketSnapshotResponse:
    return await trading_service.get_instrument_snapshot(
        InstrumentContractSpec(
            instrument_type=instrument_type,
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
    )


@router.get("/market-session", response_model=MarketSessionStatusResponse)
async def market_session(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> MarketSessionStatusResponse:
    return await trading_service.get_market_session_status()


@router.get("/exposure/{symbol}", response_model=SymbolExposureResponse)
async def symbol_exposure(
    symbol: str,
    primary_exchange: str | None = Query(default=None),
    currency: str = Query(default="USD"),
    exchange: str = Query(default="SMART"),
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> SymbolExposureResponse:
    return await trading_service.get_symbol_exposure(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        primary_exchange=primary_exchange,
    )


@router.post("/orders/conflicts", response_model=SymbolConflictResponse)
async def order_conflicts(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> SymbolConflictResponse:
    return await trading_service.get_order_conflicts(
        symbol=request.symbol,
        action=request.action,
        quantity=request.quantity,
        exchange=request.exchange,
        currency=request.currency,
        primary_exchange=request.primary_exchange,
    )


@router.post("/orders/cash-sizing", response_model=CashSizingResponse)
async def cash_sizing(
    request: CashSizingRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(READ_SCOPE)),
) -> CashSizingResponse:
    return await trading_service.get_cash_sizing(request)


@router.post("/orders/guardrails", response_model=ExecutionGuardrailsResponse)
async def execution_guardrails(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> ExecutionGuardrailsResponse:
    return await trading_service.get_execution_guardrails(request)


@router.post("/orders/advice", response_model=OrderAdvisorResponse)
async def order_advice(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> OrderAdvisorResponse:
    return await trading_service.advise_order(request)


@router.post("/orders/evaluate", response_model=TradeCandidateEvaluationResponse)
async def evaluate_trade_candidate(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> TradeCandidateEvaluationResponse:
    return await trading_service.evaluate_trade_candidate(request)


@router.post("/orders/preview", response_model=OrderPreviewResponse)
async def preview_order(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> OrderPreviewResponse:
    return await trading_service.preview_order(request)


@router.post("/positions/open/preview", response_model=PositionActionPlanResponse)
async def preview_open_position(
    request: OpenPositionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> PositionActionPlanResponse:
    return await trading_service.preview_open_position(request)


@router.post("/positions/open", response_model=OrderSubmissionResponse)
async def submit_open_position(
    request: OpenPositionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    return await trading_service.submit_open_position(request)


@router.post("/positions/reduce/preview", response_model=PositionActionPlanResponse)
async def preview_reduce_position(
    request: ReducePositionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> PositionActionPlanResponse:
    return await trading_service.preview_reduce_position(request)


@router.post("/positions/reduce", response_model=OrderSubmissionResponse)
async def submit_reduce_position(
    request: ReducePositionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    return await trading_service.submit_reduce_position(request)


@router.post("/orders/submit", response_model=OrderSubmissionResponse)
async def submit_order(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    return await trading_service.submit_order(request)


@router.post("/orders/approval", response_model=ApprovalRequestResponse)
async def create_approval(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> ApprovalRequestResponse:
    return await trading_service.create_approval_request(request)


@router.get("/orders/approval/{approval_id}", response_model=ApprovalRequestResponse)
async def get_approval(
    approval_id: str,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(PREVIEW_SCOPE)),
) -> ApprovalRequestResponse:
    return await trading_service.get_approval_request(approval_id)


@router.post("/orders/approval/{approval_id}/approve", response_model=ApprovalRequestResponse)
async def approve_order(
    approval_id: str,
    request: ApprovalDecisionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> ApprovalRequestResponse:
    return await trading_service.approve_request(approval_id, request)


@router.post("/orders/approval/{approval_id}/reject", response_model=ApprovalRequestResponse)
async def reject_order(
    approval_id: str,
    request: ApprovalDecisionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> ApprovalRequestResponse:
    return await trading_service.reject_request(approval_id, request)


@router.post("/orders/approval/{approval_id}/submit", response_model=OrderSubmissionResponse)
async def submit_approved_order(
    approval_id: str,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    return await trading_service.submit_approved_request(approval_id)


@router.post("/orders/cancel/{order_id}", response_model=OrderCancellationResponse)
async def cancel_order(
    order_id: str,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderCancellationResponse:
    return await trading_service.cancel_order(order_id)


@router.post("/orders/cancel-all", response_model=CancelAllOrdersResponse)
async def cancel_all_orders(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> CancelAllOrdersResponse:
    return await trading_service.cancel_all_open_orders()


@router.post("/orders/flatten-all", response_model=list[OrderSubmissionResponse])
async def flatten_all_positions(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> list[OrderSubmissionResponse]:
    return await trading_service.flatten_all_positions()


@router.post("/orders/close-position", response_model=OrderSubmissionResponse)
async def close_position(
    request: ClosePositionRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    return await trading_service.close_symbol_position(request)


@router.post("/orders/replace", response_model=OrderSubmissionResponse)
async def replace_order(
    request: OrderReplaceRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    return await trading_service.replace_order(request)


@router.post("/orders/submit-market", response_model=OrderSubmissionResponse)
async def submit_market_order_compat(
    request: OrderPreviewRequest,
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(EXECUTE_SCOPE)),
) -> OrderSubmissionResponse:
    market_request = request.model_copy(update={"order_type": "MKT"})
    return await trading_service.submit_order(market_request)


@router.get("/broker/reconcile", response_model=BrokerReconciliationResponse)
async def reconcile_broker(
    trading_service: TradingService = Depends(get_trading_service),
    _: object = Depends(require_http_scopes(DIAGNOSTICS_SCOPE)),
) -> BrokerReconciliationResponse:
    return await trading_service.reconcile_broker_state()
