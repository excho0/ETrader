{
  description = "ETrader IB Gateway NixOS module";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    {
      nixosModules = {
        ib-gateway = import ./infra/nix/modules/ib-gateway.nix;

        # Aggregate module: import this to enable access to all ETrader modules.
        etrader = { ... }: {
          imports = [
            self.nixosModules.ib-gateway
          ];
        };
      };
    };
}
