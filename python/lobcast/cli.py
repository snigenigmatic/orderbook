from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .bars import replay_bars
from .data import SAMPLE_TICKERS, fetch_sample, find_lobster_files
from .forecast import ForecastTable, TimestralModel, ewma_baseline, score, walk_forward
from .metrics import summarize
from .report import TickerReport, render
from .strategy import MarketMaker, MarketMakerParams


def load_or_forecast(model_cache: dict, args, ticker: str, bars: pd.DataFrame) -> ForecastTable:
    slug = args.model.split("/")[-1]
    cache = Path(args.cache) / f"{ticker}_{slug}_{int(args.bar_seconds)}s.npz"
    if cache.exists() and not args.refresh:
        print(f"  using cached forecasts {cache}")
        return ForecastTable.load(cache)
    if "model" not in model_cache:
        print(f"  loading {args.model}")
        model_cache["model"] = TimestralModel(args.model, device=args.device, threads=args.threads)
    table = walk_forward(model_cache["model"], bars, horizon=1, batch_size=args.batch_size, progress=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    table.save(cache)
    return table


def run(args) -> None:
    reports = []
    model_cache: dict = {}
    all_summaries = []
    for ticker in args.tickers:
        print(f"[{ticker}]")
        try:
            files = find_lobster_files(args.data, ticker, args.levels)
        except FileNotFoundError:
            if not args.fetch:
                raise
            print("  fetching LOBSTER sample")
            files = fetch_sample(ticker, args.data, args.levels)

        bars, stats = replay_bars(files, args.bar_seconds)
        print(f"  replayed {stats['messages']:,} messages at {stats['messages_per_second'] / 1e6:.2f}M msg/s")

        tables = [ewma_baseline(bars, horizon=1)]
        if not args.no_model:
            tables.insert(0, load_or_forecast(model_cache, args, ticker, bars))
        skill = score(tables)

        params = MarketMakerParams(order_latency=args.latency, quote_size=args.size, max_position=args.max_position)
        strategies = [("touch", None), ("ewma", tables[-1])]
        if not args.no_model:
            strategies.append(("timestral", tables[0]))

        results, summaries = [], []
        for name, table in strategies:
            result = MarketMaker(name, params, table).run(files, bars)
            s = summarize(result)
            print(f"  {name:<10} pnl ${s['pnl_usd']:>10,.0f}  fills {s['fills']:>6,}  markout10s {s.get('markout_10s_bps', float('nan')):+.2f} bps")
            results.append(result)
            summaries.append(s)
            all_summaries.append({"ticker": ticker, **s})

        reports.append(TickerReport(files, bars, stats, tables, skill, results, pd.DataFrame(summaries)))

    latency_ms = next((t.latency_seconds * 1000 for r in reports for t in r.forecasts if t.name.lower().startswith("timestral")), None)
    notes = [
        f"Own orders reach the exchange {args.latency * 1000:.1f} ms after the decision, and cancels take the same time. Fills that happen inside that window still count.",
        "Own orders join the back of the real FIFO queue. A fill happens only when a LOBSTER execution hits an order that arrived after ours, trades through our price, or a hidden order executes at our price (displayed orders have priority on NASDAQ).",
        "No market impact: our fills do not remove liquidity from the replayed book, and the market does not react to our quotes. This flatters fill counts at the touch.",
        "Quotes are post-only. An order that would cross on arrival is rejected rather than taking liquidity.",
        "PnL marks inventory at the mid and includes a maker rebate of $0.0020 per share. Taker fees never apply because the strategy never crosses.",
        "Forecasts are walk-forward: the forecast for bar t+1 uses bars up to t only and becomes usable at the bar close plus the model's measured single-series latency"
        + (f" ({latency_ms:.0f} ms on this machine)." if latency_ms else "."),
        "The pull rule compares the forecast 90th percentile of next-bar volatility against the 97.5th percentile of realized volatility over the previous hour, using bars that had already closed.",
        "The 10-level LOBSTER file omits messages for orders deeper than level 10. The replay reconciles against LOBSTER's own snapshot after every message; corrections at the top of book are reported above.",
        "One trading day per ticker (21 June 2012). Treat results as a demonstration of the pipeline, not evidence of a durable edge.",
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(reports, notes), encoding="utf-8")
    pd.DataFrame(all_summaries).to_csv(out.with_suffix(".csv"), index=False)
    print(f"report written to {out}")


def fetch(args) -> None:
    for ticker in args.tickers:
        files = fetch_sample(ticker, args.data, args.levels)
        print(f"{ticker}: {files.message.name}, {files.orderbook.name}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="lobcast")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="download LOBSTER sample days")
    f.add_argument("--tickers", nargs="+", default=["AAPL", "MSFT"], choices=SAMPLE_TICKERS)
    f.add_argument("--data", default="data")
    f.add_argument("--levels", type=int, default=10)
    f.set_defaults(func=fetch)

    r = sub.add_parser("run", help="replay, forecast, backtest and write the HTML report")
    r.add_argument("--tickers", nargs="+", default=["AAPL", "MSFT"])
    r.add_argument("--data", default="data")
    r.add_argument("--levels", type=int, default=10)
    r.add_argument("--fetch", action="store_true", help="download missing sample files")
    r.add_argument("--out", default="out/report.html")
    r.add_argument("--cache", default="out/cache")
    r.add_argument("--model", default="mistralai/Timestral-209M")
    r.add_argument("--no-model", action="store_true", help="skip Timestral and run the baselines only")
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
