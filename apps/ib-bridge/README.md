# IB Bridge

Async-safe IB bridge and MCP layer for ETrader.

This service sits between AI agents and Interactive Brokers Gateway. It is responsible for:

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

## Environment

Typical local settings:

```sh
IB_HOST=127.0.0.1
IB_TARGET_MODE=auto
IB_PREFERRED_MODE=live
IB_PAPER_PORT=4002
IB_LIVE_PORT=4001
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

## API Shape

HTTP routes are versioned under `/api/v1`.

Examples:

- `GET /api/v1/`
- `GET /api/v1/health`
- `GET /api/v1/trading/account`
- `GET /api/v1/trading/orders/open`
- `POST /api/v1/trading/orders/submit`
- `POST /api/v1/trading/orders/close-position`

## Single-Client Model

The trading app should own the broker session.

- One shared IB client session is used by both REST and MCP.
- Order placement, status, cancel, replace, and exit management should go through the app.
- Separate external IB clients are acceptable only for manual debugging, not for normal automation.

This keeps order visibility, approvals, audit logging, and lifecycle management consistent.
