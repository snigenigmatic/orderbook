from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .data import SAMPLE_TICKERS, discover_days, fetch_sample
from .multiday import run_ticker
from .report import TickerReport, multiday_section, render
from .stats import aggregate_days, paired_compare, paired_skill
from .strategy import MarketMakerParams


def select_days(args, ticker: str) -> list:
    days = discover_days(args.data, ticker, args.levels)
    if not days and args.fetch:
        print("  fetching LOBSTER sample")
        fetch_sample(ticker, args.data, args.levels)
        days = discover_days(args.data, ticker, args.levels)
    if args.start:
        days = [d for d in days if d.date >= args.start]
    if args.end:
        days = [d for d in days if d.date <= args.end]
    if not days:
        raise SystemExit(f"no data for {ticker} in {args.data}; try `lobcast fetch` or `lobcast databento-fetch`")
    return days


def notes_for(args, latency_ms: float | None, kinds: set[str]) -> list[str]:
    notes = [
        f"Own orders reach the exchange {args.latency * 1000:.1f} ms after the decision, and cancels take the same time. Fills that happen inside that window still count.",
        "Own orders join the back of the real FIFO queue. A fill happens only when an execution hits an order that arrived after ours, trades through our price, or a hidden order executes at our price (displayed orders have priority on NASDAQ).",
        "No market impact: our fills do not remove liquidity from the replayed book, and the market does not react to our quotes. This flatters fill counts at the touch.",
        "Quotes are post-only. An order that would cross on arrival is rejected rather than taking liquidity.",
        "PnL marks inventory at the mid and includes a maker rebate of $0.0020 per share. Each day starts flat and is run independently.",
        "Forecasts are walk-forward: the forecast for bar t+1 uses bars up to t only (including earlier days, so the model starts each morning with context) and becomes usable at the bar close plus the model's measured single-series latency"
        + (f" ({latency_ms:.0f} ms on this machine)." if latency_ms else "."),
        "The pull rule compares the forecast 90th percentile of next-bar volatility against the 97.5th percentile of realized volatility over the previous hour, using bars that had already closed.",
    ]
    if "lobster" in kinds:
        notes.append("The 10-level LOBSTER file omits messages for orders deeper than level 10. The replay reconciles against LOBSTER's own snapshot after every message; corrections at the top of book are reported above.")
    if "synthetic" in kinds:
        notes.append("Synthetic days come from `lobcast synth`: random order flow with intraday volatility patterns but no informed traders, so market making looks far too easy. They exist to test the plumbing.")
    if "databento" in kinds or "synthetic" in kinds:
        notes.append("Databento MBO days are rebuilt from the start-of-day snapshot plus every add, cancel and modify. Fill records set queue priority; the cancel that follows removes the volume. A trade with no matching fill is treated as a hidden-order execution.")
    notes.append("Confidence intervals are over trading days. A handful of days can rule out large effects but not small ones.")
    return notes


def run(args) -> None:
    params = MarketMakerParams(order_latency=args.latency, quote_size=args.size, max_position=args.max_position)
    model_id = None if args.no_model else args.model
    model_cache: dict = {}
    reports, all_days, all_skill, kinds = [], [], [], set()
    for ticker in args.tickers:
        sources = select_days(args, ticker)
        print(f"[{ticker}] {len(sources)} day(s): {sources[0].date} to {sources[-1].date}")
        kinds |= {s.kind for s in sources}
        days = run_ticker(sources, params, args.bar_seconds, model_id, Path(args.cache), args.context,
                          args.batch_size, args.refresh, model_cache, args.device, args.threads)
        for d in days:
            all_days.append(d.summaries)
            all_skill.append(d.skill)
        last = days[-1]
        reports.append(TickerReport(last.source, last.bars, last.stats, last.tables, last.skill.drop(columns=["ticker", "date"]),
                                    last.results, last.summaries.drop(columns=["ticker", "date"])))

    day_summaries = pd.concat(all_days, ignore_index=True)
    day_skill = pd.concat(all_skill, ignore_index=True)
    multi = day_summaries.groupby("ticker")["date"].nunique().max() > 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    multi_html, detail_note = "", ""
    if multi:
        agg = aggregate_days(day_summaries)
        paired = paired_compare(day_summaries, "timestral", "ewma") if model_id else pd.DataFrame()
        tl_name = model_id.split("/")[-1] if model_id else None
        paired_sk = paired_skill(day_skill, tl_name, "EWMA") if model_id else pd.DataFrame()
        multi_html = multiday_section(day_summaries, agg, paired, paired_sk)
        detail_note = "The sections below show the most recent day for each ticker in full detail."
        agg.to_csv(out.with_name(out.stem + "_aggregate.csv"), index=False)

    latency_ms = next((t.latency_seconds * 1000 for r in reports for t in r.forecasts if t.name.lower().startswith("timestral")), None)
    out.write_text(render(reports, notes_for(args, latency_ms, kinds), multi_html, detail_note), encoding="utf-8")
    day_summaries.to_csv(out.with_suffix(".csv"), index=False)
    day_skill.to_csv(out.with_name(out.stem + "_skill.csv"), index=False)
    print(f"report written to {out}")


