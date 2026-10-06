from pathlib import Path
import argparse
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

    def test_sim_cli_capture_options(self):
        args = fpgatool.parser().parse_args(['sim', 'examples/vga_test_bars.py',
            '--no-open', '--frames', '2', '--cycles', '1000', '--screenshot', 'bars.png'])
        self.assertTrue(args.no_open)
        self.assertEqual((args.frames, args.cycles, args.screenshot), (2, 1000, 'bars.png'))
        with self.assertRaises(argparse.ArgumentTypeError):
            fpgatool.positive_int('0')

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
        for lane in range(4):
            self.assertIn(f"QspiDQ{lane}_I: Input[uint1_t]", qspi)
            self.assertIn(f"QspiDQ{lane}_O: Output[uint1_t]", qspi)
            self.assertIn(f"QspiDQ{lane}_T: Output[uint1_t]", qspi)
            self.assertIn(f'_rewrite_pad(text, f"QspiDQ{{index}}")', qspi)
        self.assertIn("@final(syn=True)", qspi)
        self.assertIn("_bind_basys3_qspi_pads", qspi)
        self.assertIn("when {enable} = unsigned'(0 => '0')", qspi)
        self.assertIn("if n_read > 1 or n_drive != 1", qspi)
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

    def test_qspi_flash_jedec_id_path_remains_read_only(self):
        hw = (ROOT / "examples" / "hardware" / "SPI.py").read_text()
        jedec_start = hw.index("def read_jedec_id(")
        generic_start = hw.index("# Generic single-SPI byte/block access")
        jedec = hw[jedec_start:generic_start]
        self.assertIn("159  # 0x9F, Read JEDEC ID", jedec)
        self.assertIn("_ST_PRIME", jedec)
        self.assertIn("tx_shift = 102  # 0x66, Reset Enable.", jedec)
        self.assertIn("tx_shift = 153  # 0x99, Reset.", jedec)
        self.assertIn("tx_shift = 171  # 0xAB, Release from Deep Power-Down.", jedec)
        self.assertNotIn("0x02", jedec)
        self.assertNotIn("0xD8", jedec)

    def test_flash_protocol_and_spi_transport_are_split(self):
        hardware = ROOT / "examples" / "hardware"
        protocol = (hardware / "flash.py").read_text()
        spi = (hardware / "SPI.py").read_text()
        self.assertIn("FLASH_OP_READ = 1", protocol)
        self.assertIn("FLASH_OP_PROGRAM = 2", protocol)
        self.assertIn("FLASH_OP_ERASE_BLOCK = 3", protocol)
        self.assertIn("from hardware.flash import (", spi)
        self.assertIn("def flash_byte_io(", spi)
        self.assertFalse((hardware / "qspi_flash.py").exists())
        self.assertFalse((hardware / "flash_qspi_write.py").exists())
        self.assertFalse((hardware / "qspi_text_reader.py").exists())

    def test_qspi_flash_status_diagnostic_uses_canonical_flash_module(self):
        hw = (ROOT / "examples" / "hardware" / "SPI.py").read_text()
        self.assertIn("def read_status_and_test_wren(", hw)
        self.assertIn("_STATUS_RDSR_COMMAND = 0x0500000000000000", hw)
        self.assertIn("_STATUS_WREN_COMMAND = 0x0600000000000000", hw)
        self.assertNotIn("0xD8", hw[hw.index("# Status/WREN diagnostic"):])
        self.assertFalse((ROOT / "examples" / "qspi_flash_status.py").exists())
        self.assertFalse((ROOT / "examples" / "hardware" / "qspi_flash_status.py").exists())

    def test_qspi_flash_exposes_generic_arbitrary_byte_access(self):
        hw = (ROOT / "examples" / "hardware" / "SPI.py").read_text()
        self.assertIn("class qspi_flash_byte_io_t", hw)
        self.assertIn("def flash_byte_io(", hw)
        protocol = (ROOT / "examples" / "hardware" / "flash.py").read_text()
        self.assertIn("FLASH_OP_READ = 1", protocol)
        self.assertIn("FLASH_OP_PROGRAM = 2", protocol)
        self.assertIn("FLASH_OP_ERASE_BLOCK = 3", protocol)
        self.assertIn("op: uint2_t", hw)
        self.assertIn("address: uint32_t", hw)
        self.assertIn("if op != FLASH_OP_NONE", hw)
        self.assertIn("requested_op: Reg[uint2_t] = FLASH_OP_NONE", hw)
        self.assertIn("state = _BYTE_ST_DISPATCH", hw)
        self.assertIn("if requested_op == FLASH_OP_ERASE_BLOCK", hw)
        self.assertIn("elif requested_op == FLASH_OP_PROGRAM", hw)
        self.assertIn("elif requested_op == FLASH_OP_READ", hw)
        self.assertIn("write_data: uint8_t", hw)
        self.assertIn("(uint64_t(0x03) << 56) | (uint64_t(requested_address) << 32)", hw)
        self.assertIn("(uint64_t(0x02) << 56)", hw)
        self.assertIn("(uint64_t(0xD8) << 56)", hw)
        self.assertIn("uint64_t(0x06) << 56", hw)
        self.assertIn("uint64_t(0x05) << 56", hw)
        self.assertIn("_BYTE_POWERUP_CYCLES = 2_000_000", hw)
        self.assertIn("_BYTE_ST_PROGRAM_VERIFY_DONE", hw)
        self.assertNotIn("0xC7", hw)

    def test_qspi_flash_rw_demo_uses_generic_flash_interface(self):
        hw = (ROOT / "examples" / "flash_qspi_write.py").read_text()
        self.assertIn("import hardware.QSPI as qspi_flash", hw)
        self.assertIn("_USER_BLOCK_ADDRESS = 0x3F0000", hw)
        self.assertIn("qspi_flash.flash_byte_io", hw)
        self.assertIn("qspi_flash.FLASH_OP_READ", hw)
        self.assertIn("qspi_flash.FLASH_OP_ERASE_BLOCK", hw)
        self.assertIn("qspi_flash.FLASH_OP_PROGRAM", hw)
        self.assertIn("_ST_BOOT_READY", hw)
        self.assertIn("_ST_BOOT_LAUNCH", hw)
        self.assertIn("_ST_BOOT_WAIT", hw)
        self.assertIn("_ST_ERASE_READY", hw)
        self.assertIn("_ST_ERASE_LAUNCH", hw)
        self.assertIn("_ST_ERASE_WAIT", hw)
        self.assertIn("_ST_PROGRAM_READY", hw)
        self.assertIn("_ST_PROGRAM_LAUNCH", hw)
        self.assertIn("_ST_PROGRAM_WAIT", hw)
        self.assertIn("bcd_valid", hw)
        self.assertNotIn("tx_shift", hw)
        self.assertNotIn("_READ_USER_COMMAND", hw)
        self.assertNotIn("_PROGRAM_USER_COMMAND", hw)
        demo = (ROOT / "examples" / "flash_qspi_write.py").read_text()
        self.assertIn("board_buttons.BTNU", demo)
        self.assertIn("board_buttons.BTND", demo)
        self.assertIn("board_buttons.BTNC", demo)
        self.assertIn("persistent_bcd_store", demo)
        self.assertIn("drive_clock_and_cs", demo)
        self.assertIn("dq: uint4_t = concat(", demo)
        self.assertIn("board_qspi.QspiDQ1_T = flash.dq1_t", demo)
        self.assertIn("board_qspi.QspiDQ2_T = flash.dq2_t", demo)
        self.assertIn("board_qspi.QspiDQ3_T = flash.dq3_t", demo)
        self.assertIn("board_leds.LD15 = flash.quad_enabled", demo)
        self.assertIn("board_leds.LD12 = flash.quad_activity", demo)
        self.assertIn("board_leds.LD10 = flash.quad_write_activity", demo)


    def test_dspi_and_qspi_transports_use_real_wide_data_phases(self):
        hardware = ROOT / "examples" / "hardware"
        protocol = (hardware / "flash.py").read_text()
        dspi = (hardware / "DSPI.py").read_text()
        qspi = (hardware / "QSPI.py").read_text()

        self.assertIn("CMD_DUAL_OUTPUT_READ = 0x3B", protocol)
        self.assertIn("CMD_QUAD_OUTPUT_READ = 0x6B", protocol)
        self.assertIn("CMD_QUAD_PAGE_PROGRAM = 0x32", protocol)
        self.assertIn("CONFIG_QUAD_ENABLE = 0x02", protocol)

        self.assertIn("def flash_byte_io(\n    dq: uint2_t", dspi)
        self.assertIn("CMD_DUAL_OUTPUT_READ", dspi)
        self.assertIn("rx_width = 2", dspi)
        self.assertIn("concat(dq[1], dq[0])", dspi)
        self.assertIn("cclk and tx_remaining == 1", dspi)
        self.assertIn("dspi_activity = 1", dspi)
        self.assertIn("dspi_activity=dspi_activity", dspi)
        self.assertIn("dq0_t=dq0_t", dspi)

        self.assertIn("def flash_byte_io(\n    dq: uint4_t", qspi)
        self.assertIn("CMD_QUAD_OUTPUT_READ", qspi)
        self.assertIn("CMD_QUAD_PAGE_PROGRAM", qspi)
        self.assertIn("CMD_READ_CONFIG", qspi)
        self.assertIn("CMD_WRITE_REGISTERS", qspi)
        self.assertIn("config_saved | CONFIG_QUAD_ENABLE", qspi)
        self.assertIn("concat(dq[3], dq[2], dq[1], dq[0])", qspi)
        self.assertIn("cclk and tx_remaining == 1", qspi)
        self.assertIn("release_quad", qspi)
        self.assertIn("if not quad_enabled:", qspi)
        self.assertNotIn("uint64_t(0x03) << 56", qspi)
        self.assertIn("quad_activity = 1", qspi)
        self.assertIn("quad_write_activity = 1", qspi)
        self.assertIn("quad_enabled=quad_enabled", qspi)
        self.assertIn("quad_activity=quad_activity", qspi)
        self.assertIn("quad_write_activity=quad_write_activity", qspi)
        self.assertIn("dq0_t=dq0_t", qspi)
        self.assertIn("dq1_t=dq1_t", qspi)
        self.assertIn("dq2_t=dq2_t", qspi)
        self.assertIn("dq3_t=dq3_t", qspi)

    def test_reusable_button_module_is_used_by_all_button_demos(self):
        button_hw = (ROOT / "examples" / "hardware" / "buttons.py").read_text()
        self.assertIn("def make_button(", button_hw)
        self.assertIn("DEBOUNCE_CYCLES=2_000_000", button_hw)
        self.assertIn("REPEAT_DELAY_CYCLES=50_000_000", button_hw)
        self.assertIn("REPEAT_INTERVAL_CYCLES=7_500_000", button_hw)
        self.assertIn("debounce_count_t = make_uint_t(max(1, (DEBOUNCE_CYCLES - 1).bit_length()))", button_hw)
        self.assertIn("(max(REPEAT_DELAY_CYCLES, REPEAT_INTERVAL_CYCLES) - 1).bit_length()", button_hw)
        self.assertIn("@hw_func\n    def button(raw: uint1_t) -> button_t:", button_hw)
        self.assertIn("count: Reg[debounce_count_t] = 0", button_hw)
        self.assertIn("repeat_count: Reg[repeat_count_t] = 0", button_hw)
        self.assertIn("if pressed:", button_hw)
        self.assertIn("elif repeating:", button_hw)
        self.assertIn("repeat=repeat", button_hw)
        self.assertIn("return button", button_hw)

        for name in (
            "flash_spi_read.py",
            "flash_spi_write.py",
            "flash_dspi_read.py",
            "flash_qspi_read.py",
            "flash_qspi_write.py",
            "led_chaser.py",
            "kitchen_sink_demo.py",
        ):
            demo = (ROOT / "examples" / name).read_text()
            self.assertIn("import hardware.buttons as button_hw", demo)
            self.assertIn("_button = button_hw.make_button()", demo)
            self.assertIn("_button(board_buttons.", demo)

        flash_rw = (ROOT / "examples" / "flash_qspi_write.py").read_text()
        self.assertNotIn("up_prev: Reg", flash_rw)
        self.assertNotIn("down_prev: Reg", flash_rw)
        self.assertNotIn("center_prev: Reg", flash_rw)
        self.assertNotIn("debounce: Reg", flash_rw)

    def test_button_timing_is_elaboration_time_factory_configuration(self):
        button_hw = (ROOT / "examples" / "hardware" / "buttons.py").read_text()
        self.assertIn('raise ValueError("DEBOUNCE_CYCLES must be positive")', button_hw)
        self.assertIn('raise ValueError("REPEAT_DELAY_CYCLES must be positive")', button_hw)
        self.assertIn('raise ValueError("REPEAT_INTERVAL_CYCLES must be positive")', button_hw)
        self.assertNotIn("Reg[uint21_t]", button_hw)
        self.assertNotIn("Reg[uint26_t]", button_hw)

    def test_flash_read_navigation_uses_keyboard_style_repeat(self):
        for name in (
            "flash_spi_read.py",
            "flash_dspi_read.py",
            "flash_qspi_read.py",
        ):
            demo = (ROOT / "examples" / name).read_text()
            self.assertIn("left_button.repeat, right_button.repeat", demo)
            self.assertNotIn("left_button.pressed, right_button.pressed", demo)

    def test_pipelinec_wrapper_reapplies_final_hooks_after_final_top_regeneration(self):
        script = (ROOT / "toolchain" / "build-pipelinec.sh").read_text()
        self.assertIn('pipelinec_driver="$out_dir/pipelinec-driver.py"', script)
        self.assertIn('cp "$pipelinec_dir/src/pipelinec" "$pipelinec_driver"', script)
        self.assertIn('if not src_file.endswith(".py"):', script)
        self.assertIn('"$FPGA_TOOL_PIPELINEC_PYTHON" "$pipelinec_driver"', script)
        self.assertIn('$pipelinec_dir/src:$pipelinec_dir/include/pypeline', script)

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

    def test_flash_example_matrix_covers_spi_dspi_and_qspi(self):
        examples = ROOT / "examples"
        names = sorted(
            p.name for p in examples.iterdir()
            if p.is_file() and p.name.startswith("flash_")
        )
        self.assertEqual(
            names,
            [
                "flash_dspi_read.py",
                "flash_qspi_read.py",
                "flash_qspi_write.py",
                "flash_spi_read.py",
                "flash_spi_write.py",
            ],
        )

        spi_reader = (examples / "flash_spi_read.py").read_text()
        self.assertIn("import hardware.SPI as spi_flash", spi_reader)
        self.assertIn("spi_flash.flash_byte_io(dq1, op, address", spi_reader)
        self.assertIn("board_qspi.QspiDQ0_T = 0", spi_reader)
        self.assertIn("board_qspi.QspiDQ1_T = 1", spi_reader)

        dspi_reader = (examples / "flash_dspi_read.py").read_text()
        self.assertIn("import hardware.DSPI as dspi_flash", dspi_reader)
        self.assertIn("dq: uint2_t = concat(board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I)", dspi_reader)
        self.assertIn("board_leds.LD12 = page.dspi_activity", dspi_reader)

        spi_rw = (examples / "flash_spi_write.py").read_text()
        self.assertIn("import hardware.SPI as spi_flash", spi_rw)
        self.assertIn("spi_flash.FLASH_OP_ERASE_BLOCK", spi_rw)
        self.assertIn("spi_flash.FLASH_OP_PROGRAM", spi_rw)
        self.assertIn("board_qspi.QspiDQ1_T = 1", spi_rw)

    def test_flash_qspi_read_uses_raw_ff_terminated_text(self):
        reader = (ROOT / "examples" / "flash_qspi_read.py").read_text()
        self.assertIn("import hardware.QSPI as qspi_flash", reader)
        self.assertIn("_TEXT_ADDRESS = 0x3E0000", reader)
        self.assertIn("_TEXT_MAX_LENGTH = 65535", reader)
        self.assertIn("_TEXT_LAST_POSITION = _TEXT_MAX_LENGTH - 4", reader)
        self.assertIn("qspi_flash.flash_byte_io", reader)
        self.assertIn("qspi_flash.FLASH_OP_READ", reader)
        self.assertIn("flash.read_data == 255", reader)
        self.assertIn("byte_index = 4", reader)
        self.assertIn("can_move_right = flash.read_data != 255", reader)
        self.assertNotIn("_MAGIC", reader)
        self.assertNotIn("_ST_HEADER", reader)
        self.assertNotIn("header_length", reader)
        self.assertNotIn("tx_shift", reader)
        self.assertNotIn("wake_shift", reader)

        self.assertIn("board_buttons.BTNL", reader)
        self.assertIn("board_buttons.BTNR", reader)
        self.assertIn("read_text_window", reader)
        self.assertIn("page.char0", reader)
        self.assertIn("page.char3", reader)
        self.assertIn("import hardware.buttons as button_hw", reader)
        self.assertIn("_button = button_hw.make_button()", reader)
        self.assertIn("left_button = _button(board_buttons.BTNL)", reader)
        self.assertIn("right_button = _button(board_buttons.BTNR)", reader)
        self.assertIn("dq: uint4_t = concat(", reader)
        self.assertIn("page = read_text_window(dq, left_button.repeat, right_button.repeat)", reader)
        self.assertIn("board_leds.LD15 = page.quad_enabled", reader)
        self.assertIn("board_leds.LD12 = page.quad_activity", reader)
        self.assertIn("board_leds.LD11 = page.busy", reader)
        self.assertIn("board_seven_segment.CA = seg[0]", reader)
        self.assertIn("board_seven_segment.CG = seg[6]", reader)
        self.assertIn("if ch >= 97 and ch <= 122:", reader)
        self.assertIn("ch == 9 or ch == 10 or ch == 13", reader)

    def test_basys3_flash_layout_reserves_configuration_image(self):
        board = fpgatool.board_config("basys3")
        self.assertEqual(board["flash"]["size_bytes"], 0x400000)
        self.assertEqual(board["flash"]["configuration_end_offset"], 0x220000)
        self.assertEqual(board["flash"]["user_data_offset"], 0x220000)
        self.assertEqual(board["flash"]["erase_block_bytes"], 0x10000)

    def test_flash_layout_requires_erase_aligned_user_region(self):
        board = {
            "name": "test",
            "flash": {
                "size_bytes": 0x400000,
                "user_data_offset": 0x220001,
                "erase_block_bytes": 0x10000,
            },
        }
        with self.assertRaisesRegex(fpgatool.FPGAToolError, "erase-block aligned"):
            fpgatool.flash_layout(board)

    def test_program_data_defaults_to_first_safe_user_flash_block(self):
        board = fpgatool.board_config("basys3")
        path = ROOT / ".fpgatool-test-data.bin"
        try:
            path.write_bytes(b"asset")
            offset, length, erase = fpgatool.validate_data_flash_write(board, path, None)
            self.assertEqual(offset, 0x220000)
            self.assertEqual(length, 5)
            self.assertEqual(erase, 0x10000)
        finally:
            path.unlink(missing_ok=True)

    def test_program_data_rejects_configuration_overlap_and_flash_overflow(self):
        board = fpgatool.board_config("basys3")
        path = ROOT / ".fpgatool-test-data.bin"
        try:
            path.write_bytes(b"abcd")
            with self.assertRaisesRegex(fpgatool.FPGAToolError, "overlaps the FPGA configuration region"):
                fpgatool.validate_data_flash_write(board, path, 0x21FFFF)
            with self.assertRaisesRegex(fpgatool.FPGAToolError, "does not fit in flash"):
                fpgatool.validate_data_flash_write(board, path, 0x3FFFFE)
        finally:
            path.unlink(missing_ok=True)

    def test_program_data_uses_raw_binary_offset_and_verify(self):
        board = fpgatool.board_config("basys3")
        with mock.patch.object(fpgatool, "require_tool", return_value="/usr/bin/openFPGALoader"):
            cmd = fpgatool.openfpgaloader_data_command(board, Path("assets.bin"), 0x220000)
        self.assertEqual(cmd[:3], ["/usr/bin/openFPGALoader", "--board", "basys3"])
        self.assertIn("-f", cmd)
        self.assertEqual(cmd[cmd.index("--file-type") + 1], "bin")
        self.assertEqual(cmd[cmd.index("--offset") + 1], str(0x220000))
        self.assertIn("--verify", cmd)
        self.assertEqual(cmd[cmd.index("--bitstream") + 1], "assets.bin")

    def test_program_data_accepts_binary_outside_checkout(self):
        external = Path("/tmp/fpgatool-external-asset.bin")
        args = mock.Mock(source=str(external), board="basys3", offset=None)
        with mock.patch.object(fpgatool, "validate_data_flash_write", return_value=(0x220000, 4, 0x10000)) as validate_mock, mock.patch.object(
            fpgatool, "openfpgaloader_data_command", return_value=["loader"]
        ), mock.patch.object(fpgatool, "run"):
            fpgatool.cmd_program_data(args)
        self.assertEqual(validate_mock.call_args.args[1], external.resolve())

    def test_program_data_cli_accepts_hex_offset(self):
        args = fpgatool.parser().parse_args(["program-data", "asset.bin", "--offset", "0x230000"])
        self.assertEqual(args.command, "program-data")
        self.assertEqual(args.source, "asset.bin")
        self.assertEqual(args.offset, 0x230000)

    def test_default_bitstream_is_stable(self):
        source = (fpgatool.ROOT / "examples" / "blink.py").resolve()
        self.assertEqual(
            fpgatool.bitstream_path("basys3", source),
            fpgatool.ROOT / "build" / "basys3" / "blink" / "blink.bit",
        )


if __name__ == "__main__":
    unittest.main()
