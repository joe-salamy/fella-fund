"""The PNG chart embedded in the newsletter: the fund vs. the same money in each benchmark."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

# Validated categorical slots (light mode), see the site template for the dark steps.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
CONTRIBUTED = "#898781"
SURFACE, INK, INK2, MUTED, GRID, AXIS = (
    "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7")


def _short_money(x: float, _=None) -> str:
    if abs(x) >= 1e6:
        return f"${x / 1e6:.2f}".rstrip("0").rstrip(".") + "M"
    if abs(x) >= 1e3:
        return f"${x / 1e3:.0f}K"
    return f"${x:.0f}"


def render(report: dict, path: Path) -> Path:
    h = report["history"]
    dates = [date.fromisoformat(d) for d in h["dates"]]
    series = [(report["fund_name"], h["fund"])] + [
        (f"{b['name']} ({b['ticker']})", h["bench"][b["ticker"]]) for b in report["benchmarks"]
    ]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ax.plot(dates, h["contributed"], color=CONTRIBUTED, lw=1.5,
            drawstyle="steps-post", label="Money put in")
    for (label, ys), color, z in zip(series, SERIES, (4, 3, 3)):
        ax.plot(dates, ys, color=color, lw=2, solid_capstyle="round", label=label, zorder=z)
        ax.scatter([dates[-1]], [ys[-1]], s=40, color=color, edgecolors=SURFACE,
                   linewidths=2, zorder=5)

    # Direct-label only the fund's endpoint; the legend carries the rest.
    ax.annotate(_short_money(h["fund"][-1]), (dates[-1], h["fund"][-1]),
                xytext=(8, 0), textcoords="offset points", va="center",
                color=INK, fontsize=10, fontweight="bold")

    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_formatter(FuncFormatter(_short_money))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.margins(x=0.01)
    ax.set_ylim(bottom=0)

    ax.set_title("Fund value vs. the same money in the index", loc="left",
                 color=INK, fontsize=12, fontweight="bold", pad=24)
    leg = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=4, frameon=False,
                    fontsize=9, handlelength=1.4, borderaxespad=0.2)
    for t in leg.get_texts():
        t.set_color(INK2)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path
