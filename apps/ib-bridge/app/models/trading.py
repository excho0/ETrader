from pydantic import BaseModel, Field


class PositionResponse(BaseModel):
    account: str
    symbol: str
    exchange: str
    currency: str
    position: float
    average_cost: float


class AccountValue(BaseModel):
    tag: str
    value: str
    currency: str
    account: str


class AccountSummaryResponse(BaseModel):
    account_values: list[AccountValue]


class ConnectivityProbeResponse(BaseModel):
    host: str
    port: int
    client_id: int
    tcp_reachable: bool
    ib_connected: bool
    handshake_error: str | None = None


class QualifiedStockContractResponse(BaseModel):
    con_id: int
    symbol: str
    exchange: str
    primary_exchange: str | None = None
    currency: str
    local_symbol: str | None = None
    trading_class: str | None = None


class MarketQuoteResponse(BaseModel):
    symbol: str
    exchange: str
    currency: str
    data_mode: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    close: float | None = None


class MarketSnapshotResponse(BaseModel):
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    data_mode: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    close: float | None = None
    mid_price: float | None = None
    spread: float | None = None
    spread_bps: float | None = None
    day_change: float | None = None
    day_change_percent: float | None = None
    has_two_sided_market: bool
    quote_quality: str


class AccountRiskSnapshotResponse(BaseModel):
    account: str | None = None
    base_currency: str | None = None
    net_liquidation: float | None = None
    available_funds: float | None = None
    buying_power: float | None = None
    total_cash_value: float | None = None
    gross_position_value: float | None = None
    cushion: float | None = None
    position_count: int
    open_order_count: int
    connected_mode: str | None = None
    max_order_quantity: float
    paper_order_submission_enabled: bool
    policy_mode: str | None = None


class SymbolExposureResponse(BaseModel):
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    current_position: float
    average_cost: float | None = None
    open_buy_quantity: float
    open_sell_quantity: float
    net_open_order_quantity: float
    has_position: bool
    has_open_orders: bool
    directional_exposure: str


class SymbolConflictResponse(BaseModel):
    symbol: str
    conflict_detected: bool
    severity: str
    reasons: list[str] = []
    current_position: float
    open_buy_quantity: float
    open_sell_quantity: float


class PortfolioRiskItem(BaseModel):
    symbol: str
    currency: str
    position: float
    average_cost: float
    estimated_mark_price: float | None = None
    estimated_notional: float | None = None
    concentration_percent: float | None = None


class PortfolioRiskSnapshotResponse(BaseModel):
    account: str | None = None
    net_liquidation: float | None = None
    total_gross_notional: float | None = None
    largest_position_symbol: str | None = None
    largest_position_notional: float | None = None
    largest_position_concentration_percent: float | None = None
    items: list[PortfolioRiskItem]


class CashSizingRequest(BaseModel):
    symbol: str
    reference_price: float = Field(gt=0)
    budget_type: str = Field(pattern="^(cash|buying_power_percent|net_liquidation_percent)$")
    budget_value: float = Field(gt=0)
    current_position: float = 0


class CashSizingResponse(BaseModel):
    symbol: str
    reference_price: float
    budget_type: str
    budget_value: float
    notional_budget: float
    max_whole_shares: int
    current_position: float
    projected_position: float
    warnings: list[str] = []


class ExecutionGuardrailsResponse(BaseModel):
    symbol: str
    action: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str
    allowed: bool
    policy_decision: str
    approval_required: bool
    severity: str
    warnings: list[str] = []
    blockers: list[str] = []
    checks: list[str] = []
    estimated_notional: float | None = None
    estimated_resulting_position_notional: float | None = None
    concentration_after_trade_percent: float | None = None
    execution_quality: str | None = None


class OrderAdvisorResponse(BaseModel):
    symbol: str
    action: str
    quantity: float
    recommended_order_type: str
    suggested_limit_price: float | None = None
    reference_price: float | None = None
    data_mode: str
    approval_required: bool = False
    rationale: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []


class TradeCandidateEvaluationResponse(BaseModel):
    market_snapshot: MarketSnapshotResponse
    symbol_exposure: SymbolExposureResponse
    guardrails: ExecutionGuardrailsResponse
    advice: OrderAdvisorResponse


class ApprovalRequestResponse(BaseModel):
    approval_id: str
    status: str
    created_at: str
    expires_at: str
    request: "OrderPreviewRequest"
    policy_decision: str
    approval_required: bool
    guardrails: ExecutionGuardrailsResponse
    note: str | None = None
    requester: str | None = None


class ApprovalDecisionRequest(BaseModel):
    note: str | None = None
    actor: str | None = None


class AuditEventResponse(BaseModel):
    event_id: str
    event_type: str
    created_at: str
    actor: str | None = None
    requester: str | None = None
    request_source: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    strategy_id: str | None = None
    symbol: str | None = None
    order_id: str | None = None
    client_request_id: str | None = None
    approval_id: str | None = None
    status: str | None = None
    policy_decision: str | None = None
    payload: dict[str, object]


class AuditBehaviorBreakdownItem(BaseModel):
    key: str
    total_events: int
    submitted_orders: int
    approvals_created: int
    approvals_approved: int
    approvals_rejected: int
    policy_block_events: int
    unique_symbols: list[str] = []


class AuditBehaviorSummaryResponse(BaseModel):
    total_events: int
    submitted_orders: int
    approvals_created: int
    approvals_approved: int
    approvals_rejected: int
    policy_block_events: int
    unique_agents: int
    unique_runs: int
    unique_strategies: int
    unique_symbols: list[str] = []
    top_event_types: dict[str, int] = {}
    breakdown_dimension: str | None = None
    breakdown: list[AuditBehaviorBreakdownItem] = []


