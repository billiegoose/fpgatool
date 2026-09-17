from pathlib import Path
import importlib.util
import json
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fpgatool", ROOT / "fpgatool.py")
fpgatool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fpgatool)


class FPGAToolTests(unittest.TestCase):
    def test_pins_and_part_live_in_board_profile(self):
        board = fpgatool.board_config("basys3")
        self.assertEqual(board["fpga"]["part"], "xc7a35tcpg236-1")
        self.assertEqual(board["fpga"]["chipdb"], "xc7a35tcpg236.bin")
        self.assertEqual(board["backend"]["type"], "pipelinec-openxc7")

    def test_load_is_volatile_and_program_is_persistent(self):
        board = fpgatool.board_config("basys3")
        with mock.patch.object(fpgatool, "require_tool", return_value="/usr/bin/openFPGALoader"):
            load = fpgatool.openfpgaloader_command(board, Path("demo.bit"), persistent=False)
            program = fpgatool.openfpgaloader_command(board, Path("demo.bit"), persistent=True)
        self.assertEqual(load[:3], ["/usr/bin/openFPGALoader", "--board", "basys3"])
        self.assertNotIn("-f", load)
        self.assertIn("-f", program)
        self.assertIn("--bitstream", load)
        self.assertIn("--bitstream", program)

    def test_pipelinec_and_openxc7_are_commit_pinned(self):
        lock = fpgatool.lock_config()
        self.assertRegex(lock["pipelinec"]["rev"], r"^[0-9a-f]{40}$")
        self.assertRegex(lock["openxc7"]["rev"], r"^[0-9a-f]{40}$")

    def test_exact_clean_checkout_can_be_reused(self):
        with mock.patch.object(fpgatool, "output") as output_mock:
            output_mock.side_effect = [
                "https://github.com/billiegoose/PipelineC.git",
                "dce15d203edfc69c4f97ce86f7a8ef0ece58e046",
                "",
            ]
            with mock.patch.object(Path, "exists", return_value=True):
                self.assertTrue(
                    fpgatool.checkout_matches_pipelinec_pin(
                        Path("/tmp/PipelineC"),
                        "https://github.com/billiegoose/PipelineC.git",
                        "dce15d203edfc69c4f97ce86f7a8ef0ece58e046",
                    )
                )

    def test_nix_container_is_digest_pinned(self):
        image = fpgatool.lock_config()["container"]["nix_image"]
        self.assertRegex(image, r"^docker\.io/nixos/nix@sha256:[0-9a-f]{64}$")
        cmd = fpgatool.podman_base(pipelinec_dir=Path("/tmp/PipelineC"))
        self.assertIn(image, cmd)
        self.assertNotIn("docker.io/nixos/nix:latest", cmd)

    def test_openxc7_lock_matches_flake_lock_and_source(self):
        rev = fpgatool.lock_config()["openxc7"]["rev"]
        flake_lock = json.loads((ROOT / "toolchain" / "flake.lock").read_text())
        self.assertEqual(flake_lock["nodes"]["openxc7"]["locked"]["rev"], rev)
        self.assertIn(rev, (ROOT / "toolchain" / "flake.nix").read_text())

    def test_programming_modes_are_explicit_in_board_profile(self):
        board = fpgatool.board_config("basys3")
        self.assertEqual(board["programmer"]["load_mode"], "sram")
        self.assertEqual(board["programmer"]["program_mode"], "flash")
        board["programmer"]["program_mode"] = "sram"
        with self.assertRaisesRegex(fpgatool.FPGAToolError, "expected 'flash'"):
            fpgatool.openfpgaloader_command(board, Path("demo.bit"), persistent=True)

    def test_git_worktree_marker_is_accepted(self):
        with mock.patch.object(Path, "exists", return_value=True), mock.patch.object(
            fpgatool, "output"
        ) as output_mock:
            output_mock.side_effect = [
                "https://github.com/billiegoose/PipelineC.git",
                "dce15d203edfc69c4f97ce86f7a8ef0ece58e046",
                "",
            ]
            self.assertTrue(
                fpgatool.checkout_matches_pipelinec_pin(
                    Path("/tmp/PipelineC-worktree"),
                    "https://github.com/billiegoose/PipelineC.git",
                    "dce15d203edfc69c4f97ce86f7a8ef0ece58e046",
                )
            )

    def test_bare_cli_has_no_default_action(self):
        args = fpgatool.parser().parse_args([])
        self.assertIsNone(args.command)
        self.assertIsNone(args.source)

    def test_load_and_program_require_explicit_bitstream_at_parse_result(self):
        for command in ("load", "program"):
            args = fpgatool.parser().parse_args([command])
            self.assertEqual(args.command, command)
            self.assertIsNone(args.source)

    def test_run_builds_then_loads_returned_bitstream(self):
        source = ROOT / "examples" / "blink.py"
        bitstream = ROOT / "build" / "basys3" / "blink" / "blink.bit"
        args = mock.Mock(source=str(source), board="basys3")
        with mock.patch.object(fpgatool, "normalize_source", return_value=source), mock.patch.object(
            fpgatool, "cmd_build", return_value=bitstream
        ) as build_mock, mock.patch.object(fpgatool, "load_bitstream") as load_mock:
            fpgatool.cmd_run(args)
        build_mock.assert_called_once_with(args)
        load_mock.assert_called_once_with("basys3", bitstream)

    def test_build_rejects_bitstream_input(self):
        bitstream = ROOT / "build" / "basys3" / "blink" / "blink.bit"
        args = mock.Mock(source=str(bitstream), board="basys3")
        with mock.patch.object(fpgatool, "normalize_source", return_value=bitstream):
            with self.assertRaisesRegex(fpgatool.FPGAToolError, "use load or program"):
                fpgatool.cmd_build(args)

    def test_run_rejects_bitstream_input(self):
        bitstream = ROOT / "build" / "basys3" / "blink" / "blink.bit"
        args = mock.Mock(source=str(bitstream), board="basys3")
        with mock.patch.object(fpgatool, "normalize_source", return_value=bitstream):
            with self.assertRaisesRegex(fpgatool.FPGAToolError, "use load"):
                fpgatool.cmd_run(args)

    def test_verbose_is_opt_in(self):
        quiet = fpgatool.parser().parse_args(["build", "examples/blink.py"])
        verbose = fpgatool.parser().parse_args(["build", "examples/blink.py", "--verbose"])
        self.assertFalse(quiet.verbose)
        self.assertTrue(verbose.verbose)

    def test_comb_is_opt_in(self):
        normal = fpgatool.parser().parse_args(["build", "examples/blink.py"])
        comb = fpgatool.parser().parse_args(["run", "examples/vga_smpte.py", "--comb"])
        self.assertFalse(normal.comb)
        self.assertTrue(comb.comb)

    def test_build_wrapper_forwards_comb_only_when_requested(self):
        script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn('if [ "$comb_arg" = "--comb" ]; then', script)
        self.assertIn('pipelinec_args+=(--comb)', script)

    def test_quiet_run_redirects_tool_output_to_log(self):
        log = ROOT / ".fpgatool-test.log"
        try:
            with mock.patch.object(fpgatool, "VERBOSE", False), mock.patch.object(
                fpgatool.subprocess, "run", return_value=subprocess.CompletedProcess(["tool"], 0)
            ) as run_mock:
                fpgatool.run(["tool"], log_path=log)
            kwargs = run_mock.call_args.kwargs
            self.assertIn("stdout", kwargs)
            self.assertIs(kwargs["stderr"], subprocess.STDOUT)
        finally:
            log.unlink(missing_ok=True)

    def test_pipelinec_delay_cache_is_writable_build_output(self):
        script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn(
            'export PYPELINEC_PATH_DELAY_CACHE_DIR="$out_dir/path_delay_cache"',
            script,
        )

    def test_default_bitstream_is_stable(self):
        source = (fpgatool.ROOT / "examples" / "blink.py").resolve()
        self.assertEqual(
            fpgatool.bitstream_path("basys3", source),
            fpgatool.ROOT / "build" / "basys3" / "blink" / "blink.bit",
        )


if __name__ == "__main__":
    unittest.main()
