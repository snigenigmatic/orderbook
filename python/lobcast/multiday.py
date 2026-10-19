from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .bars import replay_bars
from .forecast import ForecastTable, TimestralModel, ewma_baseline, score, valid_indices, walk_forward
from .metrics import summarize
from .strategy import MarketMaker, MarketMakerParams, RunResult


@dataclass
class DayOutcome:
    source: object
    bars: pd.DataFrame
    stats: dict
    tables: list[ForecastTable] = field(default_factory=list)
    results: list[RunResult] = field(default_factory=list)
    summaries: pd.DataFrame = field(default_factory=pd.DataFrame)
    skill: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def date(self) -> str:
        return self.source.date

    @property
    def ticker(self) -> str:
        return self.source.ticker


def combine(days: list[DayOutcome]) -> tuple[pd.DataFrame, np.ndarray]:
    frames = []
    offsets = []
    start = 0
    for i, d in enumerate(days):
        f = d.bars.copy()
        f["day"] = i
        frames.append(f)
        offsets.append(start)
        start += len(f)
    return pd.concat(frames, ignore_index=True), np.array(offsets)


def split(table: ForecastTable, frame: pd.DataFrame, offsets: np.ndarray, days: list[DayOutcome]) -> dict[str, ForecastTable]:
    day_of = frame["day"].to_numpy()[table.bar_index]
    out = {}
    for i, d in enumerate(days):
        mask = day_of == i
        if not mask.any():
            continue
        sub = table.subset(mask)
        sub.bar_index = sub.bar_index - offsets[i]
        out[d.date] = sub
    return out


def cache_path(cache: Path, ticker: str, date: str, slug: str, bar_seconds: float, context: int) -> Path:
    return cache / f"{ticker}_{date}_{slug}_{int(bar_seconds)}s_ctx{context}.npz"


def timestral_tables(
    days: list[DayOutcome],
    model_id: str,
    cache: Path,
    bar_seconds: float,
    context: int,
    batch_size: int,
    refresh: bool,
    model_cache: dict,
    device: str | None = None,
    threads: int | None = None,
) -> dict[str, ForecastTable]:
    slug = model_id.split("/")[-1]
    cache.mkdir(parents=True, exist_ok=True)
    ticker = days[0].ticker
    out: dict[str, ForecastTable] = {}
    missing = []
    for i, d in enumerate(days):
        p = cache_path(cache, ticker, d.date, slug, bar_seconds, context)
        if p.exists() and not refresh:
            out[d.date] = ForecastTable.load(p)
        else:
            missing.append(i)
    if not missing:
        return out

    frame, offsets = combine(days)
    idx = valid_indices(frame, 30)
    idx = idx[np.isin(frame["day"].to_numpy()[idx], missing)]
    if model_id not in model_cache:
        print(f"  loading {model_id}")
        model_cache[model_id] = TimestralModel(model_id, device=device, threads=threads)
    print(f"  {slug}: forecasting {len(idx):,} bars over {len(missing)} day(s)")
    table = walk_forward(model_cache[model_id], frame, horizon=1, context_bars=context, batch_size=batch_size, indices=idx, progress=True)
    for date, sub in split(table, frame, offsets, days).items():
        sub.save(cache_path(cache, ticker, date, slug, bar_seconds, context))
        out[date] = sub
    return out


def ewma_tables(days: list[DayOutcome]) -> dict[str, ForecastTable]:
    frame, offsets = combine(days)
    return split(ewma_baseline(frame, horizon=1), frame, offsets, days)


def run_ticker(
    sources: list,
    params: MarketMakerParams,
    bar_seconds: float = 10.0,
    model_id: str | None = "mistralai/Timestral-209M",
    cache: Path = Path("out/cache"),
    context: int = 512,
    batch_size: int = 32,
    refresh: bool = False,
    model_cache: dict | None = None,
    device: str | None = None,
    threads: int | None = None,
) -> list[DayOutcome]:
    model_cache = {} if model_cache is None else model_cache
    days = []
    for src in sources:
        bars, stats = replay_bars(src, bar_seconds)
        print(f"  {src.date}: replayed {stats['messages']:,} messages at {stats['messages_per_second'] / 1e6:.2f}M msg/s")
        days.append(DayOutcome(src, bars, stats))

    ew = ewma_tables(days)
    tl = timestral_tables(days, model_id, Path(cache), bar_seconds, context, batch_size, refresh, model_cache, device, threads) if model_id else {}
    if model_id:
        name = model_id.split("/")[-1]
        for t in tl.values():
            t.name = name

    for d in days:
        tables = []
        if d.date in tl:
            tables.append(tl[d.date])
        tables.append(ew[d.date])
        d.tables = tables
        sk = score(tables)
        sk.insert(0, "date", d.date)
        sk.insert(0, "ticker", d.ticker)
        d.skill = sk

        strategies = [("touch", None), ("ewma", ew[d.date])]
        if d.date in tl:
            strategies.append(("timestral", tl[d.date]))
        rows = []
        for name, table in strategies:
            result = MarketMaker(name, params, table).run(d.source, d.bars)
            d.results.append(result)
            rows.append({"ticker": d.ticker, "date": d.date, **summarize(result)})
        d.summaries = pd.DataFrame(rows)
        line = "  ".join(f"{r['strategy']} ${r['pnl_usd']:,.0f}" for r in rows)
        print(f"  {d.date}: {line}")
    return days
