import pytest

from app.core.config import Settings
from app.core.errors import TradingValidationError
from app.models.trading import (
    AccountRiskSnapshotResponse,
    MarketSnapshotResponse,
    OrderPreviewRequest,
    SymbolConflictResponse,
    SymbolExposureResponse,
)
from app.services.trading import TradingService


class StubTradingService(TradingService):
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
