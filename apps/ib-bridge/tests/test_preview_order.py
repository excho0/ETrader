import pytest

from app.core.config import Settings
from app.core.errors import TradingValidationError
from app.core.instrument_types import InstrumentType
from app.models.trading import (
    AccountRiskSnapshotResponse,
    ApprovalDecisionRequest,
    ApprovalMandateRequest,
    MarketSnapshotResponse,
    OrderPreviewRequest,
    OrderSubmissionResponse,
    PositionExitOcaRequest,
    SymbolConflictResponse,
    SymbolExposureResponse,
)
from app.services.trading import TradingService


class StubTradingService(TradingService):
    async def get_instrument_snapshot(
        self,
        spec,
    ) -> MarketSnapshotResponse:
        return MarketSnapshotResponse(
            instrument_type=spec.instrument_type,
            symbol=spec.symbol,
            exchange=spec.exchange,
            currency=spec.currency,
            primary_exchange=spec.primary_exchange,
            data_mode="live",
            bid=100.0,
            ask=100.1,
            last=100.05,
            close=99.0,
            mid_price=100.05,
            spread=0.1,
            spread_bps=9.995002498750624,
            day_change=1.05,
            day_change_percent=1.0606060606,
            has_two_sided_market=True,
            quote_quality="good",
        )

    async def get_market_snapshot(
        self,
        *,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> MarketSnapshotResponse:
        return MarketSnapshotResponse(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
            data_mode="live",
            bid=100.0,
            ask=100.1,
            last=100.05,
            close=99.0,
            mid_price=100.05,
            spread=0.1,
            spread_bps=9.995002498750624,
            day_change=1.05,
            day_change_percent=1.0606060606,
            has_two_sided_market=True,
            quote_quality="good",
        )

    async def get_symbol_exposure(
        self,
        *,
        instrument_type: InstrumentType = InstrumentType.STOCK,
        symbol: str,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> SymbolExposureResponse:
        return SymbolExposureResponse(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
            current_position=0.0,
            average_cost=None,
            open_buy_quantity=0.0,
            open_sell_quantity=0.0,
            net_open_order_quantity=0.0,
            has_position=False,
            has_open_orders=False,
            directional_exposure="flat",
        )

    async def get_order_conflicts(
        self,
        *,
        instrument_type: InstrumentType = InstrumentType.STOCK,
        symbol: str,
        action: str,
        quantity: float,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
    ) -> SymbolConflictResponse:
        return SymbolConflictResponse(
            symbol=symbol,
            conflict_detected=False,
            severity="ok",
            reasons=[],
            current_position=0.0,
            open_buy_quantity=0.0,
            open_sell_quantity=0.0,
        )

    async def get_account_risk_snapshot(self) -> AccountRiskSnapshotResponse:
        return AccountRiskSnapshotResponse(
            account="DU123",
            base_currency="USD",
            net_liquidation=1_000_000.0,
            available_funds=1_000_000.0,
            buying_power=4_000_000.0,
            total_cash_value=1_000_000.0,
            gross_position_value=0.0,
            cushion=1.0,
            position_count=0,
            open_order_count=0,
            connected_mode="paper",
            max_order_quantity=1000.0,
            paper_order_submission_enabled=False,
            policy_mode="paper",
        )

    async def _submit_normalized_order(self, request: OrderPreviewRequest) -> OrderSubmissionResponse:
        return OrderSubmissionResponse(
            instrument_type=request.instrument_type,
            order_id="stub-1",
            status="Submitted",
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            time_in_force=request.time_in_force,
            client_request_id=request.client_request_id,
        )


@pytest.mark.asyncio
async def test_preview_requires_limit_price_for_limit_orders() -> None:
    service = StubTradingService(Settings(env="test"))

    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="AAPL",
            action="BUY",
            quantity=1,
            order_type="LMT",
        )
    )

    assert preview.eligible_for_submission is False
    assert any("limit_price" in warning for warning in preview.warnings)

@pytest.mark.asyncio
async def test_preview_market_order_reports_submission_disabled() -> None:
    service = StubTradingService(Settings(env="test", allow_paper_orders=False))

    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="AAPL",
            action="BUY",
            quantity=1,
        )
    )

    assert preview.eligible_for_submission is False


