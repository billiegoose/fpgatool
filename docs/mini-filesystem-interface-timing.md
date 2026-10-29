# Basys 3 mini-filesystem: flash, JTAG, and CDC audit

Evaluation date: 2026-10-29. This is an implementation and board-test report, **not a claim of complete external-interface static timing closure**.

## Design and clock inventory

The evaluated design is `examples/mini_filesystem_demo.py` with the 100 MHz Basys 3 clock, the resident USER1 SPI-over-JTAG bridge, the USER2 flash-ownership mailbox, the QSPI byte engine, and 115200 baud UART.

| Clock or interface | Source / domain | Consumers and external paths |
| --- | --- | --- |
| `clk_100p0` | Board oscillator W5, 100 MHz | Filesystem console, flash-byte FSM, UART receiver/transmitter, flash ownership FSM, status snapshot producer, and USER1 TCK synchronizers. The PipelineC `ctx.addClock` is translated to `create_clock -period 10` and appears in nextpnr's derived constraints. |
| USER1 TCK / DRCK | BSCANE2 chain 1, PyFtdi nominal 3 MHz; asynchronous to 100 MHz | DRCK captures MOSI on rising edges; TCK feeds two-flop synchronization plus delayed registered SPI SCK; the BSCAN TDO return is sampled by JTAG at its falling edge. No independent board pad. |
| USER2 DRCK | BSCANE2 chain 2, asynchronous to 100 MHz | 64-bit status capture and shift register; two-flop synchronization of application status acknowledgement into DRCK. |
| USER2 UPDATE | BSCANE2 chain 2, asynchronous to DRCK and 100 MHz | Receives 2-bit command into a holding mailbox and toggles a request, synchronized into 100 MHz. |
| Application flash SCK | Registered divided 100 MHz clock: 10 fabric cycles per half-period = 5 MHz | Generated through STARTUPE2 `USRCCLKO` and the dedicated FPGA configuration CCLK pad; not a top-level clock port. QSPI DQ0–DQ3 and CS# are normal pins. |
| USER1 flash SCK | Fabric-registered delayed copy of synchronized TCK, nominal 3 MHz | Also drives STARTUPE2 when USER1 owns flash; held low outside a transaction. |
| UART serial | Asynchronous RsRx B18, RsTx A18, 115200 baud | Rx passes a two-flop `meta`/`sync` sampler at 100 MHz; Tx is synchronous to 100 MHz. |

Relevant board-facing ports in this build are `clk_100p0`, `RsRx`, `RsTx`, `QspiCSn` (K19), `QspiDQ0` (D18), `QspiDQ1` (D19), `QspiDQ2` (G18), `QspiDQ3` (F18), and LD0–LD15. QspiDQ1 has an input pull-up. Neither configuration CCLK nor JTAG TCK/DRCK/UPDATE is a normal top-level input. `boards/basys3/pins.xdc` constrains the available package pins and LVCMOS33 standards.

## USER2 coherent status contract

`proxy` forms a registered 32-bit status in the **100 MHz** application domain, containing READY, GRANTED, BUSY, ERROR, generation, and diagnostic flags. A USER2 CAPTURE_DR returns the **previously completed, acknowledged snapshot**, not necessarily the instantaneous status:

1. DRCK CAPTURE_DR shifts the last `status_jtag` value into the 64-bit return word and, when no request is outstanding, toggles `status_request`.
2. A two-stage synchronizer transfers that request to 100 MHz. The application copies the entire status word into `status_hold` and toggles the acknowledgement to match.
3. A two-stage synchronizer transfers the acknowledgement to DRCK. The DRCK side copies the still-held bus into `status_jtag`. The next CAPTURE_DR can return this coherent word.

The low 32 bits remain the `RFL2` signature `0x52464c32`; the upper 32 bits retain the original status layout. The first read after FPGA configuration may return the initialized zero status with a valid signature; the second read returns the first completed application snapshot. The host `Mailbox` primes one read on entry and polls for state transitions. A stopped JTAG clock merely delays acceptance; the 100 MHz FSM keeps running. TAP reset does not reset this handshake or the application. A pending request is not reused until acknowledged. Tests cover back-to-back reads, changing flags, multi-bit generation transitions, `0xffff` to `0x0000` wrap, clock stalls, and TAP reset.

