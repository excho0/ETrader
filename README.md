<div align="center">
  <img src="assets/etrader-mark.png" alt="ETrader logo" width="120" height="120" />
  <h1>ETrader</h1>
  <p><strong>A self-hosted Interactive Brokers bridge for agent-assisted algorithmic trading workflows.</strong></p>
  <p>Connect trading agents to IBKR through a controlled REST API and Model Context Protocol server.</p>
</div>

ETrader is a self-hosted Interactive Brokers (IBKR) bridge and runtime for agent-assisted trading workflows. The current repository includes a FastAPI trading API with an MCP endpoint, Docker Compose profiles for IB Gateway or Trader Workstation (TWS), and NixOS modules for running the stack.

> **Status:** early development. Start with an IBKR paper account, read-only access, and order submission disabled. This software can interact with brokerage accounts; review the code and risk controls before connecting it to any account.

## What is included

- `apps/ib-bridge/`: FastAPI service exposing REST endpoints and MCP tools through one application-owned IB client session.
- `docker-compose.yml`: optional IB Gateway (`gw`), TWS (`tws`), and bridge (`mcp`) services.
- `infra/nix/`: NixOS modules for the bridge Compose project and standalone IB Gateway.
- Root `package.json`: convenience scripts for Compose and bridge development.

The `gw` and `tws` profiles represent alternative broker backends. Run one at a time. Both are joined to the bridge through the Compose network.

## Requirements

For the Compose workflow:

- Docker Engine with the Docker Compose plugin.
- An Interactive Brokers account configured for paper trading and API access.

Node.js and pnpm `10.16.1` are needed only if you want to use the root pnpm convenience scripts. The bridge's Python environment is managed with `uv`.

For the NixOS module workflow, use Nix with flakes and a NixOS host. The default dev shell also provides the project tooling through `nix develop`.

For running the bridge directly on the host, install `uv`. Node.js and pnpm `10.16.1` are needed only for the root pnpm convenience scripts.

## Quick start: paper account with Gateway

1. Clone the repository and prepare local environment files:

   ```sh
   git clone https://github.com/excho0/ETrader.git
   cd ETrader
   cp .env.example .env
   cp ib-gateway.env.example ib-gateway.env
   cp apps/ib-bridge/.env.example apps/ib-bridge/.env
   ```

2. Edit `ib-gateway.env` with your IBKR paper-account credentials. Keep the file private; runtime `.env` files are ignored by Git. Keep `TRADING_MODE=paper` and change the example VNC password.

3. In `apps/ib-bridge/.env`, use paper mode and read-only defaults while you connect and inspect account data:

   ```dotenv
   IB_TARGET_MODE=paper
   IB_PREFERRED_MODE=paper
   IB_READ_ONLY=true
   ALLOW_PAPER_ORDERS=false
   ALLOW_LIVE_ORDERS=false
   AUTH_ENABLED=true
   AUTH_AGENT_TOKEN=replace-with-a-long-random-value
   AUTH_EXECUTE_TOKEN=replace-with-a-different-long-random-value
   ```

   The example file contains the rest of the bridge settings and risk limits. The tokens above are placeholders; replace them before starting the service.

4. Start Gateway and the bridge:

   ```sh
   docker compose --profile gw --profile mcp up -d --build
   docker compose ps
   docker compose logs -f ib-gateway ib-bridge
   ```

   Wait for Gateway to finish starting and accepting API connections. The first startup may require reviewing the Gateway UI over VNC on port `5900`.

5. Check the API health endpoint and open its interactive documentation:

   ```sh
   curl -i http://localhost:8040/api/v1/health
   ```

   Open `http://localhost:8040/docs` in a browser. REST routes are under `/api/v1`; the MCP endpoint is `/mcp/` on the same service.

6. Stop the stack when finished:

   ```sh
   docker compose down --remove-orphans
   ```

The Compose service publishes the bridge on port `8040`, Gateway API on `4002`, and Gateway VNC on `5900`. The current Compose file binds published ports on all host interfaces, so configure host firewall rules and do not expose broker or VNC ports to the public internet.

## Run the bridge without Compose

This is useful when connecting the bridge to an IB Gateway or TWS instance already running on the host:

```sh
uv --directory apps/ib-bridge sync
cp apps/ib-bridge/.env.example apps/ib-bridge/.env
```

