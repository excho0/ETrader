from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


DEFAULT_URL = "http://127.0.0.1:8040/mcp/"
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_token(env_values: dict[str, str], *, execute: bool) -> str:
    env_key = "AUTH_EXECUTE_TOKEN" if execute else "AUTH_AGENT_TOKEN"
    token = os.environ.get(env_key) or env_values.get(env_key)
    if not token:
        raise SystemExit(f"Missing {env_key}; set it in the environment or {DEFAULT_ENV_PATH}")
    return token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the ib-bridge MCP endpoint.")
    parser.add_argument("--url", default=os.environ.get("IB_BRIDGE_MCP_URL", DEFAULT_URL))
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument(
        "--no-execution",
        action="store_true",
        help="Disable side-effecting tool calls and use the agent token only.",
    )
    return parser.parse_args()


def summarize(result: Any) -> str:
    if hasattr(result, "model_dump"):
        payload = result.model_dump(mode="json")
    elif isinstance(result, dict):
        payload = result
    else:
        payload = {"result": repr(result)}
    text = json.dumps(payload, indent=2, ensure_ascii=True, default=str)
    return text if len(text) <= 1200 else text[:1200] + "\n...<truncated>"


def structured_content(result: Any) -> dict[str, Any]:
    payload = getattr(result, "structuredContent", None)
    if isinstance(payload, dict):
        return payload
    return {}


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any] | None = None) -> None:
    result = await session.call_tool(name, arguments or {})
    print(f"\n== {name} ==")
    print(summarize(result))


async def call_tool_result(session: ClientSession, name: str, arguments: dict[str, Any] | None = None):
    result = await session.call_tool(name, arguments or {})
    print(f"\n== {name} ==")
    print(summarize(result))
    return result


