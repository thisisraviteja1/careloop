#!/usr/bin/env python3
"""Backtest: CareLoop's personal baseline versus fixed inactivity timers on the same data.

This is a SIMULATION that tests the decision logic, not real-world accuracy.

For each setting (persona × morning variability) we generate a deterministic 90-day
first-appearance history with naturally late mornings, inject incident days with no
activity at all, and run every method on exactly the same days. CareLoop is judged with
the production code (`compute_baseline` + `evaluate`), using only the days before the
day being judged.

Usage: python scripts/evaluate.py   (writes docs/evaluation.md, .csv and .png)
"""

from __future__ import annotations

import csv
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.baseline.model import at_minutes, compute_baseline  # noqa: E402
from app.detection.detector import evaluate  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
SEED = 2026
DAYS = 90
WARMUP_DAYS = 21  # days judged start after three weeks, for every method
INCIDENTS = 8
MARGIN = 45
START = date(2026, 6, 1)
LATE_MORNING_PROB = 0.05  # a naturally late morning (slept in, unwell, visitor)
LATE_MORNING_EXTRA = (45, 100)  # minutes later than usual
FIXED_TIMERS = (8 * 60, 9 * 60, 10 * 60)
CAVEAT = ("This is a simulation that tests the logic, not real-world accuracy. Histories are "
          "synthetic; incidents are days with no activity at all.")


@dataclass(frozen=True)
class Persona:
    name: str
    weekday_mean: int  # minutes after midnight
    weekend_mean: int


PERSONAS = (Persona("Early riser (about 7:00 AM)", 7 * 60, 7 * 60 + 25),
            Persona("Late riser (about 8:40 AM)", 8 * 60 + 40, 9 * 60 + 10))
VARIABILITY = (("low", 8), ("medium", 15), ("high", 25))  # standard deviation, minutes


@dataclass(frozen=True)
class Setting:
    persona: Persona
    variability: str
    sd: int


@dataclass(frozen=True)
class History:
    first: dict[date, int | None]  # None = incident day (no activity)
    incidents: frozenset[date]
    judged: tuple[date, ...]


@dataclass(frozen=True)
class MethodResult:
    method: str
    false_alarms: int
    normal_days: int
    missed: int
    incidents: int
    median_delay: float | None
    max_delay: int | None

    @property
    def false_alarm_rate(self) -> float:
        return 100 * self.false_alarms / self.normal_days if self.normal_days else 0.0


def usual_start(persona: Persona, day: date) -> int:
    return persona.weekend_mean if day.weekday() >= 5 else persona.weekday_mean


def simulate(setting: Setting, seed: int = SEED) -> History:
    """Deterministic history for one setting."""
    rng = random.Random(f"{seed}-{setting.persona.name}-{setting.variability}")
    days = [START + timedelta(days=i) for i in range(DAYS)]
    first: dict[date, int | None] = {}
    for day in days:
        minute = rng.gauss(usual_start(setting.persona, day), setting.sd)
        if rng.random() < LATE_MORNING_PROB:
            minute += rng.uniform(*LATE_MORNING_EXTRA)
        first[day] = round(minute)
    judged = tuple(days[WARMUP_DAYS:])
    incidents = frozenset(rng.sample(judged, INCIDENTS))
    for day in incidents:
        first[day] = None
    return History(first, incidents, judged)


def careloop_alert(history: History, day: date, person: str = "Test") -> int | None:
    """Minute CareLoop would alert on `day`, or None. Production code, past data only."""
    past = {d: m for d, m in history.first.items() if d < day and m is not None}
    baseline = compute_baseline(past, day, MARGIN)
    if not baseline.ready or baseline.threshold is None:
        return None
    threshold_at = at_minutes(day, baseline.threshold, TZ)
    today = history.first[day]
    seen = at_minutes(day, today, TZ) if today is not None and today <= baseline.threshold \
        else None
    decision = evaluate(threshold_at, baseline, today_first_activity=seen, last_seen=None,
                        device_ok=True, person_name=person)
    return baseline.threshold if decision.status == "anomaly" else None


def timer_alert(history: History, day: date, timer: int) -> int | None:
    today = history.first[day]
    return timer if today is None or today > timer else None


def score(method: str, history: History, persona: Persona, alerts: dict[date, int | None]
          ) -> MethodResult:
    normal = [d for d in history.judged if d not in history.incidents]
    false_alarms = sum(1 for d in normal if alerts[d] is not None)
    delays = [alerts[d] - usual_start(persona, d) for d in sorted(history.incidents)
              if alerts[d] is not None]
    missed = sum(1 for d in history.incidents if alerts[d] is None)
    return MethodResult(method, false_alarms, len(normal), missed, len(history.incidents),
                        statistics.median(delays) if delays else None,
                        max(delays) if delays else None)


