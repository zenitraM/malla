{
  description = "Meshcosas development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python313;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python and uv
            python
            uv

            # Playwright browsers and dependencies
            playwright-driver
            playwright-test

            #build deps
            git
            gnumake
          ];

          LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
          PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
          PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = 1;
          UV_PYTHON_PREFERENCE = "only-system";
          UV_PYTHON = "${python}";
          shellHook = ''
            ${pkgs.uv}/bin/uv sync
            # Set up the Python virtual environment with uv
            test -d .venv || ${pkgs.uv}/bin/uv venv .venv
            source .venv/bin/activate
          '';
        };
      }
    );
}
