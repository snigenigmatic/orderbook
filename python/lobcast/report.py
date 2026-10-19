from __future__ import annotations

import base64
import html
import io
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .data import LobsterFiles
from .forecast import ForecastTable
from .metrics import markouts
from .strategy import RunResult

INK = "#1f1f1d"
MUTED = "#6b6a64"
GRID = "#e6e4dc"
COLORS = {"touch": "#9a988f", "ewma": "#c9822b", "timestral": "#5b4fc4"}
FALLBACK = ["#2a7f62", "#b5446e", "#3d6fa8"]


@dataclass
class TickerReport:
    files: LobsterFiles
    bars: pd.DataFrame
    replay_stats: dict
    forecasts: list[ForecastTable]
    skill: pd.DataFrame
    results: list[RunResult]
    summaries: pd.DataFrame


def color_for(name: str, i: int) -> str:
    return COLORS.get(name.lower(), FALLBACK[i % len(FALLBACK)])


def clock(seconds: np.ndarray) -> np.ndarray:
    return np.asarray(seconds) / 3600.0


def style(ax) -> None:
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#bdbab0")
    ax.tick_params(colors=MUTED, labelsize=8.5)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)


def hour_ticks(ax) -> None:
    ticks = np.arange(10, 16.01, 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{int(h)}:00" for h in ticks])


def png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def forecast_chart(r: TickerReport, table: ForecastTable, target: str, label: str) -> str:
    v = table.targets.index(target)
    lo = int(np.argmin(np.abs(table.levels - 0.1)))
    hi = int(np.argmin(np.abs(table.levels - 0.9)))
    med = int(np.argmin(np.abs(table.levels - 0.5)))
    t = clock(table.available_time)
    actual = table.realized[:, v]

    fig, ax = plt.subplots(figsize=(9.6, 2.9))
    ax.fill_between(t, table.values[:, v, lo], table.values[:, v, hi], color=COLORS["timestral"], alpha=0.18, linewidth=0, label="Forecast 10 to 90%")
    ax.plot(t, table.values[:, v, med], color=COLORS["timestral"], linewidth=0.9, label="Forecast median")
    ax.plot(t, actual, color=INK, linewidth=0.6, alpha=0.75, label="Realized next bar")
    ax.set_ylabel(label)
    top = np.nanpercentile(np.concatenate([actual, table.values[:, v, hi]]), 99.5)
    ax.set_ylim(0, top * 1.05)
    hour_ticks(ax)
    style(ax)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper right")
    return png(fig)


def equity_chart(r: TickerReport) -> str:
    fig, ax = plt.subplots(figsize=(9.6, 3.1))
    for i, res in enumerate(r.results):
        ax.plot(clock(res.path["time"]), res.path["equity"], color=color_for(res.name, i), linewidth=1.3, label=res.name)
        last = res.path.iloc[-1]
        ax.annotate(f"{res.name}  ${last['equity']:,.0f}", (clock([last["time"]])[0], last["equity"]),
                    xytext=(6, 0), textcoords="offset points", fontsize=8, color=color_for(res.name, i), va="center")
    ax.axhline(0, color="#bdbab0", linewidth=0.8)
    ax.set_ylabel("PnL incl. rebates (USD)")
    ax.set_xlim(9.5, 16.6)
    hour_ticks(ax)
    style(ax)
    return png(fig)


def markout_chart(r: TickerReport) -> str:
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    for i, res in enumerate(r.results):
        mk = markouts(res)
        ax.plot(mk["horizon"], mk["markout_bps"], marker="o", markersize=3.5, color=color_for(res.name, i), linewidth=1.3, label=res.name)
    ax.axhline(0, color="#bdbab0", linewidth=0.8)
    ax.set_xscale("log")
    ax.set_xticks([1, 5, 10, 30, 60])
    ax.set_xticklabels(["1s", "5s", "10s", "30s", "60s"])
    ax.set_ylabel("Markout per share (bps)")
    style(ax)
    ax.legend(frameon=False, fontsize=8)
    return png(fig)


def inventory_chart(r: TickerReport) -> str:
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    for i, res in enumerate(r.results):
        ax.plot(clock(res.path["time"]), res.path["position"], color=color_for(res.name, i), linewidth=0.8, alpha=0.9, label=res.name)
    ax.axhline(0, color="#bdbab0", linewidth=0.8)
    ax.set_ylabel("Inventory (shares)")
    hour_ticks(ax)
    style(ax)
    ax.legend(frameon=False, fontsize=8)
    return png(fig)


def fmt(v, kind: str = "num") -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    if kind == "usd":
        return f"{'-' if v < 0 else ''}${abs(v):,.0f}"
    if kind == "pct":
        return f"{100 * v:.1f}%"
    if kind == "int":
        return f"{int(v):,}"
    if kind == "bps":
        return f"{v:+.2f}"
    return f"{v:,.2f}"


STRATEGY_ROWS = [
    ("PnL incl. rebates", "pnl_usd", "usd"),
    ("PnL excl. rebates", "pnl_ex_rebates_usd", "usd"),
    ("Max drawdown", "max_drawdown_usd", "usd"),
    ("Minute Sharpe (t-stat)", "minute_sharpe", "num"),
    ("Fills", "fills", "int"),
    ("Shares traded", "shares", "int"),
    ("Two-sided uptime", "two_sided_uptime", "pct"),
    ("Avg |inventory|", "avg_abs_position", "num"),
    ("Spread capture (bps)", "spread_capture_bps", "bps"),
    ("Markout 10s (bps)", "markout_10s_bps", "bps"),
    ("Markout 60s (bps)", "markout_60s_bps", "bps"),
    ("Median queue ahead at entry", "queue_at_entry_median", "int"),
    ("Close inventory", "close_position", "int"),
]


def strategy_table(r: TickerReport) -> str:
    s = r.summaries.set_index("strategy")
    best = s["pnl_usd"].idxmax()
    head = "".join(f"<th class='{ 'win' if n == best else ''}'>{html.escape(n)}</th>" for n in s.index)
    body = []
    for label, key, kind in STRATEGY_ROWS:
        if key not in s.columns:
            continue
        cells = "".join(f"<td>{fmt(s.loc[n, key], kind)}</td>" for n in s.index)
        body.append(f"<tr><th>{label}</th>{cells}</tr>")
    return f"<table class='grid'><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def skill_table(r: TickerReport) -> str:
    names = {"vol_bps": "Volatility (bps / 10s)", "spread_ticks": "Spread (ticks)"}
    rows = []
    for target, group in r.skill.groupby("target", sort=False):
        best = group["pinball"].min()
        for _, row in group.iterrows():
            win = " class='win'" if row["pinball"] == best else ""
            rows.append(
                f"<tr><th>{names.get(target, target)}</th><td{win}>{html.escape(row['model'])}</td>"
                f"<td{win}>{row['pinball']:.4f}</td><td>{row['median_mae']:.3f}</td>"
                f"<td>{100 * row['coverage_80']:.1f}%</td><td>{row['band_width_80']:.3f}</td></tr>"
            )
    return ("<table class='grid'><thead><tr><th>Target</th><th>Model</th><th>Pinball loss</th>"
            "<th>Median MAE</th><th>80% band coverage</th><th>80% band width</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def engine_cards(r: TickerReport) -> str:
    st = r.replay_stats
    msgs = st["messages"]
    by_level = st.get("reconcile_by_level") or [0]
    l1_clean = 1 - by_level[0] / max(msgs, 1)
    cards = [
        ("Messages replayed", f"{msgs:,}"),
        ("Replay speed", f"{st['messages_per_second'] / 1e6:.2f}M msg/s"),
        ("Top of book exact", f"{100 * l1_clean:.2f}%"),
        ("Hidden executions", f"{st['hidden_executions']:,}"),
    ]
    tl = next((t for t in r.forecasts if t.name.lower().startswith("timestral")), None)
    if tl is not None:
        cards.append(("Model latency (live)", f"{1000 * tl.latency_seconds:.0f} ms"))
    return "".join(f"<div class='card'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in cards)


def ticker_section(r: TickerReport) -> str:
    tl = next((t for t in r.forecasts if t.name.lower().startswith("timestral")), None)
    s = r.summaries.set_index("strategy")
    best = s["pnl_usd"].idxmax()
    spread = r.bars["spread_ticks"].median()
    lead = (f"{r.files.ticker} on {r.files.date}. Median spread {spread:.1f} ticks. "
            f"Best strategy by PnL: <b>{html.escape(best)}</b> at {fmt(s.loc[best, 'pnl_usd'], 'usd')}.")
    parts = [f"<section><h2>{r.files.ticker}</h2><p class='lead'>{lead}</p>",
             f"<div class='cards'>{engine_cards(r)}</div>",
             "<h3>Strategies</h3>", strategy_table(r),
             f"<img src='data:image/png;base64,{equity_chart(r)}' alt='Equity curves'>",
             "<div class='pair'>",
             f"<img src='data:image/png;base64,{markout_chart(r)}' alt='Markouts'>",
             f"<img src='data:image/png;base64,{inventory_chart(r)}' alt='Inventory'>",
             "</div>",
             "<h3>Forecast skill, next 10s bar, walk-forward</h3>", skill_table(r)]
    if tl is not None:
        parts.append(f"<img src='data:image/png;base64,{forecast_chart(r, tl, 'vol_bps', 'Volatility (bps / 10s)')}' alt='Volatility forecast'>")
        parts.append(f"<img src='data:image/png;base64,{forecast_chart(r, tl, 'spread_ticks', 'Spread (ticks)')}' alt='Spread forecast'>")
    parts.append("</section>")
    return "".join(parts)


CSS = """
:root{--ink:#1f1f1d;--muted:#6b6a64;--line:#e6e4dc;--bg:#fbfaf7;--accent:#5b4fc4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1000px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:28px;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:22px;margin:48px 0 6px;padding-top:24px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:28px 0 10px;color:var(--muted);font-weight:600;text-transform:none}
.sub{color:var(--muted);margin:0 0 24px}.lead{margin:0 0 16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}.k{font-size:12px;color:var(--muted)}.v{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
table.grid{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden;font-variant-numeric:tabular-nums;font-size:14px}
.grid th,.grid td{padding:7px 12px;border-bottom:1px solid var(--line);text-align:right}.grid tr:last-child th,.grid tr:last-child td{border-bottom:0}
.grid th:first-child{text-align:left;font-weight:500;color:var(--muted)}.grid thead th{background:#f4f2ec;color:var(--ink);font-weight:600}
.win{color:var(--accent);font-weight:600}
img{width:100%;height:auto;margin-top:14px;background:#fff;border:1px solid var(--line);border-radius:10px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.notes{background:#fff;border:1px solid var(--line);border-radius:10px;padding:6px 20px}.notes li{margin:6px 0}
@media (max-width:700px){.pair{grid-template-columns:1fr}.grid{font-size:12.5px}.grid th,.grid td{padding:6px 8px}}
"""


def render(reports: list[TickerReport], notes: list[str]) -> str:
    tickers = ", ".join(r.files.ticker for r in reports)
    model = next((t.name for r in reports for t in r.forecasts if t.name.lower().startswith("timestral")), "no model")
    sections = "".join(ticker_section(r) for r in reports)
    note_html = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>lobcast backtest</title><style>{CSS}</style></head><body><main>
<h1>Market-making backtest on LOBSTER L3</h1>
<p class="sub">{html.escape(tickers)} · C++ FIFO order book with queue-position fills · {html.escape(model)} quantile forecasts</p>
{sections}
<h2>Assumptions</h2><ul class="notes">{note_html}</ul>
</main></body></html>"""