@pytest.mark.asyncio
async def test_guardrails_block_read_only_submission() -> None:
    service = StubTradingService(Settings(env="test", allow_paper_orders=True, ib_read_only=True))

    guardrails = await service.get_execution_guardrails(
        OrderPreviewRequest(
            symbol="AAPL",
            action="BUY",
            quantity=10,
            order_type="LMT",
            limit_price=100,
        )
    )

    assert guardrails.allowed is False
    assert guardrails.policy_decision == "blocked"
    assert any("read-only" in blocker for blocker in guardrails.blockers)


@pytest.mark.asyncio
async def test_guardrails_require_approval_for_large_paper_order() -> None:
    service = StubTradingService(
        Settings(
            env="test",
            allow_paper_orders=True,
            ib_read_only=False,
            risk_paper_approval_trade_notional=500,
        )
    )

    guardrails = await service.get_execution_guardrails(
        OrderPreviewRequest(
            symbol="AAPL",
            action="BUY",
            quantity=10,
            order_type="LMT",
            limit_price=100,
        )
    )

    assert guardrails.allowed is True
    assert guardrails.policy_decision == "allowed_with_approval"
    assert guardrails.approval_required is True


@pytest.mark.asyncio
async def test_guardrails_block_attached_exits_on_plain_limit_order() -> None:
    service = StubTradingService(Settings(env="test", allow_paper_orders=True, ib_read_only=False))

    guardrails = await service.get_execution_guardrails(
        OrderPreviewRequest(
            symbol="AAPL",
            action="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100,
            take_profit_price=102,
            stop_price=99,
        )
    )

    assert guardrails.allowed is False
    assert any("take_profit_price" in blocker for blocker in guardrails.blockers)
    assert any("stop_price" in blocker for blocker in guardrails.blockers)


@pytest.mark.asyncio
async def test_position_exit_oca_requires_long_position() -> None:
    service = StubTradingService(Settings(env="test", allow_paper_orders=True, ib_read_only=False))

    with pytest.raises(TradingValidationError, match="existing long position"):
        await service.submit_position_exit_oca(
            PositionExitOcaRequest(
                symbol="AAPL",
                quantity=1,
                take_profit_price=102,
                stop_loss_price=99,
            )
        )


@pytest.mark.asyncio
async def test_submit_order_blocks_live_when_live_orders_disabled() -> None:
    service = StubTradingService(
        Settings(
            env="test",
            ib_target_mode="live",
            allow_paper_orders=True,
            allow_live_orders=False,
            ib_read_only=False,
        )
    )

    with pytest.raises(TradingValidationError, match="Live order submission is disabled"):
        await service.submit_order(
            OrderPreviewRequest(
                symbol="AAPL",
                action="BUY",
                quantity=1,
                order_type="LMT",
                limit_price=100,
            )
        )


@pytest.mark.asyncio
async def test_submit_order_consumes_approved_mandate(tmp_path) -> None:
    service = StubTradingService(
        Settings(
            env="test",
            allow_paper_orders=True,
            ib_read_only=False,
            risk_paper_approval_trade_notional=500,
            data_dir=str(tmp_path / "ib-bridge"),
            database_path_paper=str(tmp_path / "paper.sqlite3"),
        )
    )
    await service.startup()
    try:
        mandate = await service.create_approval_mandate(
            ApprovalMandateRequest(
                max_order_notional=2_000,
                max_uses=2,
                target_mode="paper",
                symbols=["AAPL"],
                actions=["BUY"],
                requester="test-agent",
            )
        )
        approved = await service.approve_mandate(
            mandate.mandate_id,
            ApprovalDecisionRequest(actor="tester", note="session approval"),
        )
        assert approved.status == "approved"

        submission = await service.submit_order(
            OrderPreviewRequest(
                symbol="AAPL",
                action="BUY",
                quantity=10,
                order_type="LMT",
                limit_price=100,
                client_request_id="req-1",
            )
        )

        assert submission.order_id == "stub-1"
        mandate_after = await service.get_approval_mandate(mandate.mandate_id)
        assert mandate_after.uses_consumed == 1
        assert mandate_after.status == "approved"
    finally:
        await service.shutdown()
