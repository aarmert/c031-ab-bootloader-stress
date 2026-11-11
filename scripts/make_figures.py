#!/usr/bin/env python3
"""Draw the README figures from results/*/trials.csv and results/*/serial.log.

    uv run scripts/make_figures.py          # writes docs/img/*.png

Reads only the published data in results/. No board, no network.
"""
from __future__ import annotations

import csv
import math
import random
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "docs" / "img"

SWEEP_HOOK = "reset_sweep_20261107-152056"   # sweep 1: on-chip timer, seed 2026
SWEEP_ESP = "reset_sweep_20261107-172507"    # sweep 2: ESP32-S3 pulls NRST, seed 2027
NAIVE = "naive_control_20261107-121450"      # the control, same ESP32 resets
# Short reset-injected A/B runs of the same day (131 trials together)
SHORT = ["reset_random_20261107-121105", "reset_random_20261107-121251",
         "reset_sweep_20261107-122336", "reset_sweep_20261107-122531", "double_fault_20261107-122248"]

# Runs before 2026-11-10 wrote Turkish outcome names
TR = {"YENİ": "NEW", "ESKİ": "OLD", "BEKLİYOR": "PENDING", "ÖLÜ": "DEAD", "YANLIŞ": "WRONG", "BELİRSİZ": "UNCLEAR"}
OUTCOMES = ["PENDING", "NEW", "OLD", "WRONG", "DEAD", "UNCLEAR"]
ACCEPTED = {"PENDING", "NEW", "OLD"}
COLOR = {"PENDING": "#1baf7a", "NEW": "#2a78d6", "OLD": "#6250d6",
         "WRONG": "#e34948", "DEAD": "#52514e", "UNCLEAR": "#eda100"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.dpi": 110,
    "savefig.dpi": 150, "savefig.bbox": "tight", "axes.titlesize": 10, "axes.titlecolor": INK,
})