The original direct capture of live status on DRCK has been removed. VHDL `ASYNC_REG` annotations exist on handshake synchronizer stages. Inspection of the **actual synthesized Yosys JSON** found 18 `ASYNC_REG=TRUE` **net-name attributes**, including all six USER2 request/ack/command sync nets, but no correspondingly tagged cell attributes. This proves the signal annotations were retained; it does **not** yet prove that Himbächel groups the corresponding flip-flops or provides a reliable metastability-resolution placement constraint. No broad false-path exception has been added to conceal real CDC paths.

## USER1 SPI mode and host alignment

USER1 uses SPI mode 0 (CPOL=0, CPHA=0). Its SCK is low during CAPTURE_DR, before SHIFT_DR, and during idle. DRCK rising captures the current MOSI bit; a delayed, 100 MHz-registered SCK rising edge samples it. The delayed final SCK high/low pulse is allowed to finish even if SHIFT_DR falls on its last bit. Flash SO changes after falling SCK, while the BSCANE2 TDO path registers on falling TCK. The JTAG receive stream is therefore one bit behind the flash response: the host reconstructs byte `i` as `((sampled[i] << 1) & 255) | (sampled[i+1] >> 7)`, with a lookahead byte.

The GHDL BSCANE2 model now registers TDO on falling DRCK and models CAPTURE, SHIFT, RUNTEST and TAP reset. Edge-level simulation asserts eight rising and eight falling SCK edges per transmitted byte (including single-byte `0x06`, high-bit `0x9f`, and back-to-back multi-byte transactions), MOSI setup/hold, CS setup, SCK pulse widths, final-bit completion, and grant removal. A behavioral flash drives MISO 8 ns after SCK falls and confirms the host's reconstructed bytes. Four passing VCD captures can be regenerated by running `tests.test_live_jtag_vhdl` in the pinned Nix simulation shell with `FPGATOOL_CAPTURE_JTAG_VCD=1`; they are retained under `build/basys3/mini_filesystem_demo/jtag_waveforms/`.

## Flash AC timing budget

The physical board reports JEDEC `01 02 15`, consistent with the Spansion/Infineon S25FL032P described by Digilent's Basys 3 manual. Another board revision can contain Macronix flash, so repeat identification and use that part's datasheet before applying these numbers to another device.

From S25FL032P datasheet Rev. *L, Table 25 at page 49: READ `0x03` at most 40 MHz; RDID at most 50 MHz; other serial commands at most 104 MHz; SCK high/low each at least 4.5 ns; CS active setup and hold each at least 3 ns; input setup 3 ns and input hold 2 ns; serial SO clock-low to valid at most 8 ns (full 2.7–3.6 V); quad SO at most 9.5 ns (full supply range); output hold at least 2 ns; CS high at least 10 ns after reads and 50 ns for program/erase operations. Datasheet: https://www.infineon.com/assets/row/public/documents/10/49/infineon-s25fl032p-32-mbit-3.0-v-flash-memory-datasheet-en.pdf . Basys 3 reference manual: https://digilent.com/reference/_media/reference/programmable-logic/basys-3/basys3_rm.pdf .

| Path/requirement | Functional budget before unmeasured board/FPGA delays |
| --- | --- |
| Application flash SCK | 5 MHz: 200 ns period, 100 ns high and low; exceeds flash 4.5 ns minima. |
| Application MOSI setup | Up to ~97 ns available between the modeled falling-edge update and next sampling rise after subtracting 3 ns flash setup. The fabric clock-to-output, relative pad delays and PCB skew remain unmeasured. |
| Application quad MISO read | ~90.5 ns of the 100 ns half-cycle remains after the conservative 9.5 ns flash-valid maximum, for board return, FPGA input and register setup/skew. This is **not** a proven routed path budget. |
| Application CS high | At least 10 cycles at 100 MHz = 100 ns normal gap, versus 10 ns read and 50 ns program/erase requirements; recovery gap 20 cycles = 200 ns. |
| USER1 3 MHz bitstream | Nominal ~333 ns period / ~167 ns half-cycle. MOSI is DRCK-captured, then SCK rises after multiple 100 MHz register stages; simulation enforces at least 20 ns logical setup/hold and at least 40 ns logical SCK high/low. External pad propagation and clock skew are not included. |