async def main() -> None:
    args = parse_args()
    include_execution = not args.no_execution
    env_values = load_env_file(args.env_file)
    token = resolve_token(env_values, execute=include_execution)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
        async with streamable_http_client(args.url, http_client=http_client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                print("== initialize ==")
                print(summarize(init))

                tools_result = await session.list_tools()
                tool_names = sorted(tool.name for tool in tools_result.tools)
                print("\n== tools ==")
                print(json.dumps({"count": len(tool_names), "tools": tool_names}, indent=2))

                readiness = await call_tool_result(session, "trading_health_ready", {})
                readiness_payload = getattr(readiness, "structuredContent", None) or {}
                connected_mode = readiness_payload.get("connected_mode")

                safe_calls: list[tuple[str, dict[str, Any]]] = [
                    ("trading_connectivity_probe", {}),
                    ("trading_account_risk_snapshot", {}),
                    ("trading_market_session_status", {}),
                    ("trading_positions", {}),
                    ("trading_open_orders", {}),
                    ("trading_recent_executions", {}),
                    ("trading_order_history", {"limit": 5}),
                    ("trading_position_history", {"limit": 5}),
                    ("trading_recent_audit_events", {"limit": 5}),
                    ("trading_reconcile_broker_state", {}),
                    (
                        "trading_market_snapshot",
                        {
                            "symbol": "AAPL",
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                        },
                    ),
                    (
                        "trading_symbol_exposure",
                        {
                            "symbol": "AAPL",
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                        },
                    ),
                    (
                        "trading_cash_sizing_advisor",
                        {
                            "symbol": "AAPL",
                            "reference_price": 250.0,
                            "budget_type": "buying_power_percent",
                            "budget_value": 1.0,
                            "current_position": 0,
                        },
                    ),
                    (
                        "trading_preview_open_position",
                        {
                            "symbol": "AAPL",
                            "side": "long",
                            "quantity": 1,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "entry_order_type": "LMT",
                            "limit_price": 250.0,
                            "time_in_force": "DAY",
                        },
                    ),
                    (
                        "trading_execution_guardrails",
                        {
                            "symbol": "AAPL",
                            "action": "BUY",
                            "quantity": 1,
                            "order_type": "LMT",
                            "limit_price": 250.0,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "time_in_force": "DAY",
                        },
                    ),
                    (
                        "trading_order_advisor",
                        {
                            "symbol": "AAPL",
                            "action": "BUY",
                            "quantity": 1,
                            "order_type": "LMT",
                            "limit_price": 250.0,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "time_in_force": "DAY",
                        },
                    ),
                    (
                        "trading_trade_candidate_evaluation",
                        {
                            "symbol": "AAPL",
                            "action": "BUY",
                            "quantity": 1,
                            "order_type": "LMT",
                            "limit_price": 250.0,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "time_in_force": "DAY",
                        },
                    ),
                ]

                for name, arguments in safe_calls:
                    if name not in tool_names:
                        print(f"\n== {name} ==\nmissing from server tool list")
                        continue
                    await call_tool(session, name, arguments)

                if include_execution:
                    if connected_mode == "live":
                        raise SystemExit("Refusing to run MCP execution smoke against live mode. Use --no-execution.")
                    execute_calls: list[tuple[str, dict[str, Any]]] = [
                        ("trading_cancel_all_open_orders", {}),
                        ("trading_flatten_all_positions", {}),
                    ]
                    for name, arguments in execute_calls:
                        if name not in tool_names:
                            print(f"\n== {name} ==\nmissing from server tool list")
                            continue
                        await call_tool(session, name, arguments)

                    base_id = uuid4().hex[:10]

                    submit_result = await call_tool_result(
                        session,
                        "trading_submit_order",
                        {
                            "symbol": "AAPL",
                            "action": "BUY",
                            "quantity": 1,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "order_type": "LMT",
                            "limit_price": 100.0,
                            "time_in_force": "DAY",
                            "requester": "mcp_smoke",
                            "approval_mode": "policy",
                        },
                    )
                    submit_payload = structured_content(submit_result)
                    order_id = submit_payload.get("order_id")

                    if order_id:
                        await call_tool(session, "trading_order_status", {"order_id": order_id})
                        await call_tool(
                            session,
                            "trading_replace_order",
                            {
                                "order_id": order_id,
                                "limit_price": 101.0,
                                "time_in_force": "DAY",
                            },
                        )
                        await call_tool(session, "trading_cancel_order", {"order_id": order_id})

                    approval_result = await call_tool_result(
                        session,
                        "trading_create_approval_request",
                        {
                            "symbol": "AAPL",
                            "action": "BUY",
                            "quantity": 1,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "order_type": "LMT",
                            "limit_price": 100.0,
                            "time_in_force": "DAY",
                            "requester": "mcp_smoke",
                            "approval_mode": "force_approval",
                        },
                    )
                    approval_payload = structured_content(approval_result)
                    approval_id = approval_payload.get("approval_id")
                    if approval_id:
                        await call_tool(session, "trading_get_approval_request", {"approval_id": approval_id})
                        await call_tool(
                            session,
                            "trading_approve_request",
                            {"approval_id": approval_id, "actor": "mcp_smoke", "note": "smoke approval"},
                        )
                        await call_tool(session, "trading_submit_approved_request", {"approval_id": approval_id})

                    reject_result = await call_tool_result(
                        session,
                        "trading_create_approval_request",
                        {
                            "symbol": "AAPL",
                            "action": "BUY",
                            "quantity": 1,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "order_type": "LMT",
                            "limit_price": 100.0,
                            "time_in_force": "DAY",
                            "requester": f"mcp_smoke_reject_{base_id}",
                            "approval_mode": "force_approval",
                        },
                    )
                    reject_payload = structured_content(reject_result)
                    reject_id = reject_payload.get("approval_id")
                    if reject_id:
                        await call_tool(
                            session,
                            "trading_reject_request",
                            {"approval_id": reject_id, "actor": "mcp_smoke", "note": "smoke reject"},
                        )

                    await call_tool_result(
                        session,
                        "trading_submit_open_position",
                        {
                            "symbol": "AAPL",
                            "side": "long",
                            "quantity": 1,
                            "exchange": "SMART",
                            "currency": "USD",
                            "primary_exchange": "NASDAQ",
                            "entry_order_type": "LMT",
                            "limit_price": 100.0,
                            "time_in_force": "DAY",
                            "requester": "mcp_smoke",
                        },
                    )

                    await call_tool(session, "trading_cancel_all_open_orders", {})
                    await call_tool(session, "trading_flatten_all_positions", {})


if __name__ == "__main__":
    asyncio.run(main())
