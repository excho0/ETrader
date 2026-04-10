# IB Bridge

Async-safe IB bridge and MCP layer for ETrader.

This service sits between AI agents and Interactive Brokers API backends. It is responsible for:

- connection lifecycle management
- account and position reads
- market data requests
- guarded order placement
- MCP tool exposure for agent runtimes
- versioned HTTP API boundaries
- being the single authoritative IB API client session for normal trading operations

## Run the HTTP API

```sh
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8040
```

The merged app serves:
- REST under `http://localhost:8040/api/v1`
- MCP over HTTP under `http://localhost:8040/mcp/`

## MCP access

```sh
curl -i http://localhost:8040/mcp/
```

Use the mounted MCP endpoint from the same app process. Do not run ad hoc external IB API scripts as part of normal operation. REST and MCP are intended to share one app-owned broker session.

## MCP Execution Pattern

Agents should prefer a mandate-first execution flow when they expect more than one related order to require approval.

Recommended flow:

1. Read account, exposure, and market state.
2. Run preview and guardrail tools for the intended trade shape.
3. If approval is required, create a reusable approval mandate that is scoped tightly enough for the intended batch or short execution window.
4. Approve that mandate once.
5. Continue using the normal submit tools. Matching orders will consume the approved mandate automatically until it expires or runs out of uses.

Relevant MCP tools:

- `trading_execution_guardrails`
- `trading_trade_candidate_evaluation`
- `trading_create_approval_mandate`
- `trading_get_approval_mandate`
- `trading_approve_mandate`
- `trading_reject_mandate`
- `trading_revoke_mandate`
- `trading_submit_order`
- `trading_submit_open_position`
- `trading_submit_reduce_position`

Mandates should stay narrow:

- short expiry
- explicit `target_mode`
- explicit `symbols`
- explicit `actions`
- bounded `max_order_notional`
- bounded `max_uses`

For one-off trades, create a one-use mandate with a short expiry instead of using a separate approval model.

## Environment

Typical local settings:

```sh
IB_TARGET_MODE=auto
IB_PREFERRED_MODE=live
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PAPER_PORT=4002
IB_GATEWAY_LIVE_PORT=4001
# When running TWS through the compose container on the host, use the published
# host ports 7497/7496. The compose-managed bridge container overrides these to
# the image's internal forwarded ports 7499/7498 automatically.
IB_TWS_HOST=127.0.0.1
IB_TWS_PAPER_PORT=7497
IB_TWS_LIVE_PORT=7496
IB_CLIENT_ID=11
IB_READ_ONLY=false
ALLOW_PAPER_ORDERS=true
ALLOW_LIVE_ORDERS=false
ENV=dev
AUTH_ENABLED=true
AUTH_AGENT_TOKEN=change-me-agent-token
AUTH_EXECUTE_TOKEN=change-me-execute-token
```

## Live Safety

Live order creation is blocked by default even if the bridge is connected to a live broker session.

To permit new live orders, all of the following should be true:

- `IB_TARGET_MODE=live` or the bridge actually resolves to `connected_mode=live`
- `IB_READ_ONLY=false`
- `ALLOW_LIVE_ORDERS=true`
- the execute token is used
- approval and preview flows pass
- approval mandates, if used, are scoped narrowly and reviewed before approval

Operational rule:

- `cancel`, `flatten`, and `close-position` remain the preferred emergency actions
- do not enable `ALLOW_LIVE_ORDERS` until you have completed a paper smoke pass and a live runbook review

## Authentication

The service uses a simplified scoped token model:

- `AUTH_AGENT_TOKEN`
  grants read, diagnostics, and preview capabilities
- `AUTH_EXECUTE_TOKEN`
  grants everything above plus order execution

This avoids managing a separate token per scope while still keeping execution isolated from normal agent access.

Approval tools do not bypass execute-scope protection. Creating or reading a mandate can be preview-scoped, but approving, rejecting, revoking, or submitting still requires execute authority.

## API Shape

HTTP routes are versioned under `/api/v1`.

Examples:

- `GET /api/v1/`
- `GET /api/v1/health`
- `GET /api/v1/trading/account`
- `GET /api/v1/trading/orders/open`
- `POST /api/v1/trading/orders/submit`
- `POST /api/v1/trading/orders/close-position`
- `POST /api/v1/trading/orders/approval-mandate`
- `POST /api/v1/trading/orders/approval-mandate/{mandate_id}/approve`

## Single-Client Model

The trading app should own the broker session.

- One shared IB client session is used by both REST and MCP.
- Order placement, status, cancel, replace, and exit management should go through the app.
- Separate external IB clients are acceptable only for manual debugging, not for normal automation.

This keeps order visibility, approvals, audit logging, and lifecycle management consistent.
