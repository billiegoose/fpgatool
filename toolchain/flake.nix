{
  description = "Pinned minimal PipelineC + OpenXC7 synthesis environment";

  inputs = {
    openxc7.url = "github:openXC7/toolchain-nix/9ab9e2d7f549e6665ccd2a3a94f75f1dafacf29f";
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

          # Carry the two openXC7 fixes validated by fpgatool until the pinned
          # toolchain-nix nextpnr revision contains them upstream.
          nextpnrPatched = tc.nextpnr.overrideAttrs (old: {
            patches = (old.patches or [ ]) ++ [
              ./patches/openxc7-xdc-pullup-normalization.patch
              ./patches/openxc7-mmcm-fasm-with-tests.patch
            ];
          });

          # PipelineC still emits nextpnr's legacy --pre-pack clocks.py hook.
          # Himbächel is built without Python hooks, so use a deliberately narrow
          # compatibility front-end that translates literal ctx.addClock calls
          # to native XDC create_clock constraints.
          nextpnrCompat = pkgs.runCommand "fpgatool-nextpnr-xilinx-compat" {
            nativeBuildInputs = [ pkgs.makeWrapper ];
          } ''
            mkdir -p $out/bin
            cp ${./compat/nextpnr-xilinx} $out/bin/nextpnr-xilinx
            chmod +x $out/bin/nextpnr-xilinx
            substituteInPlace $out/bin/nextpnr-xilinx \
              --replace-fail '__FPGATOOL_REAL_NEXTPNR_HIMBAECHEL__' '${nextpnrPatched}/bin/nextpnr-himbaechel'
            wrapProgram $out/bin/nextpnr-xilinx \
              --prefix PATH : ${nixpkgs.lib.makeBinPath [ pkgs.bash pkgs.python312 pkgs.coreutils ]}
          '';

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

          # Basys 3 uses the xc7a35t device alias, which shares the xc7a50t
          # Himbächel database.  Generate only that die instead of the complete
          # Artix-7 family (xc7a50t/100t/200t), while using the exact same
          # patched nextpnr generator as place-and-route.  This preserves the
          # external FPGA_TOOL_CHIPDB_DIR/xc7a35tcpg236.bin contract without
          # carrying the archived bbaexport flow or building unrelated dies.
          basys3Chipdb = pkgs.stdenv.mkDerivation {
            pname = "fpgatool-basys3-himbaechel-chipdb";
            version = nextpnrPatched.version;
            dontUnpack = true;
            nativeBuildInputs = [ pkgs.python3 ];
            buildInputs = [ nextpnrPatched ];
            buildPhase = ''
              runHook preBuild
              mkdir -p "$out"
              ${pkgs.python3}/bin/python3 \
                ${nextpnrPatched}/share/nextpnr/himbaechel/uarch/xilinx/gen/xilinx_gen.py \
                --xray "${nextpnrPatched}/share/nextpnr/external/prjxray-db/artix7" \
                --device xc7a50t \
                --bba "$TMPDIR/xc7a50t.bba"
              ${nextpnrPatched}/bin/bbasm -l \
                "$TMPDIR/xc7a50t.bba" \
                "$out/chipdb-xc7a50t.bin"
              ln -s chipdb-xc7a50t.bin "$out/xc7a35tcpg236.bin"
              rm -f "$TMPDIR/xc7a50t.bba"
              runHook postBuild
            '';
            dontInstall = true;
          };
        in {
          fasm-lite = fasmLite;
          nextpnr-patched = nextpnrPatched;
          nextpnr-compat = nextpnrCompat;
          basys3-chipdb = basys3Chipdb;
          default = basys3Chipdb;
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          tc = openxc7.packages.${system};
          nextpnrPatched = self.packages.${system}.nextpnr-patched;
          nextpnrCompat = self.packages.${system}.nextpnr-compat;
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
              nextpnrCompat
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
              export NEXTPNR_XILINX_DIR=${nextpnrCompat}
              export NEXTPNR_XILINX_PYTHON_DIR=${nextpnrPatched}/share/nextpnr
              export PRJXRAY_DB_DIR=${nextpnrPatched}/share/nextpnr/external/prjxray-db
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
