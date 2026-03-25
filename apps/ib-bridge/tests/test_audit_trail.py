from pathlib import Path

import pytest

from app.core.config import Settings
from app.db import database, initialize_database
from app.models.trading import OrderPreviewRequest
from app.services.trading import TradingService


@pytest.mark.asyncio
async def test_audit_trail_persists_execution_context(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    initialize_database(str(db_path))
    service = TradingService(Settings(env="test", data_dir=str(tmp_path)))

    request = OrderPreviewRequest(
        symbol="AAPL",
        action="BUY",
        quantity=1,
        order_type="LMT",
        limit_price=100,
        requester="agent:alpha",
        request_source="mcp",
        agent_id="alpha",
        run_id="run-001",
        strategy_id="mean-revert-v1",
        client_request_id="ctx-001",
    )

    await service._write_audit_event(
        "order_submitted",
        {
            **service._audit_context_from_request(request),
            "symbol": request.symbol,
            "client_request_id": request.client_request_id,
            "response": {
                "order_id": "123",
                "status": "Submitted",
                "symbol": request.symbol,
                "client_request_id": request.client_request_id,
            },
        },
    )

    events = await service.get_recent_audit_events(limit=10)
    assert len(events) == 1
    event = events[0]
    assert event.requester == "agent:alpha"
    assert event.request_source == "mcp"
    assert event.agent_id == "alpha"
    assert event.run_id == "run-001"
    assert event.strategy_id == "mean-revert-v1"
    assert event.order_id == "123"

    summary = await service.get_audit_behavior_summary(limit=10, breakdown_by="agent_id")
    assert summary.total_events == 1
    assert summary.submitted_orders == 1
    assert summary.unique_agents == 1
    assert summary.breakdown_dimension == "agent_id"
    assert len(summary.breakdown) == 1
    assert summary.breakdown[0].key == "alpha"
    assert summary.breakdown[0].submitted_orders == 1

    if not database.is_closed():
        database.close()
