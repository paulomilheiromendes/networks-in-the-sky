{
  description = "Networks in the Sky - student experiment template (Jupyter + NixNet)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-parts.url = "github:hercules-ci/flake-parts";
    nixnet.url = "github:birneee/nixnet";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = inputs.nixnet.supportedSystems;
      perSystem =
        { pkgs, inputs', lib, ... }:
        let
          nixnet = inputs'.nixnet.legacyPackages;

          # ------------------------------------------------------------------
          # Example NixNet experiment: ground station (west) -> aircraft relay
          # -> ground station (east). Each air link gets a one-way delay, an
          # optional random loss and a rate limit. The west station measures
          # RTT with ping and TCP throughput with iperf3.
          #
          # Results land in results/nixnet/<name>/<run>/<node>/ ; the notebook
          # reads them from there (runner.run_nixnet).
          # Replace this with your own topology and measurement.
          # ------------------------------------------------------------------
          mkRelay =
            { name, delayMs, lossPct, rateMbit }:
            let
              link = {
                inherit delayMs rateMbit;
                loss = if lossPct > 0 then { random.percent = lossPct; } else null;
              };
            in
            {
              workDir = "results/nixnet/${name}/{run}";
              arp = false;
              arpPrefill = true;
              nodePackages = with pkgs; [ coreutils iputils iperf3 ];
              nodes = {
                gs-west = {
                  networking.interfaces.veth0.ipv4 = {
                    addresses = [ { address = "10.0.0.1"; prefixLength = 24; } ];
                    routes = [ { address = "10.0.1.0"; prefixLength = 24; via = "10.0.0.2"; } ];
                  };
                  scripts.main = {
                    exec = ''
                      sleep 0.5
                      ping -c 20 -i 0.2 10.0.1.2 > ping.txt 2>&1
                      iperf3 -c 10.0.1.2 -t 5 -J > iperf3.json
                    '';
                    await = true;
                  };
                };
                aircraft = {
                  networking.interfaces = {
                    veth0.ipv4.addresses = [ { address = "10.0.0.2"; prefixLength = 24; } ];
                    veth1.ipv4.addresses = [ { address = "10.0.1.1"; prefixLength = 24; } ];
                  };
                  sysctl."net.ipv4.ip_forward" = true;
                };
                gs-east = {
                  networking.interfaces.veth0.ipv4 = {
                    addresses = [ { address = "10.0.1.2"; prefixLength = 24; } ];
                    routes = [ { address = "10.0.0.0"; prefixLength = 24; via = "10.0.1.1"; } ];
                  };
                  scripts.main.exec = "iperf3 -s > iperf3-server.log 2>&1";
                };
              };
              veths.veth0 = {
                netem = link;
                a.node = "gs-west";
                b.node = "aircraft";
              };
              veths.veth1 = {
                netem = link;
                a.node = "aircraft";
                b = { node = "gs-east"; iface = "veth0"; };
              };
            };

          # Parameter grid: one runnable experiment per point, e.g.
          #   nix run .#relay-d5-l1 1-3     (runs 01..03)
          experiments = lib.listToAttrs (
            map (
              p:
              let
                name = "relay-d${toString p.delayMs}-l${toString p.lossPct}";
              in
              lib.nameValuePair name (mkRelay (p // { inherit name; rateMbit = 50; }))
            ) (lib.cartesianProduct {
              delayMs = [ 1 5 20 ]; # one-way delay per air link [ms]; 1 ms ~ 300 km
              lossPct = [ 0 1 ];
            })
          );

          # Jupyter + analysis libraries, pinned by flake.lock.
          python = pkgs.python3.withPackages (ps: with ps; [
            jupyterlab
            ipykernel
            nbconvert
            numpy
            pandas
            matplotlib
            networkx
          ]);
        in
        {
          packages = lib.mapAttrs (_: nixnet.mkExperiment) experiments // {
            # Topology diagram: nix build .#mermaid-svg
            mermaid-svg = nixnet.mkMermaidSvg experiments."relay-d5-l0";
          };

          devShells.default = pkgs.mkShell {
            packages = [ python pkgs.git ];
            shellHook = ''
              echo "Networks in the Sky: run 'jupyter lab' to start."
            '';
          };
        };
    };
}