class OrderReplaceRequest(BaseModel):
    order_id: str
    quantity: float | None = Field(default=None, gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    time_in_force: str | None = Field(default=None, pattern="^(DAY|GTC)$")


class OrderCancellationResponse(BaseModel):
    order_id: str
    status: str


class CancelAllOrdersResponse(BaseModel):
    canceled_order_ids: list[str]
    count: int


class OrderStatusResponse(BaseModel):
    order_id: str
    status: str
    symbol: str | None = None
    action: str | None = None
    order_type: str | None = None
    quantity: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str | None = None
    source: str
    message: str | None = None


class OrderLifecycleEventResponse(BaseModel):
    event_id: str
    order_id: str
    symbol: str | None = None
    action: str | None = None
    order_type: str | None = None
    quantity: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str | None = None
    latest_status: str | None = None
    client_request_id: str | None = None
    source_event_type: str
    updated_at: str
    payload: dict[str, object]


class MarketSessionStatusResponse(BaseModel):
    market: str
    timezone: str
    current_time: str
    session: str
    is_open: bool
    allows_market_orders: bool
    allows_limit_orders: bool
    next_session_transition: str | None = None


class BrokerReconciliationResponse(BaseModel):
    connected: bool
    connected_mode: str | None = None
    broker_open_order_count: int
    broker_position_count: int
    unknown_broker_order_ids: list[str] = []
    stale_local_active_order_ids: list[str] = []
    unexpected_position_symbols: list[str] = []
    healthy: bool
    summary: list[str] = []


class PositionSnapshotResponse(BaseModel):
    snapshot_id: str
    symbol: str
    account: str | None = None
    exchange: str | None = None
    currency: str | None = None
    position: float
    average_cost: float | None = None
    captured_at: str
    source: str


class ExecutionQualityResponse(BaseModel):
    order_id: str
    symbol: str
    action: str | None = None
    order_type: str | None = None
    quantity: float | None = None
    submitted_limit_price: float | None = None
    fill_price: float | None = None
    reference_price: float | None = None
    estimated_slippage: float | None = None
    estimated_slippage_bps: float | None = None
    data_mode: str | None = None
    quality: str
    notes: list[str] = []


class ExecutionReportResponse(BaseModel):
    symbol: str
    side: str
    shares: float
    price: float
    time: str
    order_id: str | None = None
    perm_id: str | None = None


class OrderPreviewRequest(BaseModel):
    symbol: str
    action: str = Field(pattern="^(BUY|SELL)$")
    quantity: float = Field(gt=0)
    position_intent: str = Field(default="auto", pattern="^(auto|reduce|open_short)$")
    exchange: str = "SMART"
    currency: str = "USD"
    primary_exchange: str | None = None
    order_type: str = Field(default="MKT", pattern="^(MKT|LMT|STP|STP LMT|BRACKET)$")
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    entry_limit_price: float | None = Field(default=None, gt=0)
    time_in_force: str = Field(default="DAY", pattern="^(DAY|GTC)$")
    requester: str | None = None
    request_source: str | None = None
    agent_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    strategy_id: str | None = Field(default=None, min_length=1, max_length=128)
    approval_mode: str = Field(default="policy", pattern="^(policy|force_approval)$")
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class OrderPreviewResponse(BaseModel):
    symbol: str
    action: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    entry_limit_price: float | None = None
    time_in_force: str
    warnings: list[str] = []
    eligible_for_submission: bool


class OrderSubmissionResponse(BaseModel):
    order_id: str
    status: str
    symbol: str
    action: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str
    client_request_id: str | None = None
    idempotent_replay: bool = False


class ClosePositionRequest(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    primary_exchange: str | None = None
    time_in_force: str = Field(default="DAY", pattern="^(DAY|GTC)$")
    requester: str | None = None
    request_source: str | None = None
    agent_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    strategy_id: str | None = Field(default=None, min_length=1, max_length=128)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class OpenPositionRequest(BaseModel):
    symbol: str
    side: str = Field(pattern="^(long|short)$")
    quantity: float = Field(gt=0)
    exchange: str = "SMART"
    currency: str = "USD"
    primary_exchange: str | None = None
    entry_order_type: str = Field(default="MKT", pattern="^(MKT|LMT|STP|STP LMT|BRACKET)$")
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    entry_limit_price: float | None = Field(default=None, gt=0)
    time_in_force: str = Field(default="DAY", pattern="^(DAY|GTC)$")
    requester: str | None = None
    request_source: str | None = None
    agent_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    strategy_id: str | None = Field(default=None, min_length=1, max_length=128)
    approval_mode: str = Field(default="policy", pattern="^(policy|force_approval)$")
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ReducePositionRequest(BaseModel):
    symbol: str
    quantity: float = Field(gt=0)
    exchange: str = "SMART"
    currency: str = "USD"
    primary_exchange: str | None = None
    time_in_force: str = Field(default="DAY", pattern="^(DAY|GTC)$")
    requester: str | None = None
    request_source: str | None = None
    agent_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    strategy_id: str | None = Field(default=None, min_length=1, max_length=128)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class PositionActionPlanResponse(BaseModel):
    normalized_order: OrderPreviewRequest
    preview: OrderPreviewResponse
    guardrails: ExecutionGuardrailsResponse
    advice: OrderAdvisorResponse


class OpenOrderResponse(BaseModel):
    order_id: str
    perm_id: str
    client_id: int
    symbol: str
    exchange: str
    currency: str
    action: str
    order_type: str
    total_quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str | None = None
    status: str


ApprovalRequestResponse.model_rebuild()
