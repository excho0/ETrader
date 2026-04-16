from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.instrument_types import InstrumentType, ensure_supported_instrument_type


class InstrumentTypeAwareModel(BaseModel):
    @field_validator("instrument_type", check_fields=False)
    @classmethod
    def validate_instrument_type(cls, value: str | InstrumentType) -> InstrumentType:
        return ensure_supported_instrument_type(value)

    @model_validator(mode="after")
    def normalize_contract_defaults(self):
        instrument_type = getattr(self, "instrument_type", None)
        exchange = getattr(self, "exchange", None)
        primary_exchange = getattr(self, "primary_exchange", None)
        currency = getattr(self, "currency", None)

        if instrument_type == InstrumentType.FOREX:
            if isinstance(exchange, str) and exchange.strip().upper() in {"", "SMART"}:
                self.exchange = "IDEALPRO"
            if primary_exchange == "":
                self.primary_exchange = None
            if isinstance(currency, str):
                self.currency = currency.strip().upper()
        return self


class InstrumentContractSpec(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    primary_exchange: str | None = None


class SupportedInstrumentTypesResponse(BaseModel):
    supported_instrument_types: list[InstrumentType]
    default_instrument_type: InstrumentType
    generic_tools_preferred: bool = True
    compatibility_wrappers: dict[str, list[str]] = {}


class QualifiedContractResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    con_id: int
    symbol: str
    exchange: str
    primary_exchange: str | None = None
    currency: str
    local_symbol: str | None = None
    trading_class: str | None = None


class PositionResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class AccountPnLResponse(BaseModel):
    account: str
    model_code: str = ""
    daily_pnl: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    source: str = "ib_pnl_subscription"


class SymbolPnLResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    account: str
    model_code: str = ""
    con_id: int
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    daily_pnl: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    position: float | None = None
    value: float | None = None
    source: str = "ib_pnl_single_subscription"


class PnLSubscriptionItem(BaseModel):
    kind: str
    account: str
    model_code: str = ""
    con_id: int | None = None


class PnLSubscriptionsResponse(BaseModel):
    subscriptions: list[PnLSubscriptionItem]


class ConnectivityProbeResponse(BaseModel):
    host: str
    port: int
    client_id: int
    tcp_reachable: bool
    ib_connected: bool
    handshake_error: str | None = None


class QualifiedStockContractResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    con_id: int
    symbol: str
    exchange: str
    primary_exchange: str | None = None
    currency: str
    local_symbol: str | None = None
    trading_class: str | None = None


class MarketQuoteResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    exchange: str
    currency: str
    data_mode: str
    quote_available: bool = True
    availability_note: str | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    close: float | None = None


class MarketSnapshotResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    data_mode: str
    quote_available: bool = True
    availability_note: str | None = None
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


class HistoricalBarResponse(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    average: float | None = None
    bar_count: int | None = None


class HistoricalBarsResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    data_mode: str = "historical"
    timeframe: str
    duration: str
    what_to_show: str
    use_rth: bool
    bar_count: int
    bars: list[HistoricalBarResponse]


class MultiTimeframeBarsResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    data_mode: str = "historical"
    what_to_show: str
    use_rth: bool
    frames: dict[str, HistoricalBarsResponse]


class LevelMapResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    data_mode: str = "historical"
    intraday_timeframe: str
    intraday_duration: str
    daily_duration: str
    what_to_show: str
    use_rth: bool
    current_price: float | None = None
    current_time: str | None = None
    session_open: float | None = None
    session_high: float | None = None
    session_low: float | None = None
    prior_close: float | None = None
    prior_day_high: float | None = None
    prior_day_low: float | None = None
    rolling_5d_high: float | None = None
    rolling_5d_low: float | None = None
    intraday_vwap: float | None = None
    intraday_bar_count: int = 0
    daily_bar_count: int = 0


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


class SymbolExposureResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class SymbolConflictResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    conflict_detected: bool
    severity: str
    reasons: list[str] = []
    current_position: float
    open_buy_quantity: float
    open_sell_quantity: float


class PortfolioRiskItem(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class CashSizingRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
    symbol: str
    reference_price: float = Field(gt=0)
    budget_type: str = Field(pattern="^(cash|buying_power_percent|net_liquidation_percent)$")
    budget_value: float = Field(gt=0)
    current_position: float = 0


class CashSizingResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    reference_price: float
    budget_type: str
    budget_value: float
    notional_budget: float
    max_whole_shares: int
    current_position: float
    projected_position: float
    warnings: list[str] = []


class PolicyProfileResponse(BaseModel):
    policy_mode: str
    connected_mode: str | None = None
    target_mode: str
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
    paper_order_submission_enabled: bool
    live_order_submission_enabled: bool


class ExecutionGuardrailsResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class OrderAdvisorResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class ApprovalDecisionRequest(BaseModel):
    note: str | None = None
    actor: str | None = None


class ApprovalMandateRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
    target_mode: str = Field(default="paper", pattern="^(paper|live|auto)$")
    symbols: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    max_order_notional: float = Field(gt=0)
    max_uses: int = Field(default=1, ge=1)
    expires_in_seconds: int | None = Field(default=None, gt=0)
    requester: str | None = None
    request_source: str | None = None
    agent_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    strategy_id: str | None = Field(default=None, min_length=1, max_length=128)


class ApprovalMandateResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    mandate_id: str
    status: str
    created_at: str
    expires_at: str
    target_mode: str
    symbols: list[str] = []
    actions: list[str] = []
    max_order_notional: float
    max_uses: int
    uses_consumed: int
    note: str | None = None
    requester: str | None = None
    approved_by: str | None = None


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


class OrderStatusResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class OrderLifecycleEventResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class PositionSnapshotResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    snapshot_id: str
    symbol: str
    account: str | None = None
    exchange: str | None = None
    currency: str | None = None
    position: float
    average_cost: float | None = None
    captured_at: str
    source: str


class ExecutionQualityResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class ExecutionReportResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    symbol: str
    side: str
    shares: float
    price: float
    time: str
    order_id: str | None = None
    perm_id: str | None = None


class OrderPreviewRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
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


class OrderPreviewResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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


class OrderSubmissionResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
    order_id: str
    status: str
    symbol: str
    action: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    time_in_force: str
    client_request_id: str | None = None
    idempotent_replay: bool = False


class ClosePositionRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
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


class OpenPositionRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
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


class ReducePositionRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
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


class PositionExitOcaRequest(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = Field(default=InstrumentType.STOCK)
    symbol: str
    quantity: float = Field(gt=0)
    take_profit_price: float = Field(gt=0)
    stop_loss_price: float = Field(gt=0)
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


class OpenOrderResponse(InstrumentTypeAwareModel):
    instrument_type: InstrumentType = InstrumentType.STOCK
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
