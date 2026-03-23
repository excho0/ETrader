# ETrader

ETrader is the infrastructure repo for an AI-agent driven algorithmic trading stack built around OpenClaw and Interactive Brokers.

At the moment this repo exposes a Nix flake and NixOS module for booting the IB Gateway container through `virtualisation.oci-containers`. This is the base connectivity layer for agent-driven trading workflows, execution infrastructure, and future OpenClaw services.

## Scope

Current scope:
- Nix flake exposing reusable NixOS modules
- NixOS module for Interactive Brokers Gateway
- Docker-backed container startup through native NixOS `oci-containers`

Planned scope:
- OpenClaw services
- AI agent runtimes for research, execution, and monitoring
- Strategy orchestration and market data services
- Risk controls and trading automation infrastructure

## Module Usage

Import the aggregate module from a parent flake:

```nix
{
  imports = [
    inputs.etrader.nixosModules.etrader
  ];

  virtualisation.docker.enable = true;

  services.etrader.ibGateway = {
    enable = true;
    environmentFiles = [ <runtime-env-file> ];
  };
}
```

## IB Gateway

When `services.etrader.ibGateway.enable = true;` is set, the module configures a Docker-backed OCI container using:

- image: `ghcr.io/gnzsnz/ib-gateway:latest`
- API port: `4002`
- VNC port: `5900`
- `TWS_ACCEPT_INCOMING=true`
- `CLEANUP_LOGS=true`

NixOS generates the underlying systemd unit automatically via `virtualisation.oci-containers`, so no separate custom service is required for this container.

## Environment Files

Environment files should remain service-specific and should not be committed.

This repo ignores `*.env` files via [`.gitignore`](/home/void/projects/etrader/.gitignore). Keep sensitive values in a local runtime env file outside Git.

Use [ib-gateway.env.example](/home/void/projects/etrader/ib-gateway.env.example) as the template for the local runtime file.

## Development Notes

- The repo is designed to be consumed as a local flake input from the main NixOS system flake.
- `update-rebuild` in the shell config updates the `etrader` flake input together with the rest of the system.
- Additional trading services can be exposed here either as more `oci-containers` modules or as custom NixOS services where Compose-like orchestration is actually needed.
