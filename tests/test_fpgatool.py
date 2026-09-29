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
                "af34f25f76d11bbf7973b8e4b531611fe499cf0e",
                "",
            ]
            with mock.patch.object(Path, "exists", return_value=True):
                self.assertTrue(
                    fpgatool.checkout_matches_pipelinec_pin(
                        Path("/tmp/PipelineC"),
                        "https://github.com/billiegoose/PipelineC.git",
                        "af34f25f76d11bbf7973b8e4b531611fe499cf0e",
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
                "af34f25f76d11bbf7973b8e4b531611fe499cf0e",
                "",
            ]
            self.assertTrue(
                fpgatool.checkout_matches_pipelinec_pin(
                    Path("/tmp/PipelineC-worktree"),
                    "https://github.com/billiegoose/PipelineC.git",
                    "af34f25f76d11bbf7973b8e4b531611fe499cf0e",
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
        comb = fpgatool.parser().parse_args(["run", "examples/vga_test_bars.py", "--comb"])
        self.assertFalse(normal.comb)
        self.assertTrue(comb.comb)

    def test_build_wrapper_uses_merged_openxc7_interface(self):
        script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn('--syn_tool open_tools', script)
        self.assertIn('--part "$part"', script)
        self.assertNotIn('--syn_tool openxc7', script)
        self.assertNotIn('--no_sweep', script)

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

    def test_pipelinec_cache_is_writable_build_output(self):
        script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn(
            'export PYPELINEC_CACHE_DIR="$out_dir/cache"',
            script,
        )
        self.assertNotIn("PYPELINEC_PATH_DELAY_CACHE_DIR", script)

    def test_basys3_ps2_uses_split_unidirectional_io(self):
        ps2 = (ROOT / "examples" / "fpgatool_board" / "basys3" / "ps2.py").read_text()
        self.assertNotIn("OpenDrain", ps2)
        self.assertIn("PS2Clk_I: Input[uint1_t]", ps2)
        self.assertIn("PS2Clk_T: Output[uint1_t]", ps2)
        self.assertIn("PS2Data_I: Input[uint1_t]", ps2)
        self.assertIn("PS2Data_T: Output[uint1_t]", ps2)
        script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn("FPGATOOL_FINAL_TOP_VHDL", script)
        self.assertIn("unsigned\'(0 => \'0\')", ps2)

    def test_ps2_release_controls_are_explicit_uint1_t_locals(self):
        ps2 = (ROOT / "examples" / "hardware" / "ps2_mouse.py").read_text()
        # These annotations are semantically important to PipelineC elaboration.
        # Without them, the generated return struct collapsed both tristate
        # controls to constant zero, permanently holding the PS/2 pads low.
        self.assertIn("clk_release: uint1_t = 1", ps2)
        self.assertIn("data_release: uint1_t = 1", ps2)
        self.assertNotIn("\n    clk_release = 1\n", ps2)
        self.assertNotIn("\n    data_release = 1\n", ps2)

    def test_basys3_qspi_uses_internal_startupe2_for_cclk(self):
        qspi = (ROOT / "examples" / "fpgatool_board" / "basys3" / "qspi.py").read_text()
        self.assertIn("STARTUPE2", qspi)
        self.assertIn("USRCCLKO => cclk(0)", qspi)
        self.assertIn(
            "def drive_clock_and_cs(cclk: uint1_t, cs_n: uint1_t, cclk_ts: uint1_t) -> uint1_t",
            qspi,
        )
        self.assertIn("USRCCLKTS => cclk_ts(0)", qspi)
        self.assertNotIn("USRCCLKTS => '0'", qspi)
        self.assertIn("vhdl(_STARTUPE2_VHDL)", qspi)
        self.assertIn("@sim_model(drive_clock_and_cs)", qspi)
        self.assertIn("return cs_n", qspi)
        self.assertNotIn("QSPI_CCLK: Output", qspi)
        self.assertNotIn("@final", qspi)
        demo = (ROOT / "examples" / "qspi_flash_id.py").read_text()
        self.assertIn(
            "board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(",
            demo,
        )
        pins = (ROOT / "boards" / "basys3" / "pins.xdc").read_text()
        self.assertIn("LOC D18 [get_ports QspiDQ0]", pins)
        self.assertIn("LOC D19 [get_ports QspiDQ1]", pins)
        self.assertIn("LOC G18 [get_ports QspiDQ2]", pins)
        self.assertIn("LOC F18 [get_ports QspiDQ3]", pins)
        self.assertIn("LOC K19 [get_ports QspiCSn]", pins)
        self.assertNotIn("get_ports QSPI_CCLK", pins)
        self.assertIn("set_property PULLUP true [get_ports QspiDQ1]", pins)
        build_script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn("LIOB33_X0Y47.IOB_Y1.PULLTYPE.NONE", build_script)
        self.assertIn("LIOB33_X0Y47.IOB_Y1.PULLTYPE.PULLUP", build_script)
        self.assertIn("fasm2frames", build_script)
        self.assertIn("xc7frames2bit", build_script)
        self.assertIn('final_json="$final_top_dir/top.json"', build_script)
        self.assertIn('"QspiDQ1" in top.get("ports", {})', build_script)
        self.assertIn('if [ "$dq1_in_design" -eq 1 ]; then', build_script)
        self.assertIn("Modern Himbächel with XDC pull normalization", build_script)

    def test_qspi_flash_demo_is_read_only_jedec_id(self):
        hw = (ROOT / "examples" / "hardware" / "qspi_flash.py").read_text()
        self.assertIn("159  # 0x9F, Read JEDEC ID", hw)
        self.assertIn("_STARTUP_PRIME_CYCLES = 8", hw)
        self.assertIn("_ST_PRIME", hw)
        self.assertIn("tx_shift = 102  # 0x66, Reset Enable.", hw)
        self.assertIn("tx_shift = 153  # 0x99, Reset.", hw)
        self.assertIn("tx_shift = 171  # 0xAB, Release from Deep Power-Down.", hw)
        self.assertIn("_RES_CYCLES = 10_000", hw)
        self.assertNotIn("0x02", hw)
        self.assertNotIn("0x20", hw)
        self.assertNotIn("0xD8", hw)
        demo = (ROOT / "examples" / "qspi_flash_id.py").read_text()
        self.assertIn("read_jedec_id", demo)
        self.assertIn("manufacturer_id", demo)
        self.assertIn("memory_type", demo)
        self.assertIn("capacity", demo)

    def test_qspi_flash_rw_demo_uses_reserved_tail_block(self):
        hw = (ROOT / "examples" / "hardware" / "qspi_flash_rw.py").read_text()
        self.assertIn("_USER_BLOCK_ADDRESS = 0x3F0000", hw)
        self.assertIn("_READ_USER_COMMAND = ((0x03 << 24) | _USER_BLOCK_ADDRESS) << 32", hw)
        self.assertIn("_ERASE_USER_COMMAND = ((0xD8 << 24) | _USER_BLOCK_ADDRESS) << 32", hw)
        self.assertIn("_PROGRAM_USER_COMMAND = ((0x02 << 24) | _USER_BLOCK_ADDRESS) << 32", hw)
        self.assertIn("_WREN_COMMAND = 0x0600000000000000", hw)
        self.assertIn("_RDSR_COMMAND = 0x0500000000000000", hw)
        self.assertIn("bcd_valid", hw)
        self.assertIn("_CS_HIGH_CYCLES = 10", hw)
        self.assertIn("_ST_BUS_CS_HIGH = 17", hw)
        self.assertIn("state = _ST_BUS_CS_HIGH", hw)
        self.assertIn("_STARTUP_PRIME_CYCLES = 8", hw)
        self.assertIn("_RECOVERY_CS_HIGH_CYCLES = 20", hw)
        self.assertIn("_RES_CYCLES = 10_000", hw)
        self.assertIn("_ST_PRIME = 18", hw)
        self.assertIn("_ST_WAKE_FF = 19", hw)
        self.assertIn("_ST_WAKE_GAP = 20", hw)
        self.assertIn("_ST_WAKE_CMD = 21", hw)
        self.assertIn("_ST_WAKE_RES_WAIT = 22", hw)
        self.assertIn("wake_shift = 102  # 0x66, Reset Enable.", hw)
        self.assertIn("wake_shift = 153  # 0x99, Reset.", hw)
        self.assertIn("wake_shift = 171  # 0xAB, Release from Deep Power-Down.", hw)
        self.assertIn("elif state == _ST_BUS_CS_HIGH:", hw)
        self.assertNotIn("else:  # _ST_BUS_CS_HIGH", hw)
        self.assertNotIn("0xC7", hw)
        demo = (ROOT / "examples" / "qspi_flash_rw.py").read_text()
        self.assertIn("board_buttons.BTNU", demo)
        self.assertIn("board_buttons.BTND", demo)
        self.assertIn("board_buttons.BTNC", demo)
        self.assertIn("persistent_bcd_store", demo)
        self.assertIn("drive_clock_and_cs", demo)

    def test_container_nix_develop_uses_path_flake_for_dirty_worktrees(self):
        source = (ROOT / "fpgatool.py").read_text()
        self.assertEqual(
            source.count('"develop", "path:/workspace/toolchain",'),
            2,
        )
        self.assertNotIn('"develop", "/workspace/toolchain",', source)
        self.assertIn(
            '"--command", "bash", "/workspace/toolchain/build-pipelinec.sh",',
            source,
        )

    def test_qspi_ereader_uses_separate_read_only_text_sector(self):
        reader = (ROOT / "examples" / "hardware" / "qspi_text_reader.py").read_text()
        self.assertIn("_TEXT_SECTOR_ADDRESS = 0x3E0000", reader)
        self.assertIn("_TEXT_DATA_ADDRESS = _TEXT_SECTOR_ADDRESS + 6", reader)
        self.assertIn("tx_shift = (uint64_t(0x03) << 56) | (uint64_t(_TEXT_SECTOR_ADDRESS) << 32)", reader)
        self.assertIn("tx_shift = (uint64_t(0x03) << 56) | (uint64_t(address) << 32)", reader)
        self.assertEqual(reader.count("uint64_t(0x03) << 56"), 2)
        self.assertNotIn("command: uint32_t", reader)
        self.assertNotIn("uint64_t(command << 32)", reader)
        self.assertNotIn("uint64_t(command) << 32", reader)
        self.assertIn("_MAGIC = 0x45524452", reader)
        self.assertIn("uint64_t(0x03) << 56", reader)
        self.assertNotIn("0x02 << 24", reader)
        self.assertNotIn("0xD8 << 24", reader)
        self.assertNotIn("0xC7", reader)
        self.assertIn("wake_shift = 102", reader)
        self.assertIn("wake_shift = 153", reader)
        self.assertIn("wake_shift = 171", reader)

        demo = (ROOT / "examples" / "qspi_ereader.py").read_text()
        self.assertIn("board_buttons.BTNL", demo)
        self.assertIn("board_buttons.BTNR", demo)
        self.assertIn("read_text_window", demo)
        self.assertIn("page.char0", demo)
        self.assertIn("page.char3", demo)
        self.assertIn("left_stable: Reg[uint1_t] = 0", demo)
        self.assertIn("right_stable: Reg[uint1_t] = 0", demo)
        self.assertIn("left_count: Reg[uint21_t] = 0", demo)
        self.assertIn("right_count: Reg[uint21_t] = 0", demo)
        self.assertIn("left_event: Reg[uint1_t] = 0", demo)
        self.assertIn("right_event: Reg[uint1_t] = 0", demo)
        self.assertIn("left_count >= 1_999_999", demo)
        self.assertIn("right_count >= 1_999_999", demo)
        self.assertNotIn("prev_left", demo)
        self.assertNotIn("prev_right", demo)
        self.assertNotIn("debounce: Reg[uint22_t]", demo)
        reader_call = "page = text_reader.read_text_window(board_qspi.QspiDQ1, left_event, right_event)"
        self.assertIn(reader_call, demo)
        self.assertLess(demo.index(reader_call), demo.index("left_event = 0"))
        self.assertIn("board_seven_segment.CA = seg[0]", demo)
        self.assertIn("board_seven_segment.CG = seg[6]", demo)

    def test_qspi_ereader_image_packer_reserves_exactly_one_sector(self):
        import importlib.util
        path = ROOT / "examples" / "make_qspi_ereader_image.py"
        spec = importlib.util.spec_from_file_location("qspi_ereader_image", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        image = module.build_image("Hello   world\nfrom FPGA")
        self.assertEqual(len(image), 64 * 1024)
        self.assertEqual(image[:4], b"ERDR")
        length = int.from_bytes(image[4:6], "big")
        self.assertEqual(image[6:6 + length], b"HELLO WORLD FROM FPGA")
        self.assertEqual(image[6 + length:], b"\xff" * (len(image) - 6 - length))

    def test_default_bitstream_is_stable(self):
        source = (fpgatool.ROOT / "examples" / "blink.py").resolve()
        self.assertEqual(
            fpgatool.bitstream_path("basys3", source),
            fpgatool.ROOT / "build" / "basys3" / "blink" / "blink.bit",
        )


if __name__ == "__main__":
    unittest.main()
