# ETrader

ETrader is the infrastructure repo for an AI-agent driven algorithmic trading stack built around OpenClaw and Interactive Brokers.

The repo now ships a compose-managed stack for the core runtime, plus NixOS modules to manage that compose project declaratively the same way `estudio` does.

## Scope

Current scope:
- Nix flake exposing reusable NixOS modules
- NixOS module for the ETrader docker compose stack
- Optional standalone IB Gateway NixOS module for single-container use
- Docker Compose stack for IB Gateway, trading API, and optional OpenClaw gateway
- Monorepo scaffolding for OpenClaw and future trading services
- Async trading API and MCP bridge for IB Gateway

Planned scope:
- OpenClaw services
- AI agent runtimes for research, execution, and monitoring
- Strategy orchestration and market data services
- Risk controls and trading automation infrastructure

## Monorepo Layout

The repository now follows the same top-level monorepo shape as `estudio`:

- `apps/` for runnable applications and services
- `packages/` for shared code and internal libraries
- root `package.json` for monorepo scripts
- root `pnpm-workspace.yaml` for workspace layout

The IB bridge lives in `apps/ib-bridge` and is the intended boundary between AI agents and Interactive Brokers. It uses FastAPI for HTTP, Pydantic for settings/schema enforcement, the official MCP Python SDK for agent tool exposure, and `ib_async` for async IB Gateway integration.

## Module Usage

Import the aggregate module from a parent flake:

```nix
{
  imports = [
    inputs.etrader.nixosModules.etrader
  ];

  virtualisation.docker.enable = true;

  services.etrader.compose = {
    enable = true;
    environmentFiles = [ <compose-env-file> ];
    profiles = [ "mcp" ];
  };
}
```

The compose module wraps `docker compose up -d` / `down` in a systemd-managed unit, mirroring the `estudio` pattern. By default it enables the `mcp` profile so the IB bridge and MCP endpoint come up for Codex.

## Compose Stack

The root [docker-compose.yml](/home/void/projects/etrader/docker-compose.yml) is now the preferred runtime entrypoint.

Included services:
- `ib-gateway`
- `ib-bridge`
- `openclaw-gateway` under the optional `openclaw` compose profile, pulled from the registry

Persistent runtime state is stored under the project-local `data/` tree by default:
- `data/ib-gateway/tws_settings`
- `data/openclaw/config`
- `data/openclaw/workspace`

Local workflow:

```sh
docker compose --profile mcp up -d --build
docker compose ps
docker compose logs -f
docker compose down --remove-orphans
```

Or through the root scripts:

```sh
pnpm run compose:up
pnpm run compose:up:full
pnpm run compose:ps
pnpm run compose:logs
pnpm run compose:down
```

Profile behavior:

- `compose:up` enables the `mcp` profile so `ib-bridge` starts
- `compose:up:full` enables both `mcp` and `openclaw`
- `compose:down` tears down the compose project

Compose override variables can live in a local root `.env`. Start from [`.env.example`](/home/void/projects/etrader/.env.example).

The trading bridge now runs as one app:
- REST API on `http://localhost:8040/api/v1`
- MCP over HTTP on `http://localhost:8040/mcp`

Normal trading operations should go through that single app-owned IB client session. Avoid placing routine orders from separate ad hoc IB scripts, because they fragment order visibility and lifecycle management.

## IB Gateway

The compose stack runs IB Gateway using:

- image: `ghcr.io/gnzsnz/ib-gateway:latest`
- API port: `4002`
- VNC port: `5900`
- `TWS_SETTINGS_PATH=/home/ibgateway/tws_settings`
- `TWS_ACCEPT_INCOMING=accept`
- `CLEANUP_LOGS=true`

The dedicated TWS settings directory is mounted from the repo-local
`data/ib-gateway/tws_settings` path so Gateway UI changes and persisted settings survive
container recreation without masking the image's built-in bootstrap files.

The legacy `services.etrader.ibGateway` module is still exported for cases where you want a single standalone container through `oci-containers`, but the compose stack is now the preferred path for this repo.

## Environment Files

Environment files should remain service-specific and should not be committed.

This repo ignores `*.env` files via [`.gitignore`](/home/void/projects/etrader/.gitignore). Keep sensitive values in a local runtime env file outside Git.

Use [ib-gateway.env.example](/home/void/projects/etrader/ib-gateway.env.example) as the template for the local runtime file.
Use [apps/ib-bridge/.env.example](/home/void/projects/etrader/apps/ib-bridge/.env.example) for the IB bridge env file.
Use [`.env.example`](/home/void/projects/etrader/.env.example) if you want compose-level path overrides.

For persistence:
- compose uses `data/ib-gateway/tws_settings` by default for IB Gateway settings
- the standalone Nix `services.etrader.ibGateway` module mounts the same project-local path by default
- `services.etrader.compose.dataRoot` can move the whole persistent tree elsewhere declaratively

## OpenClaw Runtime

OpenClaw is no longer vendored in this repo. The compose stack can pull it directly from the registry through:

- `OPENCLAW_IMAGE`
- `OPENCLAW_ENV_FILE`

This keeps `etrader` focused on infrastructure and the trading bridge rather than tracking the OpenClaw source tree locally.

## Trading API

Install dependencies:

```sh
pnpm run ib-bridge:setup
```

Run the trading API:

```sh
pnpm run ib-bridge:dev
```

The merged app also serves MCP:

```sh
curl -i http://localhost:8040/mcp/
```

Useful lifecycle commands:

```sh
pnpm run ib-bridge:build
pnpm run ib-bridge:start
pnpm run ib-bridge:test
pnpm run ib-bridge:lint
pnpm run ib-bridge:format
```

Key capabilities exposed by the first version:

- compact health probe
- explicit IB Gateway connect and disconnect
- account summary reads
- position reads
- stock quote lookups
- guarded order previews
- versioned routes under `/api/v1`
- MCP transport mounted under `/mcp`
- one shared broker client session for REST and MCP

The service is intentionally conservative. Real order submission is disabled by default and must be explicitly enabled through configuration.

## Dev Shell

Like `estudio`, this repo exposes a default Nix dev shell with the core tooling for the monorepo:

```sh
nix develop
```

It includes:

- `node`
- `pnpm`
- `python`
- `uv`
- `docker`
- `podman`
- `nc`

## Development Notes

- The repo is designed to be consumed as a local flake input from the main NixOS system flake.
- `update-rebuild` in the shell config updates the `etrader` flake input together with the rest of the system.
- Compose is now the preferred runtime for the repo because the stack spans multiple services.
- Additional trading services can be added to the compose project and then managed through `services.etrader.compose`.
