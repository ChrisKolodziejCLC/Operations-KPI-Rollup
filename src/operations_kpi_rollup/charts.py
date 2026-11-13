from pathlib import Path
from typing import Any, Dict, Iterable, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


COLORS = {
    "teal": "#147d86",
    "blue": "#2f6f9f",
    "green": "#38856d",
    "purple": "#8a6aa8",
    "red": "#bb514b",
    "amber": "#d78d23",
    "navy": "#102a43",
    "grid": "#d7e2e8",
    "muted": "#627d98",
}


def _new_figure(title: str, subtitle: str):
    fig, ax = plt.subplots(figsize=(10.75, 3.8), dpi=80)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.suptitle(title, x=0.03, y=0.97, ha="left", fontsize=15, fontweight="bold", color=COLORS["navy"])
    fig.text(0.03, 0.89, subtitle, ha="left", fontsize=8.5, color=COLORS["muted"])
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#8aa4b5")
    ax.tick_params(axis="both", labelsize=8, colors=COLORS["muted"])
    fig.subplots_adjust(left=0.07, right=0.985, bottom=0.18, top=0.78)
    return fig, ax


def _save(fig, path: Path) -> None:
    fig.savefig(path, format="png", dpi=80, facecolor="white")
    plt.close(fig)


def _date_labels(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["date"][5:].replace("-", "/") for row in rows]


def _daily_throughput(rows: List[Dict[str, Any]], path: Path) -> None:
    fig, ax = _new_figure("Daily Throughput", "Current report week; production days only in trend lines.")
    x = np.arange(len(rows))
    series = [
        ("Parts loaded", "parts_loaded", COLORS["teal"]),
        ("Parts painted", "paint_pieces_processed", COLORS["blue"]),
        ("EOL inspected", "eol_inspected", COLORS["purple"]),
        ("Painted parts shipped", "painted_parts_shipped", COLORS["red"]),
    ]
    for label, field, color in series:
        ax.plot(x, [row.get(field, 0) for row in rows], marker="o", linewidth=2, label=label, color=color)
    ax.set_xticks(x, _date_labels(rows))
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", ncol=4, frameon=False, fontsize=8)
    _save(fig, path)


def _daily_yield(rows: List[Dict[str, Any]], path: Path) -> None:
    fig, ax = _new_figure("Daily First-Pass Quality", "Weighted outcomes retain their numerator and denominator.")
    x = np.arange(len(rows))
    series = [
        ("PPY (Paint Process Yield)", "ppy", COLORS["teal"]),
        ("Paint FTY", "paint_fty", COLORS["blue"]),
        ("Receiving FTY", "receiving_fty", COLORS["green"]),
        ("Final FTY", "final_fty", COLORS["purple"]),
    ]
    for label, field, color in series:
        values = [float(row[field] * 100) if row.get(field) is not None else np.nan for row in rows]
        ax.plot(x, values, marker="o", linewidth=2, label=label, color=color)
    ax.set_xticks(x, _date_labels(rows))
    ax.set_ylim(50, 101)
    ax.set_yticks([50, 60, 70, 80, 90, 100], ["50%", "60%", "70%", "80%", "90%", "100%"])
    ax.legend(loc="upper left", ncol=4, frameon=False, fontsize=8)
    _save(fig, path)


def _painter_throughput(rows: List[Dict[str, Any]], path: Path) -> None:
    fig, ax = _new_figure("Daily Painter Throughput", "Parts associated with each painter and booth session.")
    dates = sorted({row["date"] for row in rows})
    painters = sorted({row["painter"] for row in rows})
    palette = [COLORS["navy"], "#3f7fbf", "#6ba377", "#9ac7b5", COLORS["amber"], COLORS["purple"]]
    x = np.arange(len(dates))
    for index, painter in enumerate(painters):
        by_date = {row["date"]: row.get("parts", 0) for row in rows if row["painter"] == painter}
        ax.plot(x, [by_date.get(day, 0) for day in dates], marker="o", linewidth=2, label=painter, color=palette[index % len(palette)])
    ax.set_xticks(x, [day[5:].replace("-", "/") for day in dates])
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", ncol=min(4, max(1, len(painters))), frameon=False, fontsize=8)
    _save(fig, path)


def _shipping(rows: List[Dict[str, Any]], path: Path) -> None:
    fig, ax = _new_figure("Current Week Shipping by Line Set", "Daily non-service pieces; total labels appear at the end of each bar.")
    dates = sorted({row["date"] for row in rows})
    line_sets = ["Bumpers", "Chassis Fairings", "Fenders"]
    colors = [COLORS["red"], COLORS["blue"], COLORS["teal"]]
    y = np.arange(len(dates))
    left = np.zeros(len(dates))
    for line_set, color in zip(line_sets, colors):
        values = np.array([
            next((row.get("pieces", 0) for row in rows if row["date"] == day and row["line_set"] == line_set), 0)
            for day in dates
        ])
        ax.barh(y, values, left=left, label=line_set, color=color, height=0.34)
        left += values
    for index, total in enumerate(left):
        ax.text(total + max(left.max() * 0.01, 2), index, f"{int(total):,}", va="center", fontsize=8, color=COLORS["navy"])
    ax.set_yticks(y, [day[5:].replace("-", "/") for day in dates])
    ax.invert_yaxis()
    ax.grid(axis="x", color=COLORS["grid"], linewidth=0.7)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper left", ncol=3, frameon=False, fontsize=8)
    ax.set_xlim(right=max(left.max() * 1.12, 1))
    _save(fig, path)


def generate_charts(context: Dict[str, Any], output_dir: Path) -> Dict[str, Dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    charts: Dict[str, Dict[str, str]] = {}

    def register(key: str, filename: str, title: str, alt: str, renderer, rows) -> None:
        path = output_dir / filename
        renderer(rows, path)
        charts[key] = {"filename": filename, "cid": f"operations-kpi-{key}", "title": title, "alt": alt}

    if len(context["active_daily"]) >= 2:
        register("daily-throughput", "daily-throughput.png", "Daily throughput", "Daily throughput trend", _daily_throughput, context["active_daily"])
        register("daily-yield", "daily-yield.png", "Daily first-pass quality", "Daily first-pass quality trend", _daily_yield, context["active_daily"])
    if len({row["date"] for row in context["painters"]}) >= 2:
        register("painter-throughput", "painter-throughput.png", "Painter throughput", "Daily painter throughput", _painter_throughput, context["painters"])
    if context["shipping"]:
        register("shipping", "shipping-by-line-set.png", "Shipping by line set", "Current week shipping by line set", _shipping, context["shipping"])
    return charts
