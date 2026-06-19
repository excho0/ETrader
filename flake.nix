{
  description = "ETrader infrastructure for AI-agent algo trading with IB Gateway";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };
      runtimeLibs = with pkgs; [
        stdenv.cc.cc.lib
        zlib
        openssl
      ];
      runtimeLibraryPath = pkgs.lib.makeLibraryPath runtimeLibs;
    in
    {
      nixosModules = {
        ib-gateway = import ./infra/nix/modules/ib-gateway.nix;
        compose = import ./infra/nix/modules/etrader-compose.nix;

        # Aggregate module: import this to enable access to all ETrader infrastructure modules.
        etrader = { ... }: {
          imports = [
            self.nixosModules.ib-gateway
            self.nixosModules.compose
          ];
        };
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          nodejs_24
          pnpm
          python312
          uv
          git
          docker
          docker-compose
          podman
          netcat-openbsd
        ];

        buildInputs = runtimeLibs;

        LD_LIBRARY_PATH = runtimeLibraryPath;
        NIX_LD_LIBRARY_PATH = runtimeLibraryPath;

        shellHook = ''
          if [ -t 1 ]; then
            echo "ETrader dev shell loaded."
            echo "- Node: $(node --version 2>/dev/null || true)"
            echo "- Python: $(python --version 2>/dev/null || true)"
            echo "- uv: $(uv --version 2>/dev/null || true)"
            echo "- pnpm: $(pnpm --version 2>/dev/null || true)"
          fi
        '';
      };
    };
}