def fetch(args) -> None:
    for ticker in args.tickers:
        files = fetch_sample(ticker, args.data, args.levels)
        print(f"{ticker}: {files.message.name}, {files.orderbook.name}")


def databento_cost(args) -> None:
    from .databento_data import estimate_cost

    table = estimate_cost(args.symbols, args.start, args.end, args.key)
    print(table.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print(f"total ${table['cost_usd'].sum():,.2f} for {table['gigabytes'].sum():,.2f} GB")


def databento_fetch(args) -> None:
    from .databento_data import fetch_days

    days = fetch_days(args.symbols, args.start, args.end, args.data, args.key, args.max_cost)
    print(f"{len(days)} day file(s) in {args.data}")


def synth(args) -> None:
    from .synthetic import synthetic_days

    for i, ticker in enumerate(args.tickers):
        days = synthetic_days(args.data, ticker, args.start, args.days, seed=args.seed + 1000 * i, session_events=args.events)
        print(f"{ticker}: wrote {len(days)} synthetic day(s) to {args.data}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="lobcast")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="download the free LOBSTER sample day")
    f.add_argument("--tickers", nargs="+", default=["AAPL", "MSFT"], choices=SAMPLE_TICKERS)
    f.add_argument("--data", default="data")
    f.add_argument("--levels", type=int, default=10)
    f.set_defaults(func=fetch)

    c = sub.add_parser("databento-cost", help="estimate the cost of NASDAQ MBO days before downloading")
    c.add_argument("--symbols", nargs="+", required=True)
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--key", default=None, help="defaults to DATABENTO_API_KEY")
    c.set_defaults(func=databento_cost)

    d = sub.add_parser("databento-fetch", help="download NASDAQ MBO days, one file per symbol per day")
    d.add_argument("--symbols", nargs="+", required=True)
    d.add_argument("--start", required=True)
    d.add_argument("--end", required=True)
    d.add_argument("--data", default="data")
    d.add_argument("--key", default=None, help="defaults to DATABENTO_API_KEY")
    d.add_argument("--max-cost", type=float, default=None, help="refuse to download if the estimate is above this many USD")
    d.set_defaults(func=databento_fetch)

    s = sub.add_parser("synth", help="write synthetic MBO days to exercise the multi-day pipeline")
    s.add_argument("--tickers", nargs="+", default=["SYN"])
    s.add_argument("--start", default="2024-03-04")
    s.add_argument("--days", type=int, default=5)
    s.add_argument("--events", type=int, default=30_000)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--data", default="data")
    s.set_defaults(func=synth)

    r = sub.add_parser("run", help="replay, forecast, backtest and write the HTML report")
    r.add_argument("--tickers", nargs="+", default=["AAPL", "MSFT"])
    r.add_argument("--data", default="data")
    r.add_argument("--start", default=None, help="first date to include, YYYY-MM-DD")
    r.add_argument("--end", default=None, help="last date to include, YYYY-MM-DD")
    r.add_argument("--levels", type=int, default=10)
    r.add_argument("--fetch", action="store_true", help="download the LOBSTER sample if a ticker has no data")
    r.add_argument("--out", default="out/report.html")
    r.add_argument("--cache", default="out/cache")
    r.add_argument("--model", default="mistralai/Timestral-209M", help="any Timestral checkpoint, e.g. mistralai/Timestral-28M")
    r.add_argument("--no-model", action="store_true", help="skip Timestral and run the baselines only")
    r.add_argument("--context", type=int, default=512, help="bars of history the model sees, across days")
    r.add_argument("--refresh", action="store_true", help="ignore cached forecasts")
    r.add_argument("--device", default=None)
    r.add_argument("--threads", type=int, default=None)
    r.add_argument("--batch-size", type=int, default=32)
    r.add_argument("--bar-seconds", type=float, default=10.0)
    r.add_argument("--latency", type=float, default=0.001)
    r.add_argument("--size", type=int, default=100)
    r.add_argument("--max-position", type=int, default=500)
    r.set_defaults(func=run)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