def trials(run: str) -> list[dict]:
    with open(RES / run / "trials.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["outcome"] = TR.get(r["outcome"], r["outcome"])
    return rows


def legend_handles(names):
    return [plt.Rectangle((0, 0), 1, 1, color=COLOR[n]) for n in names]


# ---------------------------------------------------------------- statistics
def binom_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided interval, by bisection on the binomial CDF."""
    def solve(f, lo=0.0, hi=1.0):
        for _ in range(80):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda p: 1 - binom_cdf(k - 1, n, p) < alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) > alpha / 2)
    return lower, upper


def up3(pct: float) -> str:
    """Round a percentage bound up to 3 decimals, so the printed bound is never below the exact one."""
    return f"{math.ceil(pct * 1000) / 1000:.3f}"


def zero_fail_upper(n: int, conf: float = 0.95) -> float:
    return 1 - (1 - conf) ** (1 / n)


# ---------------------------------------------------------------- figure 1
def fig_outcomes_by_phase():
    runs = [(SWEEP_HOOK, "Sweep 1: on-chip timer reset (1493 trials)"),
            (SWEEP_ESP, "Sweep 2: ESP32-S3 pulls NRST (1479 trials)")]
    order = ["ERASE", "DATA", "HDR", "META", "BOOT", "CONFIRM"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), sharex=False)
    for ax, (run, title) in zip(axes, runs):
        rows = trials(run)
        phases = [p for p in order if any(r["phase"] == p for r in rows)]
        c = Counter((r["phase"], r["outcome"]) for r in rows)
        left = [0] * len(phases)
        for o in OUTCOMES:
            vals = [c[(p, o)] for p in phases]
            if not any(vals):
                continue
            ax.barh(phases, vals, left=left, color=COLOR[o], edgecolor="white", linewidth=1.5, height=0.62)
            left = [a + b for a, b in zip(left, vals)]
        for y, total in enumerate(left):
            ax.text(total + max(left) * 0.015, y, str(total), va="center", fontsize=9, color=INK2)
        bad = sum(1 for r in rows if r["outcome"] not in ACCEPTED)
        ax.set_title(f"{title}\nnot accepted (WRONG / DEAD / UNCLEAR): {bad}", loc="left")
        ax.invert_yaxis()
        ax.set_xlabel("trials")
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, max(left) * 1.12)
    fig.legend(legend_handles(["PENDING", "NEW"]), ["PENDING (update resumed, then NEW)", "NEW"],
               loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.08))
    fig.savefig(OUT / "outcomes_by_phase.png")
    plt.close(fig)


# ---------------------------------------------------------------- figure 2
def fig_delay_scatter():
    rng = random.Random(1)
    hook = trials(SWEEP_HOOK)
    esp = trials(SWEEP_ESP)
    panels = [
        ("Sweep 1 · ERASE: slot erase", hook, "ERASE", 1e-3, "delay (ms)", "jitter"),
        ("Sweep 1 · DATA: packet write", hook, "DATA", 1, "delay (µs)", "index"),
        ("Sweep 1 · HDR: header write", hook, "HDR", 1, "delay (µs)", "jitter"),
        ("Sweep 1 · META: log record", hook, "META", 1, "delay (µs)", "index"),
        ("Sweep 1 · BOOT: boot decision", hook, "BOOT", 1e-3, "delay (ms)", "jitter"),
        ("Sweep 1 · CONFIRM: before confirm", hook, "CONFIRM", 1, "delay (µs)", "jitter"),
        ("Sweep 2 · ERASE (after UPD BEGIN)", esp, "ERASE", 1e-3, "delay (ms)", "jitter"),
        ("Sweep 2 · DATA k (after packet k)", esp, "DATA", 1, "delay (µs)", "index"),
        ("Sweep 2 · HDR (after UPD END), - - commit ≈ 30 ms", esp, "HDR", 1e-3, "delay (ms, log)", "jitter"),
    ]
    fig, axes = plt.subplots(3, 3, figsize=(12, 9.2))
    for ax, (title, rows, phase, scale, xlabel, ymode) in zip(axes.flat, panels):
        sel = [r for r in rows if r["phase"] == phase]
        for o in OUTCOMES:
            pts = [r for r in sel if r["outcome"] == o]
            if not pts:
                continue
            xs = [int(r["delay_us"]) * scale for r in pts]
            if ymode == "index":
                ys = [int(r["phase_index"]) + rng.uniform(-0.25, 0.25) for r in pts]
            else:
                ys = [rng.uniform(0, 1) for _ in pts]
            ax.scatter(xs, ys, s=9, color=COLOR[o], alpha=0.8, linewidths=0, label=o)
        ax.set_title(f"{title}  (n={len(sel)})", loc="left")
        ax.set_xlabel(xlabel)
        if ymode == "jitter":
            ax.set_yticks([])
            ax.grid(axis="y", visible=False)
        elif phase == "META":
            idx = sorted({int(r["phase_index"]) for r in sel})
            names = {2: "TRIAL", 3: "ATTEMPT", 4: "CONFIRM"}  # stress/layout.py KIND
            ax.set_yticks(idx, [names.get(i, str(i)) for i in idx])
        else:
            ax.set_ylabel("packet no.")
        if xlabel.endswith("log)"):
            ax.set_xscale("log")
            ax.axvline(31.3, color=INK2, linestyle="--", linewidth=1)
    fig.legend(legend_handles(["PENDING", "NEW"]), ["PENDING", "NEW"], loc="upper right", ncol=2,
               frameon=False, bbox_to_anchor=(0.99, 1.01))
    fig.suptitle("Where each reset landed and what the board did. One dot = one trial. No WRONG anywhere.",
                 x=0.01, ha="left", y=1.0, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(OUT / "delay_scatter.png")
    plt.close(fig)


# ---------------------------------------------------------------- figure 3
def fig_esp_latency():
    late = []
    for r in trials(SWEEP_ESP):
        m = re.search(r"late_us=(\d+)", r["note"])
        if m:
            late.append(int(m.group(1)))
    c = Counter(late)
    xs = list(range(min(late), max(late) + 1))
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(xs, [c[x] for x in xs], color=COLOR["NEW"], width=0.8)
    med = sorted(late)[len(late) // 2]
    ax.set_title(f"ESP32-S3 NRST pulse: how late past the planned moment (sweep 2, n = {len(late)})\n"
                 f"min {min(late)} µs, median {med} µs, max {max(late)} µs", loc="left")
    ax.set_xlabel("late by (µs)")
    ax.set_ylabel("pulses")
    ax.set_xticks(xs)
    ax.grid(axis="x", visible=False)
    fig.savefig(OUT / "esp_latency.png")
    plt.close(fig)
    return min(late), med, max(late), len(late)


# ---------------------------------------------------------------- figure 4
def fig_upper_bound(n_short: int):
    ns = [10 * 1.05**i for i in range(int(math.log(6000 / 10) / math.log(1.05)) + 1)]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(ns, [100 * zero_fail_upper(int(n)) for n in ns], color=COLOR["NEW"], linewidth=2,
            label="exact: 1 − 0.05^(1/N)")
    ax.plot(ns, [300 / n for n in ns], color=INK2, linewidth=1, linestyle="--", label="rule of three: 3/N")
    n_all = n_short + 1493 + 1479
    pts = [(n_short, f"short runs: N={n_short} → {up3(100 * zero_fail_upper(n_short))}%", (1.12, 1.25)),
           (1486, "sweep 1 / sweep 2: N=1493 / 1479 → 0.201% / 0.203%", (1.1, 1.3)),
           (n_all, f"all: N={n_all} → {up3(100 * zero_fail_upper(n_all))}%", (0.42, 0.62))]
    for n, label, (fx, fy) in pts:
        u = 100 * zero_fail_upper(n)
        ax.scatter([n], [u], color=COLOR["NEW"], s=40, zorder=3, edgecolors="white", linewidths=1.5)
        ax.annotate(label, (n, u), xytext=(n * fx, u * fy), fontsize=9, color=INK,
                    ha="left" if fx > 1 else "right")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("trials with zero failures, N (log)")
    ax.set_ylabel("95% upper bound on failure rate (%)")
    ax.set_title("What “0 failures in N trials” allows: the highest failure rate still consistent at 95%",
                 loc="left")
    ax.legend(frameon=False)
    fig.savefig(OUT / "upper_bound.png")
    plt.close(fig)


# ---------------------------------------------------------------- figure 5
def fig_ab_vs_naive(n_ab: int):
    naive = trials(NAIVE)
    ab_esp = trials(SWEEP_ESP) + trials("reset_random_20261107-121251") + trials("reset_sweep_20261107-122336")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1.15, 1]})

    groups = [("A/B bootloader\n(ESP32 NRST resets)", ab_esp), ("naive bootloader\n(same ESP32 resets)", naive)]
    for y, (name, rows) in enumerate(groups):
        c = Counter(r["outcome"] for r in rows)
        left = 0.0
        for o in OUTCOMES:
            if not c[o]:
                continue
            w = 100 * c[o] / len(rows)
            ax1.barh(y, w, left=left, color=COLOR[o], edgecolor="white", linewidth=1.5, height=0.55)
            if w > 6:
                ax1.text(left + w / 2, y, f"{o}\n{c[o]}", ha="center", va="center", color="white", fontsize=8.5)
            left += w
        ax1.text(101, y, f"n={len(rows)}", va="center", fontsize=9, color=INK2)
    ax1.set_yticks([0, 1], [g[0] for g in groups])
    ax1.invert_yaxis()
    ax1.set_xlim(0, 112)
    ax1.set_xlabel("share of trials (%)")
    ax1.grid(axis="y", visible=False)
    ax1.set_title("Outcomes with the same kind of reset", loc="left")

    k_n = sum(r["outcome"] == "WRONG" for r in naive)
    lo_n, hi_n = clopper_pearson(k_n, len(naive))
    up_ab = zero_fail_upper(n_ab)
    rows = [("A/B, all reset trials", 0.0, 0.0, up_ab, f"0 / {n_ab}  →  < {up3(100 * up_ab)}%"),
            ("naive control", k_n / len(naive), lo_n, hi_n,
             f"{k_n} / {len(naive)}  →  {100 * lo_n:.0f}–{100 * hi_n:.0f}%")]
    for y, (name, p, lo, hi, label) in enumerate(rows):
        col = COLOR["WRONG"] if p > 0 else COLOR["NEW"]
        ax2.plot([100 * lo, 100 * hi], [y, y], color=col, linewidth=3, solid_capstyle="round")
        ax2.scatter([100 * p], [y], color=col, s=60, zorder=3, edgecolors="white", linewidths=1.5)
        ax2.text(100 * hi + 2, y - 0.18, label, fontsize=9, color=INK)
    ax2.set_yticks([0, 1], [r[0] for r in rows])
    ax2.set_ylim(-0.6, 1.6)
    ax2.invert_yaxis()
    ax2.set_xlim(-2, 115)
    ax2.set_xlabel("rate of corrupt image booted (WRONG), 95% interval (%)")
    ax2.grid(axis="y", visible=False)
    ax2.set_title("Failure rate: normal measurement vs negative control", loc="left")
    fig.legend(legend_handles(["PENDING", "NEW", "OLD", "WRONG"]), ["PENDING", "NEW", "OLD", "WRONG (corrupt image ran)"],
               loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.07))
    fig.tight_layout()
    fig.savefig(OUT / "ab_vs_naive.png")
    plt.close(fig)
    return k_n, len(naive), lo_n, hi_n


# ---------------------------------------------------------------- figure 6
def log_counts(run: str) -> dict:
    """The serial log holds each board line twice (V = VCP witness, < = ESP32 side); count the V copy."""
    boots = bad = resume = fired = 0
    with open(RES / run / "serial.log", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            tag, text = parts[1], parts[2]
            if tag == "V" and text.startswith("BL v0.1"):
                boots += 1
                bad += "=bad" in text
            elif tag == "V" and text.startswith("BL resume"):
                resume += 1
            elif tag == "V" and text.startswith("BL fault_fired 1"):
                fired += 1
            elif tag == "E" and text.startswith("ESP NRST FIRED"):
                fired += 1
    return {"boots": boots, "bad": bad, "resume": resume, "fired": fired}


def fig_evidence():
    data = [("Sweep 1 (timer)", SWEEP_HOOK), ("Sweep 2 (ESP32 NRST)", SWEEP_ESP)]
    counts = [(name, log_counts(run), len(trials(run))) for name, run in data]
    metrics = [("trials", None), ("resets fired*", "fired"), ("boots", "boots"),
               ("boots with a\nhalf-written slot", "bad"), ("BL resume\n(waits for PC)", "resume"),
               ("corrupt image ran\n(WRONG)", "wrong")]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    w = 0.38
    for i, (name, c, n) in enumerate(counts):
        vals = [n if k is None else (0 if k == "wrong" else c[k]) for _, k in metrics]
        xs = [j + (i - 0.5) * w for j in range(len(metrics))]
        ax.bar(xs, vals, width=w - 0.04, color=[COLOR["NEW"], COLOR["PENDING"]][i], label=name)
        for x, v in zip(xs, vals):
            ax.text(x, v + 60, str(v), ha="center", fontsize=8.5, color=INK2)
    ax.set_xticks(range(len(metrics)), [m[0] for m in metrics])
    ax.set_ylabel("count")
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, loc="upper right")
    ax.set_title("Did the test do anything? Resets fired and corrupted flash thousands of times; "
                 "the A/B bootloader never booted it\n"
                 "*includes the trial that was cut short when the 2-hour run was stopped", loc="left")
    fig.savefig(OUT / "evidence.png")
    plt.close(fig)
    return counts


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    n_short = sum(len(trials(r)) for r in SHORT)
    n_ab = n_short + len(trials(SWEEP_HOOK)) + len(trials(SWEEP_ESP))
    fig_outcomes_by_phase()
    fig_delay_scatter()
    lat = fig_esp_latency()
    fig_upper_bound(n_short)
    k, n, lo, hi = fig_ab_vs_naive(n_ab)
    ev = fig_evidence()
    print(f"A/B reset-injected trials: {n_ab} (short runs {n_short}); 95% upper bound "
          f"{100 * zero_fail_upper(n_ab):.4f}%, 3/N {300 / n_ab:.4f}%")
    print(f"naive control: {k}/{n} WRONG, Clopper-Pearson 95% [{100 * lo:.1f}%, {100 * hi:.1f}%]")
    print(f"ESP latency: min {lat[0]} median {lat[1]} max {lat[2]} µs, n={lat[3]}")
    for name, c, nt in ev:
        print(f"{name}: trials {nt}, {c}")
    print(f"figures in {OUT.relative_to(ROOT)}: " + ", ".join(sorted(p.name for p in OUT.glob('*.png'))))


if __name__ == "__main__":
    main()