Edit the bridge environment file for your local broker endpoint, then run:

```sh
uv --directory apps/ib-bridge run uvicorn app.main:app --reload --host 127.0.0.1 --port 8040
```

The API listens on `http://localhost:8040`. By default the bridge connects to paper mode and is read-only. The command above binds the local API to loopback only.

## Choose TWS instead of Gateway

Create the TWS runtime file and configure it with paper-account credentials:

```sh
cp ib-tws.env.example ib-tws.env
docker compose --profile tws --profile mcp up -d --build
```

Stop the current profile before switching between Gateway and TWS. The bridge uses the Compose network hostnames and internal API ports when it runs as a container.

### Connect the bridge to TWS on the host

To run only the bridge in Docker and connect it to a TWS workstation running on the host, set these values in the root `.env` file:

```dotenv
IB_TWS_HOST=docker.host.internal
IB_TWS_PAPER_PORT=7497
IB_TWS_LIVE_PORT=7496
MCP_HTTP_ISSUER_URL=http://localhost:8040
MCP_HTTP_RESOURCE_SERVER_URL=http://localhost:8040
```

Then start only the bridge profile:

```sh
docker compose --profile mcp up -d --build
```

The Compose setup adds a host-gateway alias for `docker.host.internal`. Configure TWS to accept API connections from the Docker host and keep the bridge in paper and read-only mode while validating the connection.

## Environment files and persistent data

Runtime files are created from the checked-in examples and are excluded from Git:

- `.env`: Compose path and project overrides.
- `ib-gateway.env`: Gateway login and UI settings.
- `ib-tws.env`: TWS login and desktop settings.
- `apps/ib-bridge/.env`: bridge mode, authentication, broker connection, and risk settings.

Compose stores broker settings and bridge state under `data/` by default. The root `.env.example` demonstrates how to move these paths. Back up persistent state before removing it; `docker compose down` leaves it in place.

## API and MCP

The bridge serves both interfaces from one application process:

- REST: `http://localhost:8040/api/v1`
- Health: `http://localhost:8040/api/v1/health`
- OpenAPI UI: `http://localhost:8040/docs`
- MCP over HTTP: `http://localhost:8040/mcp/`

Authentication uses separate scoped tokens. `AUTH_AGENT_TOKEN` is for read, diagnostics, and preview operations; `AUTH_EXECUTE_TOKEN` also grants execution authority. Keep both secret. The local MCP auth bypass is intended only for loopback clients; review its settings before exposing the service beyond the host.

Order submission is disabled by default. Paper order submission requires deliberate configuration changes, and live orders have additional mode, permission, token, preview, and approval checks. Keep live trading disabled while evaluating the project. Risk limits are safeguards, not a guarantee against loss.

## NixOS module

The repository exports `nixosModules.etrader` for the Compose service and `nixosModules.ib-gateway` for the standalone Gateway container. A host flake can add this repository as an input and import the aggregate module:

```nix
{
  imports = [ inputs.etrader.nixosModules.etrader ];

  virtualisation.docker.enable = true;

  services.etrader.compose = {
    enable = true;
    environmentFiles = [ "/etc/etrader/compose.env" ];
    profiles = [ "gw" "mcp" ];
  };
}
```

Provide the referenced environment file on the host and configure service-specific runtime files as described above. The `gw` and `tws` backends should not be enabled together.

## Development commands

```sh
pnpm run ib-bridge:setup
pnpm run ib-bridge:test
pnpm run ib-bridge:lint
pnpm run ib-bridge:format
pnpm run ib-bridge:build
```

The Compose scripts are `compose:up`, `compose:up:mcp`, `compose:up:gw`, `compose:up:tws`, `compose:ps`, `compose:logs`, and `compose:down`. `compose:up` starts the Gateway and bridge profiles; `compose:up:mcp` starts only the bridge.

## Contributing

Issues and pull requests are welcome. Include the operating system, Docker/Compose or Nix versions, broker backend (paper mode), and relevant redacted logs. Never include account credentials, API tokens, account numbers, or unredacted trading data.

## License

ETrader's original project code is released under the [MIT License](LICENSE). Third-party images, libraries, and bundled components retain their own licenses; check their notices before redistributing them.
