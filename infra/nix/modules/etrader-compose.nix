{ config, lib, pkgs, ... }:
let
  cfg = config.services.etrader.compose;

  resolveComposeFile = file:
    if lib.hasPrefix "/" file then file else "${cfg.repoPath}/${file}";

  resolvedComposeFiles = map resolveComposeFile cfg.composeFiles;
  composeFileArgs = lib.concatMapStringsSep " " (f: "-f ${lib.escapeShellArg f}") resolvedComposeFiles;
  projectArg = lib.optionalString (cfg.projectName != null)
    "--project-name ${lib.escapeShellArg cfg.projectName}";
  extraArgs = lib.concatStringsSep " " cfg.extraArgs;

  upArgs =
    lib.concatStringsSep " " ([
      composeFileArgs
      projectArg
      "up -d"
    ]
    ++ lib.optional cfg.pullOnStart "--pull always"
    ++ lib.optional cfg.buildOnStart "--build"
    ++ lib.optional cfg.removeOrphans "--remove-orphans"
    ++ lib.optional (extraArgs != "") extraArgs);

  downArgs =
    lib.concatStringsSep " " ([
      composeFileArgs
      projectArg
      "down"
      "--remove-orphans"
    ] ++ lib.optional (extraArgs != "") extraArgs);

  runtimeInputs =
    if cfg.runtime == "podman"
    then [ pkgs.podman pkgs.podman-compose pkgs.coreutils pkgs.bash ]
    else [ pkgs.docker pkgs.coreutils pkgs.bash ];

  runtimeExec =
    if cfg.runtime == "podman"
    then "${pkgs.podman-compose}/bin/podman-compose"
    else "${pkgs.docker}/bin/docker compose";

  composeFilesCheckSnippet = lib.concatMapStringsSep "\n" (f: ''
    if [ ! -f ${lib.escapeShellArg f} ]; then
      echo "Missing compose file: ${f}" >&2
      exit 1
    fi
  '') resolvedComposeFiles;

  composeUpScript = pkgs.writeShellApplication {
    name = "etrader-compose-up";
    inherit runtimeInputs;
    text = ''
      set -euo pipefail

      if [ ! -d ${lib.escapeShellArg cfg.repoPath} ]; then
        echo "repoPath does not exist: ${cfg.repoPath}" >&2
        exit 1
      fi

      cd ${lib.escapeShellArg cfg.repoPath}
      ${composeFilesCheckSnippet}
      exec ${runtimeExec} ${upArgs}
    '';
  };

  composeDownScript = pkgs.writeShellApplication {
    name = "etrader-compose-down";
    inherit runtimeInputs;
    text = ''
      set -euo pipefail

      if [ ! -d ${lib.escapeShellArg cfg.repoPath} ]; then
        echo "repoPath does not exist: ${cfg.repoPath}" >&2
        exit 1
      fi

      cd ${lib.escapeShellArg cfg.repoPath}
      ${composeFilesCheckSnippet}
      exec ${runtimeExec} ${downArgs}
    '';
  };
in
{
  options.services.etrader.compose = {
    enable = lib.mkEnableOption "ETrader compose stack as a systemd-managed service";

    runtime = lib.mkOption {
      type = lib.types.enum [ "docker" "podman" ];
      default = "docker";
      description = ''
        Container runtime for compose execution.
        - `docker`: uses `docker compose`
        - `podman`: uses `podman-compose`
      '';
    };

    repoPath = lib.mkOption {
      type = lib.types.str;
      default = "/home/USER/projects/etrader";
      example = "/srv/etrader";
      description = "Absolute path to the ETrader repository containing compose files.";
    };

    composeFiles = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "docker-compose.yml" ];
      example = [ "docker-compose.yml" ];
      description = "Compose files in merge order. Relative values are resolved from `repoPath`.";
    };

    dataRoot = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.repoPath}/data";
      example = "/var/lib/etrader";
      description = ''
        Root directory for persistent compose-mounted data such as IB Gateway settings
        and OpenClaw state.
      '';
    };

    projectName = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = "etrader";
      description = "Optional compose project name override.";
    };

    pullOnStart = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Run compose startup with image pull (`--pull always`).";
    };

    buildOnStart = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Run compose startup with build (`--build`).";
    };

    removeOrphans = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Remove orphan services during compose startup.";
    };

    extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Additional raw arguments appended to both up/down commands.";
    };

    environmentFiles = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      example = [ "/run/secrets/etrader-compose.env" ];
      description = "Optional systemd `EnvironmentFile=` entries loaded for the compose unit.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.composeFiles != [ ];
        message = "services.etrader.compose.composeFiles must contain at least one compose file.";
      }
      {
        assertion = lib.hasPrefix "/" cfg.repoPath;
        message = "services.etrader.compose.repoPath must be an absolute path.";
      }
      {
        assertion = lib.hasPrefix "/" cfg.dataRoot;
        message = "services.etrader.compose.dataRoot must be an absolute path.";
      }
      {
        assertion = cfg.runtime != "docker" || config.virtualisation.docker.enable;
        message = "services.etrader.compose.runtime = \"docker\" requires virtualisation.docker.enable = true.";
      }
      {
        assertion = cfg.runtime != "podman" || config.virtualisation.podman.enable;
        message = "services.etrader.compose.runtime = \"podman\" requires virtualisation.podman.enable = true.";
      }
    ];

    systemd.services.etrader-compose = {
      description = "ETrader Compose Stack";

      after =
        [ "network-online.target" ]
        ++ lib.optional (cfg.runtime == "docker") "docker.service"
        ++ lib.optional (cfg.runtime == "podman") "podman.service";

      wants =
        [ "network-online.target" ]
        ++ lib.optional (cfg.runtime == "docker") "docker.service"
        ++ lib.optional (cfg.runtime == "podman") "podman.service";

      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        WorkingDirectory = cfg.repoPath;
        ExecStart = "${composeUpScript}/bin/etrader-compose-up";
        ExecStop = "${composeDownScript}/bin/etrader-compose-down";
        Environment = [
          "IB_GATEWAY_DATA_DIR=${cfg.dataRoot}/ib-gateway/tws_settings"
          "OPENCLAW_CONFIG_DIR=${cfg.dataRoot}/openclaw/config"
          "OPENCLAW_WORKSPACE_DIR=${cfg.dataRoot}/openclaw/workspace"
        ];
        EnvironmentFile = cfg.environmentFiles;
      };
    };
  };
}
