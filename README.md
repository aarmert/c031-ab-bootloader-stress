# c031-ab-bootloader-stress

**If a microcontroller is reset at any moment of a firmware update, does it still boot a correct image?**

This repo tests one A/B bootloader on an STM32C031C6 (NUCLEO-C031C6). During real firmware updates the
board was reset at planned moments, either by the chip's own timer or by an ESP32-S3 pulling the NRST
pin. After every trial the host read both slots back over SWD and classified the outcome from their
SHA-256 hashes, not from timing or log lines.

| | Raw result |
|---|---|
| A/B bootloader, reset-injected updates | 3103 trials: 0 booted a corrupt image, 0 left the board dead |
| Naive bootloader (negative control), same ESP32 resets | 11 of 20 trials booted a corrupt image; the tool flagged all 11 |

These are counts at the points that were tested, on one board. They are not a failure probability.
What the data does not show is listed under [Limits](#limits).

<p align="center">
  <img src="docs/img/bench.jpg" width="380"
       alt="The bench: an ESP32-S3 wired to a NUCLEO-C031C6 with four jumper wires">
</p>
<p align="center"><em>The bench: the ESP32-S3 bridge (top) and the NUCLEO-C031C6. Grey and brown wires are
the UART, turquoise is NRST, purple is GND.</em></p>

**Contents:** [How the A/B bootloader works](#how-the-ab-bootloader-works) ·
[The sweeps](#the-sweeps) ·
[Results](#results) ·
[Negative control](#negative-control) ·
[Limits](#limits) ·
[Next steps](#next-steps) ·
[Try it without hardware](#try-it-without-hardware) ·
[With hardware](#running-it-on-the-hardware) ·
[Repo layout](#repo-layout)

This project was split out of [aarmert/tezgah-lab](https://github.com/aarmert/tezgah-lab), a
hardware-in-the-loop test bench for STM32 boards.

## How the A/B bootloader works

The 32 KB of flash holds the bootloader, two image slots (A and B) and an append-only meta log of
32-byte records. The newest record with a valid CRC holds the state: which slot is active, whether the
other slot is on trial, and how many trial boots it has had.

- A new image is always written to the **inactive** slot. The running image is never touched.
- The marks that make the new image valid (the header CRC and the CRC word of the meta record) are
  **always written last**. Work that a reset cuts short has no mark, and the bootloader ignores it.
- The new image boots as a **trial**. After 1 s of healthy running the app writes a CONFIRM record. An
  app that has not confirmed within 5 s stops feeding the watchdog. After three failed attempts the
  bootloader rolls back to the old slot.
- Every image is checked with CRC32 on every boot, and with CRC32 + SHA-256 after the transfer.

The claim under test: wherever the reset lands, the board comes up running either the old image or the
new one, never a half-written one, and never with nothing to boot.

The update is split into **phases**, the points in the firmware where a planned reset delay starts
counting ([SPEC §6.2](docs/spec/SPEC.md)). Their lengths come from the chip's own 1 µs timer (TIM14)
during `calibrate`; they were not checked with an outside instrument.

| Phase | Where the delay starts | Length (chip's timer) | Expected outcome of a reset |
|---|---|---|---|
| ERASE | erase of the inactive slot (4 pages) | 88.1 ms | PENDING |
| DATA k | flash write of packet k (192 B) | 2.12 ms each, 34 packets | PENDING |
| HDR | header write | 2.83 ms | PENDING |
| META | a meta record is appended: **TRIAL** (its CRC word is the commit), **ATTEMPT**, **CONFIRM** | 0.36 ms | TRIAL: PENDING before the commit; ATTEMPT, CONFIRM: NEW |
| BOOT | bootloader start, before the boot decision | ~16 ms | NEW |
| CONFIRM | in the app, before it writes CONFIRM | ~2.1 ms | NEW |

Two more phases, ROTATE (a full meta page is erased) and JUMP, were barely touched by the sweeps.

### One trial

1. **Baseline:** the ST-LINK reads the flash. A confirmed v1 or v2 must be running.
2. **Arm the reset:** the chip's timer (`FAULT ARM`) or the ESP32 (`NRST ARM`), "reset at this delay
   in this phase".
3. **Update:** the PC starts a v1→v2 (or v2→v1) update through the ESP32. The reset fires.
4. **Observe:** the board reboots. If the bootloader reports a cut-short update (`BL resume`), the PC
   sends the update again.
5. **Verify:** the ST-LINK reads both slots; their SHA-256 hashes are compared with v1 and v2.
6. **Classify:** `stress/classify.py` writes one row to `trials.csv`.

| Outcome | Meaning | Accepted |
|---|---|---|
| `NEW` | The new image runs from an intact slot | yes |
| `PENDING` | The reset cut the update short, the old image was kept, the PC finished the update | yes |
| `OLD` | The old image runs from an intact slot | yes |
| `WRONG` | A half-written or corrupt image was started. **The failure we are looking for.** | no |
| `DEAD` | Nothing boots; the ST-LINK had to recover the board | no |
| `UNCLEAR` | An unexplained reset or a setup error | no |

The files in `results/` use the Turkish names: `YENİ` = NEW, `ESKİ` = OLD, `BEKLİYOR` = PENDING,
`ÖLÜ` = DEAD, `YANLIŞ` = WRONG, `BELİRSİZ` = UNCLEAR. `python -m stress report` and
`scripts/make_figures.py` map them.

## The sweeps

The critical moments are short (the TRIAL record takes 0.36 ms of a ~1.4 s update), so random resets
would rarely hit them. Instead each phase was divided into evenly spaced delays (10 µs step, at most
800 points per phase, so ~110 µs in the 88 ms erase), and the list was shuffled with a seed.

| | Sweep 1 | Sweep 2 |
|---|---|---|
| Reset source | the chip's own timer (TIM3 ISR in RAM, then SYSRESETREQ) | ESP32 GPIO4 → NRST (a pin reset) |
| Delay counted from | the phase start, on the chip's clock | the moment the ESP32 finished receiving the C031's UART line for that phase |
| Phases | 6 of 8 | ERASE, DATA, HDR |
| Planned points / seed | 3001 / 2026 | 2400 / 2027 |
| Trials run (stopped after 2 h) | 1493 | 1479 |

In sweep 2 the time from the event on the C031 to the end of its UART line at the ESP32 (line
transmission, UART buffering, loop polling) was not measured, so its delays carry an unknown offset.

### Wiring

```
PC USB ── NUCLEO-C031C6 ST-LINK/V2-1     SWD + virtual COM port (USART2 PA2/PA3, 115200)
PC USB ── ESP32-S3 UART connector        CH343, 921600

ESP32 GPIO17 ──────────────────►  PA10 (USART1 RX)
ESP32 GPIO18 ◄──────────────────  PA9  (USART1 TX)
ESP32 GPIO4 (open-drain) ──────►  NRST
GND ────────────────────────────  GND
3V3 and 5V are not connected between the boards.
```

The C031 writes every line to both UARTs; the PC compares the two copies, so a line lost or changed on
one path shows up.

## Results

| Phase | Sweep 1 PENDING | Sweep 1 NEW | Sweep 2 PENDING | Sweep 2 NEW |
|---|---:|---:|---:|---:|
| ERASE | 394 | | 492 | |
| DATA | 408 | | 511 | |
| HDR | 139 | | 15 | 461 |
| META | 19 (TRIAL) | 25 (ATTEMPT 16, CONFIRM 9) | | |
| BOOT | | 400 | | |
| CONFIRM | | 108 | | |
| **Total** | **960** | **533** | **1018** | **461** |
| WRONG / DEAD / UNCLEAR | 0 / 0 / 0 | | 0 / 0 / 0 | |

With the 131 shorter reset-injected trials of the same day (`reset_random` ×2, two short
`reset_sweep` runs, `double_fault`): 20 + 20 + 24 + 57 + 10 + 1493 + 1479 = 3103 trials, all
accepted. No ST-LINK recovery and no unexpected reset.

![Outcome per phase in both sweeps](docs/img/outcomes_by_phase.png)

![Each trial as a dot: reset delay within the phase vs outcome](docs/img/delay_scatter.png)

*x: the reset delay from the start of the phase. y: the packet number in the DATA panels, the meta
record in the META panel; elsewhere the dots are only spread out.*

The outcomes match the expected column of the phase table. In sweep 2, HDR was PENDING up to 29.3 ms
after the ESP32 saw `UPD END` and NEW from 33.3 ms on: the commit happened somewhere in that gap.

### Did the resets do anything?

![Resets fired, boots, half-written slots seen, BL resume count, WRONG](docs/img/evidence.png)

| Check | Sweep 1 | Sweep 2 |
|---|---|---|
| Reset fired | every trial (`BL fault_fired 1`) | every trial (`ESP NRST FIRED`) |
| A slot was half-written at boot | 841 of 4349 boots | 876 of 4435 boots |
| Bootloader reported a cut-short update | 961 × `BL resume` | 1019 × `BL resume` |
| Meta page erases (log wrapped) | 0 → 36 | 36 → 74 |

From the logs: in 9 sweep-1 BOOT trials the two UART copies of a line differed because the reset cut
the banner mid-character (all `NEW`). In sweep 2, 161 trials needed 319 line retransmissions (`ERR
LINE` after a reset during a DATA line). Slot pages were erased 2670 (A) and 2705 (B) times that day;
the C031 is rated for at least 10 000.

## Negative control

"0 WRONG" means something only if the same pipeline can report WRONG. A deliberately unsafe naive
bootloader, which overwrites its only slot in place, got the same ESP32 NRST resets:

| | A/B bootloader | Naive bootloader |
|---|---|---|
| Resets | 3103 (timer and ESP32 NRST) | 20 (ESP32 NRST, same phases) |
| WRONG | 0 | 11 |
| Other outcomes | 1978 PENDING, 994 NEW, 131 from the short runs | 7 PENDING (header already erased, nothing to boot), 2 NEW (late HDR resets) |

![A/B vs naive bootloader under the same resets](docs/img/ab_vs_naive.png)

The tool caught all 11 by reading the slot back (`slot A holds 'other' (neither v1 nor v2)`). In the
simulator the same pair gives 288/288 on the A/B model and 47/60 unsafe on the naive model.

## Limits

- **A count, not a probability.** The points were a systematic sweep, only about half of each plan
  ran, and three setups are added together. A bug confined to a window that no reset hit would not
  show. The per-run `summary.md` files in `results/` print a zero-failure 95% bound; that formula
  assumes independent random trials, which these are not.
- **The commit itself was barely hit.** Sweep 1 put 19 resets into the TRIAL record (0 to 330 µs of
  its ~359 µs), all PENDING; none landed on the flip. Sweep 2 has no trial in the 4 ms around it.
- **No outside timing reference.** Phase lengths come from the chip's timer. The ESP32 reports its
  pulses as 2–15 µs late, but it measures that itself, from its own planned moment to its own pin
  reading low; the UART offset above is not in that number. Neither was checked with a logic analyzer
  or a second MCU's timer capture.
- **One board, one temperature, one build.** The firmware had fault-injection hooks compiled in, and
  the resets kept power on (SYSRESETREQ or NRST), so the RAM "update in progress" flag survived.

## Next steps

- Measure the timing from outside: a GPIO raised at every phase start and the NRST line, both captured
  by a second MCU's timer (or a logic analyzer), to get the real offset and jitter of sweep 2.
- A dense sweep around the TRIAL commit.
- A power-cut sweep: the ESP32-S3 cuts the supply through a MOSFET, so the bootloader has to recover
  from flash alone.
- A mutation test (for example, write the header before the data) that the sweep must report as
  `WRONG`; more boards; the release build without hooks; an on-device update client.

## Try it without hardware

You need [uv](https://docs.astral.sh/uv/). It installs Python and the packages on the first `uv run`.

```bash
git clone https://github.com/aarmert/c031-ab-bootloader-stress.git && cd c031-ab-bootloader-stress

# The simulator models the bootloader, the flash and the reset behaviour of the C031
uv run python -m stress --json plan reset_sweep --seed 1 --sim --target c031    # the 288 faults it would inject
uv run python -m stress --json run reset_sweep --seed 1 --sim --target c031     # 288/288 pass (167 PENDING, 121 NEW)
uv run python -m stress --json run naive_control --seed 1 --sim --target c031   # the control: 47/60 unsafe (WRONG)

# Redraw the figures in docs/img from the published data in results/
uv run scripts/make_figures.py
```

The two `run` commands end like this (trimmed):

```json
{"ok": true, "summary": "reset_sweep: PASS. 288/288 trials met the pass criterion", "counts": {"PENDING": 167, "NEW": 121}}
{"ok": true, "summary": "naive_control: PASS. naive control showed 47/60 unsafe outcomes (DEAD/WRONG): the test can see failures", "counts": {"WRONG": 47, "PENDING": 7, "NEW": 6}}
```

Note that `naive_control` passes when the naive bootloader *fails*: its pass criterion is that unsafe
outcomes appear. Each run writes a folder under `stress_runs/`.

Unit tests (the firmware tests build the images, so they need `arm-none-eabi-gcc`):

```bash
uv run python -m unittest discover -s stress/tests          # 140 tests
uv run python -m unittest discover -s firmware/boot_c0/tests
uv run python -m unittest discover -s firmware/boot/tests
```

Without `--target c031` the simulator models the F407 port in `firmware/boot/` (255 trials in
`reset_sweep`). The F407 port has only run in the simulator. The C031 build also needs it: the
`bad_image` test uses a real F407 app as its "wrong board" image.

## Running it on the hardware

| For | You need |
|---|---|
| Host tool | [uv](https://docs.astral.sh/uv/) (installs Python and `pyserial`) |
| Firmware | `arm-none-eabi-gcc` |
| Flashing and flash read-back | OpenOCD newer than 0.12.0 (0.12.0 has no `stm32c0x.cfg`; a git build works) |
| ESP32 bridge | `arduino-cli` with the esp32 core; upload it yourself |

```bash
cp stress.example.toml stress.toml                 # then fill in the ports
cp bench-c031.example.toml bench-c031.toml
uv run firmware/boot_c0/build_boot.py --json      # bootloaders, apps, images
uv run esp32/build.py --json                      # compile the bridge, then upload it yourself

uv run python -m stress --json doctor --target c031
uv run python -m stress --json calibrate --target c031
uv run python -m stress --json run basic --target c031 --n 20

# Sweep 1 (on-chip timer); stop it with Ctrl+C whenever you like
uv run python -m stress --json run reset_sweep --target c031 --seed 2026 --max-points-per-phase 800
# Sweep 2 (ESP32 NRST)
uv run python -m stress --json run reset_sweep --target c031 --seed 2027 --reset-source esp --max-points-per-phase 800
# The control
uv run python -m stress --json run naive_control --target c031 --n 20 --reset-source esp

uv run python -m stress --json report stress_runs/<run-folder> --plot
```

The tests are `basic`, `transfer_cut`, `line_noise`, `reset_random`, `reset_sweep`, `double_fault`,
`bad_image`, `rollback` and `naive_control`. [`stress/README.md`](stress/README.md) describes each one,
how a trial runs and how outcomes are classified. `bench.py` is the flashing/serial layer the stress
tool imports. It is a copy of `bench.py` from [f407-hil-bench](https://github.com/aarmert/f407-hil-bench),
where it is maintained and also drives the F407 functional test bench; it is included here so this repo
runs on its own.

## Repo layout

| Path | What |
|---|---|
| `stress/` | the host tool: planner, runner, classifier, simulator, report (`python -m stress`) |
| `bench.py` | flashing, SWD read-back and serial layer used by `stress/` (a copy from f407-hil-bench, unchanged) |
| `firmware/boot_c0/` | A/B and naive bootloaders, test apps and image builder for the C031 |
| `firmware/boot/` | the F407 port of the same (simulator only; also supplies the wrong-board image) |
| `firmware/wiretest_c031/` | a small wiring check for the C031 bench, not part of the stress system |
| `esp32/` | the ESP32-S3 line bridge with the timed NRST pulse |
| `AGENTS.md`, `CLAUDE.md` | rules for a coding agent driving this bench (touch the board only through `python -m stress`) |
| `docs/spec/` | the specs: `SPEC.md`, `SPEC-C031C6.md`, `SPEC-ESP32.md` |
| `docs/img/` | the bench photo and the figures |
| `results/` | the hardware runs of 2026-11-07: `trials.csv`, `summary.md`, `summary.json`, `run.json`, `serial.log` |
| `scripts/make_figures.py` | draws `docs/img/*.png` from `results/` |

### `results/`

| Folder | Result |
|---|---|
| `reset_sweep_20261107-152056` | sweep 1: 1493/1493 (timer hook, seed 2026) |
| `reset_sweep_20261107-172507` | sweep 2: 1479/1479 (ESP32 NRST, seed 2027) |
| `naive_control_20261107-121450` | the control: 11/20 WRONG |
| `reset_random_20261107-121105`, `reset_random_20261107-121251` | 20/20 each (hook, ESP) |
| `reset_sweep_20261107-122336`, `reset_sweep_20261107-122531` | 24/24 (ESP, 3 phases), 57/57 (hook, 8 phases, `--meta-near-full`) |
| `double_fault_20261107-122248` | 10/10 (two resets per trial) |
| `basic_…`, `transfer_cut_…`, `line_noise_…`, `bad_image_…`, `rollback_…` | 4/4 NEW, 10/10 OLD, 10/10 NEW, 2/2, 2/2 OLD (no reset injection) |
| `calibrate_*`, `calibration_c031.json` | the phase lengths and ESP32 windows the sweeps used |
| `wear.json` | flash erase counters |

The host name, home directory, ST-Link serial number and board UIDs were replaced with placeholders
(`<host>`, `~/`, `<stlink-serial>`, `<board-uid-N>`). Nothing else was changed.

## License

Apache-2.0, see [LICENSE](LICENSE).
