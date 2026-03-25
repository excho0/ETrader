{ config, lib, ... }:
let
  cfg = config.services.etrader.ibGateway;
in
{
  options.services.etrader.ibGateway = {
    enable = lib.mkEnableOption "ETrader IB Gateway container for the AI-agent trading stack";

    containerName = lib.mkOption {
      type = lib.types.str;
      default = "ib-gateway";
      description = "Container name under virtualisation.oci-containers.containers.";
    };

    image = lib.mkOption {
      type = lib.types.str;
      default = "ghcr.io/gnzsnz/ib-gateway:latest";
      description = "OCI image used for the IB Gateway container.";
    };

    autoStart = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Automatically start the container at boot.";
    };

    ports = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "4002:4002"
        "5900:5900"
      ];
      description = ''
        Port mappings for the IB Gateway container.
        Defaults expose the paper trading API and VNC access.
      '';
    };

    environmentFiles = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      example = [ /absolute/path/to/ib-gateway.env ];
      description = "Optional environment files passed to the container runtime.";
    };

    environment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = {
        TWS_SETTINGS_PATH = "/home/ibgateway/tws_settings";
        TWS_ACCEPT_INCOMING = "accept";
        CLEANUP_LOGS = "true";
      };
      description = "Environment variables passed directly to the IB Gateway container.";
    };

    volumes = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "/var/lib/etrader/ib-gateway/tws_settings:/home/ibgateway/tws_settings"
      ];
      example = [ "/srv/etrader/data/ib-gateway/tws_settings:/home/ibgateway/tws_settings" ];
      description = ''
        Volume mounts for persistent IB Gateway state. By default this mounts the
        dedicated TWS settings directory under a generic host path so UI changes and
        trusted IP settings survive container recreation without shadowing the image's
        built-in bootstrap files.
      '';
    };

    extraOptions = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "--pull=always" ];
      description = "Additional raw options passed to the OCI container backend.";
    };
  };

  config = lib.mkIf cfg.enable {
    virtualisation.oci-containers = {
      backend = lib.mkDefault "docker";
      containers.${cfg.containerName} = {
        image = cfg.image;
        autoStart = cfg.autoStart;
        ports = cfg.ports;
        environmentFiles = cfg.environmentFiles;
        environment = cfg.environment;
        volumes = cfg.volumes;
        extraOptions = cfg.extraOptions;
      };
    };
  };
}
