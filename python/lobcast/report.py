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
COLORS = {"timestral": "#2a78d6", "ewma": "#eb6834", "touch": "#1baf7a"}
FALLBACK = ["#eda100", "#e87ba4", "#008300"]
STRATEGY_ORDER = ["touch", "ewma", "timestral"]


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
        last = res.path.iloc[-1]["equity"]
        ax.plot(clock(res.path["time"]), res.path["equity"], color=color_for(res.name, i), linewidth=1.3,
                label=f"{res.name}  {fmt(last, 'usd')}")
    ax.axhline(0, color="#bdbab0", linewidth=0.8)
    ax.set_ylabel("PnL incl. rebates (USD)")
    hour_ticks(ax)
    style(ax)
    ax.legend(frameon=False, fontsize=8.5, loc="lower left")
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
    by_level = st.get("reconcile_by_level") or []
    cards = [
        ("Messages replayed", f"{msgs:,}"),
        ("Replay speed", f"{st['messages_per_second'] / 1e6:.2f}M msg/s"),
    ]
    if by_level:
        cards.append(("Top of book exact", f"{100 * (1 - by_level[0] / max(msgs, 1)):.2f}%"))
    else:
        cards.append(("Unknown order IDs", f"{st['unknown_orders']:,}"))
    cards.append(("Hidden executions", f"{st['hidden_executions']:,}"))
    tl = next((t for t in r.forecasts if t.name.lower().startswith("timestral")), None)
    if tl is not None:
        cards.append(("Model latency (live)", f"{1000 * tl.latency_seconds:.0f} ms"))
    return "".join(f"<div class='card'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in cards)


def ticker_section(r: TickerReport) -> str:
    tl = next((t for t in r.forecasts if t.name.lower().startswith("timestral")), None)
    s = r.summaries.set_index("strategy")
    best = s["pnl_usd"].idxmax()
    spread = r.bars["spread_ticks"].median()
    lead = (f"{r.files.ticker} on {r.files.date}{ {'databento': ' (Databento MBO)', 'synthetic': ' (synthetic MBO)'}.get(getattr(r.files, 'kind', ''), '')}. Median spread {spread:.1f} ticks. "
            f"Best strategy by PnL: <b>{html.escape(best)}</b> at {fmt(s.loc[best, 'pnl_usd'], 'usd')}.")
    parts = [f"<section><h2>{r.files.ticker} · {r.files.date}</h2><p class='lead'>{lead}</p>",
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
:root{--ink:#1f1f1d;--muted:#6b6a64;--line:#e6e4dc;--bg:#fbfaf7;--accent:#2a78d6}
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
.muted{color:var(--muted);font-size:12.5px}.note{color:var(--muted);font-size:13px;margin:4px 0 10px}.grid td.l{text-align:left}
.banner{background:#fdf0e6;border:1px solid #f2c4a6;color:#7a3311;border-radius:10px;padding:12px 16px;margin:16px 0;font-weight:500}
.notes{background:#fff;border:1px solid var(--line);border-radius:10px;padding:6px 20px}.notes li{margin:6px 0}
@media (max-width:700px){.pair{grid-template-columns:1fr}.grid{font-size:12.5px}.grid th,.grid td{padding:6px 8px}}
"""


def ci_text(mean, lo, hi, kind="usd") -> str:
    if not np.isfinite(lo):
        return f"{fmt(mean, kind)} <span class='muted'>(CI needs 2+ days)</span>"
    return f"{fmt(mean, kind)} <span class='muted'>[{fmt(lo, kind)}, {fmt(hi, kind)}]</span>"


def cumulative_chart(days: pd.DataFrame, ticker: str) -> str:
    g = days[days["ticker"] == ticker]
    dates = sorted(g["date"].unique())
    fig, ax = plt.subplots(figsize=(9.6, 3.0))
    names = [n for n in STRATEGY_ORDER if n in set(g["strategy"])] + sorted(set(g["strategy"]) - set(STRATEGY_ORDER))
    for i, name in enumerate(names):
        series = g[g["strategy"] == name].set_index("date").reindex(dates)["pnl_usd"].fillna(0).cumsum()
        ax.plot(range(len(dates)), series.to_numpy(), color=color_for(name, i), linewidth=2, marker="o", markersize=4,
                label=f"{name}  {fmt(series.iloc[-1], 'usd')}")
    ax.axhline(0, color="#bdbab0", linewidth=0.8)
    step = max(1, len(dates) // 10)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels([dates[k][5:] for k in range(0, len(dates), step)])
    ax.set_ylabel("Cumulative PnL (USD)")
    style(ax)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    return png(fig)


def ci_chart(agg: pd.DataFrame) -> str:
    tickers = list(agg["ticker"].unique())
    fig, axes = plt.subplots(1, len(tickers), figsize=(max(4.6, 3.2 * len(tickers)), 2.8), squeeze=False)
    for ax, ticker in zip(axes[0], tickers):
        g = agg[agg["ticker"] == ticker].set_index("strategy")
        names = [n for n in STRATEGY_ORDER if n in g.index] + sorted(set(g.index) - set(STRATEGY_ORDER))
        for k, name in enumerate(names):
            row = g.loc[name]
            c = color_for(name, k)
            if np.isfinite(row["ci_low"]):
                ax.plot([row["ci_low"], row["ci_high"]], [k, k], color=c, linewidth=2, solid_capstyle="round")
            ax.plot([row["mean_daily_pnl"]], [k], marker="o", markersize=8, color=c, markeredgecolor="white", markeredgewidth=2)
        ax.axvline(0, color="#bdbab0", linewidth=0.8)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names)
        ax.set_ylim(-0.6, len(names) - 0.4)
        ax.set_title(ticker, fontsize=10, color=INK, loc="left")
        ax.set_xlabel("Mean daily PnL, 95% CI (USD)")
        style(ax)
    fig.tight_layout()
    return png(fig)


def multiday_section(days: pd.DataFrame, agg: pd.DataFrame, paired: pd.DataFrame, paired_sk: pd.DataFrame) -> str:
    n_days = days.groupby("ticker")["date"].nunique()
    head = (f"<section><h2>Across days</h2><p class='lead'>{int(n_days.sum())} stock-days "
            f"({', '.join(f'{t}: {n}' for t, n in n_days.items())}). Intervals are 95% bootstrap confidence intervals over days; "
            "p-values come from a paired sign-flip test.</p>")
    rows = []
    for _, r in agg.iterrows():
        rows.append(f"<tr><th>{html.escape(r['ticker'])}</th><td class='l'>{html.escape(r['strategy'])}</td><td>{int(r['days'])}</td>"
                    f"<td>{ci_text(r['mean_daily_pnl'], r['ci_low'], r['ci_high'])}</td><td>{fmt(r['win_rate'], 'pct')}</td>"
                    f"<td>{fmt(r['daily_t_stat'])}</td><td>{fmt(r['mean_drawdown'], 'usd')}</td><td>{fmt(r['mean_uptime'], 'pct')}</td></tr>")
    agg_html = ("<h3>Daily PnL by strategy</h3><table class='grid'><thead><tr><th>Ticker</th><th class='l'>Strategy</th><th>Days</th>"
                "<th>Mean daily PnL [95% CI]</th><th>Profitable days</th><th>t-stat</th><th>Avg max drawdown</th><th>Two-sided uptime</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>")
    parts = [head, agg_html, f"<img src='data:image/png;base64,{ci_chart(agg)}' alt='Mean daily PnL with confidence intervals'>"]
    for ticker in days["ticker"].unique():
        if n_days[ticker] > 1:
            parts.append(f"<img src='data:image/png;base64,{cumulative_chart(days, ticker)}' alt='Cumulative PnL {html.escape(ticker)}'>")

    if not paired.empty:
        kinds = {"Daily PnL (USD)": "usd", "Max drawdown (USD)": "usd", "Two-sided uptime": "pct", "Minute Sharpe": "num"}
        rows = []
        for _, r in paired.iterrows():
            k = kinds.get(r["metric"], "num")
            rows.append(f"<tr><th>{html.escape(str(r['ticker']))}</th><td class='l'>{html.escape(r['metric'])}</td><td>{int(r['days'])}</td>"
                        f"<td>{ci_text(r['mean_diff'], r['ci_low'], r['ci_high'], k)}</td><td>{fmt(r['a_better_days'], 'pct')}</td>"
                        f"<td>{fmt(r['p_value'])}</td></tr>")
        parts.append("<h3>Timestral minus EWMA, paired by day</h3><p class='note'>Positive means Timestral was higher. For drawdown, higher means a smaller loss.</p>"
                     "<table class='grid'><thead><tr><th>Ticker</th><th class='l'>Metric</th><th>Days</th><th>Mean difference [95% CI]</th>"
                     f"<th>Days Timestral higher</th><th>p-value</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
    if not paired_sk.empty:
        names = {"vol_bps": "Volatility", "spread_ticks": "Spread"}
        rows = []
        for _, r in paired_sk.iterrows():
            rows.append(f"<tr><th>{html.escape(r['ticker'])}</th><td class='l'>{names.get(r['target'], r['target'])}</td><td>{int(r['days'])}</td>"
                        f"<td>{ci_text(r['pinball_reduction'], r['ci_low'], r['ci_high'], 'pct')}</td><td>{fmt(r['a_better_days'], 'pct')}</td>"
                        f"<td>{fmt(r['p_value'])}</td></tr>")
        parts.append("<h3>Forecast skill: pinball loss reduction vs EWMA</h3>"
                     "<table class='grid'><thead><tr><th>Ticker</th><th class='l'>Target</th><th>Days</th><th>Reduction [95% CI]</th>"
                     f"<th>Days Timestral better</th><th>p-value</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
    parts.append("</section>")
    return "".join(parts)


def render(reports: list[TickerReport], notes: list[str], multi_html: str = "", detail_note: str = "") -> str:
    tickers = ", ".join(r.files.ticker for r in reports)
    model = next((t.name for r in reports for t in r.forecasts if t.name.lower().startswith("timestral")), "no model")
    sections = "".join(ticker_section(r) for r in reports)
    note_html = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
    synthetic = [r.files.ticker for r in reports if getattr(r.files, "kind", "") == "synthetic"]
    banner = (f"<div class='banner'>Synthetic data ({html.escape(', '.join(synthetic))}): generated order flow with no informed traders, "
              "used to exercise the pipeline. PnL here says nothing about real markets.</div>") if synthetic else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>lobcast backtest</title><style>{CSS}</style></head><body><main>
<h1>Market-making backtest on LOBSTER L3</h1>
<p class="sub">{html.escape(tickers)} · C++ FIFO order book with queue-position fills · {html.escape(model)} quantile forecasts</p>
{multi_html}
{banner}
{f"<p class='note'>{html.escape(detail_note)}</p>" if detail_note else ""}
{sections}
<h2>Assumptions</h2><ul class="notes">{note_html}</ul>
</main></body></html>"""