def method_name(timer: int) -> str:
    return f"Fixed timer {timer // 60}:00 AM"


def run_setting(setting: Setting, seed: int = SEED) -> list[MethodResult]:
    history = simulate(setting, seed)
    results = [score("CareLoop baseline", history, setting.persona,
                     {d: careloop_alert(history, d) for d in history.judged})]
    for timer in FIXED_TIMERS:
        results.append(score(method_name(timer), history, setting.persona,
                             {d: timer_alert(history, d, timer) for d in history.judged}))
    return results


def run_all(seed: int = SEED) -> list[tuple[Setting, list[MethodResult]]]:
    return [(s, run_setting(s, seed)) for s in
            (Setting(p, v, sd) for p in PERSONAS for v, sd in VARIABILITY)]


# ---- outputs ---------------------------------------------------------------------------------

def fmt_delay(value: float | None) -> str:
    return "–" if value is None else f"{value:.0f} min"


def write_csv(rows: list[tuple[Setting, list[MethodResult]]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["persona", "variability", "sd_minutes", "method", "false_alarms",
                         "normal_days", "false_alarms_per_100_days", "missed_incidents",
                         "incidents", "median_delay_min", "max_delay_min"])
        for setting, results in rows:
            for r in results:
                writer.writerow([setting.persona.name, setting.variability, setting.sd, r.method,
                                 r.false_alarms, r.normal_days, f"{r.false_alarm_rate:.1f}",
                                 r.missed, r.incidents,
                                 "" if r.median_delay is None else f"{r.median_delay:.0f}",
                                 "" if r.max_delay is None else r.max_delay])


def markdown(rows: list[tuple[Setting, list[MethodResult]]], seed: int) -> str:
    lines = [
        "# Evaluation: personal baseline vs fixed timers", "",
        f"> {CAVEAT}", "",
        "Regenerate with `python scripts/evaluate.py`. Same data for every method; CareLoop "
        "is judged with the production `compute_baseline` and `evaluate` functions, using "
        "only days before the day being judged.", "",
        "**Parameters:** "
        f"seed {seed}; {DAYS} days per setting; first {WARMUP_DAYS} days are history only; "
        f"{INCIDENTS} incident days (no activity) per setting; naturally late mornings on "
        f"{LATE_MORNING_PROB:.0%} of days (+{LATE_MORNING_EXTRA[0]}–{LATE_MORNING_EXTRA[1]} "
        f"min); weekends 25–30 min later; CareLoop margin {MARGIN} min.", "",
        "- **False alarms:** alerts on days the person did appear (out of the normal judged "
        "days).",
        "- **Missed:** incident days with no alert.",
        "- **Delay:** minutes from the person's usual first appearance to the alert, on "
        "incident days (median / worst).", "",
    ]
    for persona in PERSONAS:
        lines += [f"## {persona.name}", "",
                  "| Morning variability | Method | False alarms | Missed "
                  "| Delay (median / worst) |",
                  "|---|---|---|---|---|"]
        for setting, results in rows:
            if setting.persona != persona:
                continue
            for r in results:
                lines.append(
                    f"| {setting.variability} (±{setting.sd} min) | {r.method} | "
                    f"{r.false_alarms} of {r.normal_days} days ({r.false_alarm_rate:.1f}%) | "
                    f"{r.missed} of {r.incidents} | {fmt_delay(r.median_delay)} / "
                    f"{fmt_delay(r.max_delay)} |")
        lines.append("")
    lines += ["## Reading the results", "", summary(rows), "",
              "![False alarms and detection delay by method](evaluation.png)", ""]
    return "\n".join(lines)


def summary(rows: list[tuple[Setting, list[MethodResult]]]) -> str:
    """Worst case per method across every setting, generated from the numbers."""
    methods = [r.method for r in rows[0][1]]
    lines = ["Worst case for each method across all six settings (both people, all three "
             "variability levels), with no per-person tuning:", "",
             "| Method | Most false alarms in any setting | Slowest median delay | "
             "Earliest median alert |", "|---|---|---|---|"]
    for i, method in enumerate(methods):
        results = [res[i] for _, res in rows]
        worst_fa = max(results, key=lambda r: r.false_alarm_rate)
        delays = [r.median_delay for r in results if r.median_delay is not None]
        lines.append(f"| {method} | {worst_fa.false_alarms} of {worst_fa.normal_days} days "
                     f"({worst_fa.false_alarm_rate:.0f}%) | {fmt_delay(max(delays))} | "
                     f"{fmt_delay(min(delays))} |")
    lines += ["",
              "A negative delay means the timer fires before the person usually gets up, so "
              "it alerts on almost every normal day.", "",
              "What this shows, and what it doesn't:", "",
              "- A fixed timer can match CareLoop for one person when it happens to be set "
              "right for them (for the early riser, an 8:00 AM timer has a similar number of "
              "false alarms and a shorter delay than CareLoop). The same timer is wrong for "
              "someone else: no single fixed time works for both people here.",
              "- CareLoop sets its threshold from each person's own history, so it needs no "
              "tuning. The cost is the 45-minute margin after the usual window, which makes "
              "its median delay longer than a well-chosen timer's.",
              "- CareLoop's remaining false alarms come from the naturally late mornings "
              "built into the simulation. That is why the camera check and the elder-first "
              "check-in come before any family member is alerted.",
              "- No method missed an incident, because an incident here is a whole day with "
              "no activity. Partial-activity incidents are not modelled."]
    return "\n".join(lines)


def chart(rows: list[tuple[Setting, list[MethodResult]]], path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed: skipping the chart (pip install -e '.[dev]').")
        return False
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # validated categorical slots 1–4
    ink, ink2, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": grid, "axes.labelcolor": ink2,
                         "xtick.color": ink2, "ytick.color": ink2, "text.color": ink})
    fig, axes = plt.subplots(2, len(PERSONAS), figsize=(11, 7.2), facecolor=surface,
                             sharey="row")
    methods = [r.method for r in rows[0][1]]
    width = 0.2
    for col, persona in enumerate(PERSONAS):
        subset = [(s, r) for s, r in rows if s.persona == persona]
        for row, (metric, title) in enumerate((
                ("rate", "False alarms per 100 normal days"),
                ("delay", "Median minutes from usual time to alert"))):
            ax = axes[row][col]
            ax.set_facecolor(surface)
            for i, method in enumerate(methods):
                xs = [k + (i - 1.5) * width for k in range(len(subset))]
                values = []
                for _, results in subset:
                    r = results[i]
                    values.append(r.false_alarm_rate if metric == "rate"
                                  else (r.median_delay or 0))
                bars = ax.bar(xs, values, width * 0.9, color=colors[i], label=method,
                              edgecolor=surface, linewidth=1, zorder=3)
                for bar, value in zip(bars, values, strict=True):
                    ax.annotate(f"{value:.0f}", (bar.get_x() + bar.get_width() / 2,
                                                 bar.get_height()),
                                xytext=(0, 2 if value >= 0 else -2),
                                textcoords="offset points", ha="center",
                                va="bottom" if value >= 0 else "top", fontsize=8, color=ink2)
            ax.set_xticks(range(len(subset)),
                          [f"{s.variability}\n±{s.sd} min" for s, _ in subset])
            ax.set_title(f"{persona.name}\n{title}" if row == 0 else title, fontsize=10.5,
                         loc="left", color=ink)
            ax.grid(axis="y", color=grid, linewidth=0.8, zorder=0)
            ax.spines[["top", "right", "left"]].set_visible(False)
            ax.tick_params(axis="y", length=0, labelleft=True)
            ax.axhline(0, color=ink2, linewidth=0.8, zorder=4)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, 0.995))
    fig.text(0.5, 0.005, "Simulation of the decision logic on synthetic histories, "
             "not real-world accuracy. Morning variability on the x-axis.",
             ha="center", fontsize=9, color=ink2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(path, dpi=160, facecolor=surface)
    plt.close(fig)
    return True


def main() -> int:
    rows = run_all(SEED)
    docs = REPO_ROOT / "docs"
    docs.mkdir(exist_ok=True)
    write_csv(rows, docs / "evaluation.csv")
    (docs / "evaluation.md").write_text(markdown(rows, SEED), encoding="utf-8")
    drew = chart(rows, docs / "evaluation.png")
    print(CAVEAT, "\n")
    for setting, results in rows:
        print(f"{setting.persona.name}, {setting.variability} variability (±{setting.sd} min)")
        for r in results:
            print(f"  {r.method:<22} false alarms {r.false_alarms:>2}/{r.normal_days}  "
                  f"missed {r.missed}/{r.incidents}  delay median {fmt_delay(r.median_delay)}"
                  f", worst {fmt_delay(r.max_delay)}")
    print("\nWrote docs/evaluation.md, docs/evaluation.csv"
          + (", docs/evaluation.png" if drew else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