There is no published per-trace propagation bound in the board manual used here. No PCB delay, STARTUPE2 CCLK output timing, physical IO delay, or worst-case PVT uncertainty was measured on this board. Those quantities must be subtracted before an external setup/hold guarantee can be made.

## Constraint and routed-implementation coverage

The pinned OpenXC7 compatibility wrapper accepts PipelineC's `ctx.addClock("clk_100p0", 100.0)` and visibly translates it to `create_clock -period 10`. The actual nextpnr route reports that 100 MHz application clock. The JTAG-related DRCK and UPDATE clocks appear in nextpnr at a **default inferred 12 MHz**, not as a documented asynchronous clock relationship or a measured 3 MHz timing source. Cross-domain critical-path reports exist, but their low path delays are not a CDC proof. The flow does not emit a comprehensive unconstrained-external-path signoff report.

The routed design currently has **no demonstrated applied `set_input_delay`, `set_output_delay`, generated-clock relationship for STARTUPE2 CCLK, or effective path-specific CDC exceptions**. These are the remaining constraint/toolchain gaps, not satisfied requirements. Nextpnr's documented generic interface covers named clock constraints and architecture-specific pin constraints; do not assume Vivado timing commands work in the pinned Himbächel XDC parser. The current shim translates literal `ctx.addClock` calls and passes the board XDC through unchanged. An external STA engine or supported timing-constraint implementation plus actual board delays is needed for complete I/O signoff. Nextpnr documentation: https://github.com/YosysHQ/nextpnr/blob/main/docs/constraints.md .

| Implemented block | Final routed FMAX | Required | Margin above requirement |
| --- | ---: | ---: | ---: |
| Flash byte engine + USER1/USER2 proxy, independently built | **157.43 MHz** | 100 MHz | **57.43%** |
| Integrated mini-filesystem/UART demo | **109.54 MHz** | 100 MHz | **9.54%** |

Both builds PASS their 100 MHz application clocks. The independent engine exceeds AGENTS.md's 10–20% block-level margin; the final design has narrower headroom and should be rechecked after changes. The inferred 12 MHz JTAG FMAX passes do **not** validate async CDC or flash external timing.

Reproducibility: git HEAD `1be0c7183df802fb96d555345e4535aa7c17860a` plus uncommitted WIP. `jtag_flash.py` SHA-256 `82b09936d3740848917ab4ae6fda90444fa4a601945177760c86fa97b4092b20`; full demo bitstream `6a4f76be47368e09da369bd722e7e2dad06bcb3b3fe7417828729765ac86ccd8`; final routed report `20685a16596189b73e6905e593869360ca212547da535810d564709a550ae502`. Build settings: `./fpgatool.sh build examples/mini_filesystem_demo.py --board basys3 --comb` and `./fpgatool.sh build examples/mini_filesystem_spi_engine_probe.py --board basys3 --comb`, pinned Podman/Nix OpenXC7 with GHDL 6.0.0. Reports: each design's `build/basys3/<design>/pipelinec/top/open_tools_final.log`.

## Verification and remaining signoff

- Four GHDL bridge regression tests pass, with stored VCD traces; 13 Python mini-filesystem host tests pass.
- The corrected full design was loaded **to volatile SRAM only**. Physical no-write USER2 BEGIN/RELOAD changed `0x00000001` (generation 0) through GRANTED `0x00000007` to `0x00010001` (generation 1), idle and ready.
- Physical UART `list` returned the expected 53 bytes, ebook `print` the expected 498 bytes, and non-text/missing-name rejection passed.
- Physical USER1 read-only JEDEC returned `01 02 15`; 256 index bytes at `0x240000` matched the archived 4 MiB flash image. No flash programming or erase occurred in these checks. The saved capture SHA-256 remains `45a83b673a9ba41bbafe0c18eae3a62fc69f5a8450bab5024f477d4c71a1efae`.

**Still open:** establish supported, applied external I/O timing constraints or an independent STA/measurement alternative; bound actual PCB and STARTUPE2 IO delays and skew over PVT; confirm the P&R treatment and placement of `ASYNC_REG` synchronizer stages. Until then, simulation and physical functional checks are strong evidence of correct sequencing, but they are not a proof of all-condition interface safety.
