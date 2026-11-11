# Agent rules (c031-ab-bootloader-stress)

This repo is the NUCLEO-C031C6 bootloader stress bench. Touch the board only through
`python -m stress` (which uses `bench.py`).

## Folders
- `stress/`, `stress_runs/`: the stress-test host tool and its results (`stress/README.md`)
- `bench.py`: the bench core that `stress` imports (flash, reset, serial). It is the same file as in
  `f407-hil-bench`; changes belong there.
- `firmware/boot_c0/`, `firmware/boot/`: stress-test bootloaders + apps for the C031 and the F407
- `firmware/wiretest_c031/`: a small wiring check for the C031 bench
- `esp32/bridge/`, `esp32/build.py`: the ESP32-S3 line bridge with a timed NRST
- `docs/spec/`: the stress-test specs (`SPEC.md` + `SPEC-C031C6.md` + `SPEC-ESP32.md`)
- `results/`: the published hardware runs of 2026-11-07

## Hardware
- Board: NUCLEO-C031C6 (STM32C031C6, Cortex-M0+, 32 KB flash in 2 KB pages, 12 KB RAM, 48 MHz) with
  its on-board ST-LINK/V2-1 (SWD + virtual COM port on USART2 PA2/PA3, 115200)
- ESP32-S3 bridge on its CH343 USB-UART port (921600): GPIO17 → PA10 (USART1 RX), PA9 → GPIO18,
  GPIO4 (open-drain) → NRST, GND. 3V3/5V are not connected between the boards.
- OpenOCD for the C0 is the git build in `~/.local/openocd-git` (the system 0.12.0 has no `stm32c0x.cfg`)
- `bench.py halt-dump` and `mem` have F407 constants and give wrong results on the C031

## Commands (always use --json)
- Run Python through uv (`uv run ...`) so it uses `.venv` with the packages in `uv.lock`. If `.venv` is missing, run `uv sync`.
- Build the bootloaders and images: `uv run firmware/boot_c0/build_boot.py --json`
- `uv run python -m stress --json doctor --target c031`, then
  `uv run python -m stress --json run <test> --target c031 [--reset-source esp]`. Commands are in
  `stress/README.md`; `plan` and `report` do not touch the board, `--sim` runs without hardware.
- ESP32 bridge: build with `uv run esp32/build.py --json`. Uploading it is a human step.

Every result has `ok`, `error_type`, `summary`, and `likely_causes` fields.

## Prohibited
- Do NOT CHANGE `bench.py`, `bench-c031.toml`, `stress.toml`, `results/` or `stress_runs/`. If a test is
  wrong, tell the human. Changing a test to make it pass is forbidden.
- Do not run `STM32_Programmer_CLI` or `openocd` directly.
- Do not upload to the ESP32 (`arduino-cli upload`, `esptool`, `mpremote`); a human does that.
- Never touch option bytes, read protection (RDP), or mass erase.
- In the firmware, do not use the PA13/PA14 (SWD) pins for anything else.

## Negative checks
Every stress claim needs a control that can fail: the naive bootloader (`naive_control`) must show
unsafe outcomes with the same resets. A test that cannot fail proves nothing.
