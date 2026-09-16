{
  description = "Pinned minimal PipelineC + OpenXC7 synthesis environment";

  inputs = {
    openxc7.url = "github:openXC7/toolchain-nix/860ee576fbf8f29cc893561624d1e1aa044bc2e8";
    nixpkgs.follows = "openxc7/nixpkgs";
  };

  outputs = { self, openxc7, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          tc = openxc7.packages.${system};
          py = pkgs.python312Packages;

          # OpenXC7's FASM package builds the optional native ANTLR parser,
          # whose toolchain pulls Bazel into a cold build. FASM explicitly
          # supports a pure-Python textX parser fallback, which is sufficient
          # for prjxray's fasm2frames conversion used by this tool.
          fasmLite = py.buildPythonPackage rec {
            pname = "fpgatool-fasm";
            version = "0.0.2.r98.g9a73d70";
            format = "setuptools";
            # Reuse the exact source derivation already pinned by OpenXC7.
            # Selecting .src does not pull OpenXC7's native ANTLR/Bazel build.
            src = tc.fasm.src;
            propagatedBuildInputs = [ py.textx ];
            postPatch = ''
              ${pkgs.python312}/bin/python3 - <<'PY'
              from pathlib import Path

              path = Path("setup.py")
              text = path.read_text()
              text = text.replace("from Cython.Build import cythonize\n", "")
              old = """    ext_modules=[
                      CMakeExtension('parse_fasm', sourcedir='src', prefix='fasm/parser')
                  ] + cythonize("fasm/parser/antlr_to_tuple.pyx"),"""
              if old not in text:
                  raise SystemExit("expected FASM extension declaration not found")
              text = text.replace(old, "    ext_modules=[],")
              path.write_text(text)
              PY
            '';
            doCheck = false;
          };

          basys3Chipdb = pkgs.stdenv.mkDerivation {
            pname = "fpgatool-basys3-chipdb";
            version = "0.9.5";
            src = "${tc.nextpnr-xilinx}/share/nextpnr/external/prjxray-db";
            dontUnpack = true;
            buildInputs = [
              tc.prjxray
              tc.nextpnr-xilinx
              pkgs.pypy310
              pkgs.coreutils
              pkgs.findutils
              pkgs.gnused
              pkgs.gnugrep
            ];
            buildPhase = ''
              runHook preBuild
              mkdir -p "$out"
              pypy3.10 ${tc.nextpnr-xilinx}/share/nextpnr/python/bbaexport.py \
                --device xc7a35tcpg236-1 \
                --bba "$TMPDIR/xc7a35tcpg236.bba"
              bbasm -l "$TMPDIR/xc7a35tcpg236.bba" "$out/xc7a35tcpg236.bin"
              rm -f "$TMPDIR/xc7a35tcpg236.bba"
              runHook postBuild
            '';
            dontInstall = true;
          };
        in {
          fasm-lite = fasmLite;
          basys3-chipdb = basys3Chipdb;
          default = basys3Chipdb;
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          tc = openxc7.packages.${system};
          fasmLite = self.packages.${system}.fasm-lite;
          chipdb = self.packages.${system}.basys3-chipdb;
          py = pkgs.python312Packages;
          pyPkgPath = "/lib/python3.12/site-packages/";
          openxc7PythonPath = nixpkgs.lib.concatStrings [
            "${tc.prjxray}/usr/share/python3/:"
            "${fasmLite}${pyPkgPath}:"
            "${py.textx}${pyPkgPath}:"
            "${py.arpeggio}${pyPkgPath}:"
            "${py.pyyaml}${pyPkgPath}:"
            "${py.simplejson}${pyPkgPath}:"
            "${py.intervaltree}${pyPkgPath}:"
            "${py.sortedcontainers}${pyPkgPath}:"
            "${py.distutils}${pyPkgPath}:"
            "${py.jaraco-envs}${pyPkgPath}:"
            "${py.jaraco-functools}${pyPkgPath}:"
            "${py.more-itertools}${pyPkgPath}:"
            "${py.packaging}${pyPkgPath}"
          ];
        in {
          default = pkgs.mkShell {
            packages = [
              fasmLite
              tc.nextpnr-xilinx
              tc.prjxray
              pkgs.yosys
              pkgs.ghdl
              pkgs.yosys-ghdl
              pkgs.pypy310
              pkgs.python312
              py.pyyaml
              py.textx
              py.simplejson
              py.intervaltree
              chipdb
            ];
            shellHook = ''
              export NEXTPNR_XILINX_DIR=${tc.nextpnr-xilinx}
              export NEXTPNR_XILINX_PYTHON_DIR=${tc.nextpnr-xilinx}/share/nextpnr/python/
              export PRJXRAY_DB_DIR=${tc.nextpnr-xilinx}/share/nextpnr/external/prjxray-db
              export PRJXRAY_PYTHON_DIR=${tc.prjxray}/usr/share/python3/
              export PYTHONPATH="${openxc7PythonPath}''${PYTHONPATH:+:$PYTHONPATH}"
              export PYPY3=${pkgs.pypy310}/bin/pypy3.10
              export PYPELINEC_YOSYS_GHDL_PLUGIN=${pkgs.yosys-ghdl}/share/yosys/plugins/ghdl.so
              export FPGA_TOOL_PIPELINEC_PYTHON=${pkgs.python312}/bin/python3
              export FPGA_TOOL_CHIPDB_DIR=${chipdb}
            '';
          };
        });
    };
}
