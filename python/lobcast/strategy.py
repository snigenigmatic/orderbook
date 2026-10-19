from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ._core import Backtester, Side
from .bars import make_config
from .data import PRICE_SCALE, TICK, LobsterFiles
from .forecast import ForecastTable


@dataclass
class MarketMakerParams:
    quote_size: int = 100
    max_position: int = 500
    decision_interval: float = 1.0
    start: float = 34200.0 + 300.0
    stop: float = 57600.0 - 300.0
    vol_multiplier: float = 1.0
    vol_level: float = 0.9
    pull_level: float = 0.9
    pull_percentile: float = 97.5
    pull_lookback_bars: int = 360
    skew_fraction: float = 1.0
    order_latency: float = 0.001
    maker_rebate: int = 20


@dataclass
class RunResult:
    name: str
    params: MarketMakerParams
    fills: pd.DataFrame
    path: pd.DataFrame
    summary: dict = field(default_factory=dict)


class MarketMaker:
    def __init__(self, name: str, params: MarketMakerParams, forecast: ForecastTable | None = None):
        self.name = name
        self.p = params
        self.forecast = forecast
        self.vol_history: list[float] = []

    def vol_ticks(self, t: float, mid: float) -> float:
        if self.forecast is None:
            return 0.0
        vol_bps = self.forecast.quantile(t, "vol_bps", self.p.vol_level)
        if not math.isfinite(vol_bps):
            return 0.0
        return vol_bps * 1e-4 * mid / TICK

    def should_pull(self, t: float, bars_vol: np.ndarray, bar_end: np.ndarray) -> bool:
        if self.forecast is None:
            return False
        q = self.forecast.quantile(t, "vol_bps", self.p.pull_level)
        if not math.isfinite(q):
            return False
        known = int(np.searchsorted(bar_end, t, side="right"))
        history = bars_vol[max(0, known - self.p.pull_lookback_bars):known]
        if len(history) < 60:
            return False
        return q > np.percentile(history, self.p.pull_percentile)

    def targets(self, bt: Backtester, t: float, bars_vol: np.ndarray, bar_end: np.ndarray) -> tuple[int | None, int | None]:
        if not (bt.has_bid() and bt.has_ask()):
            return None, None
        best_bid, best_ask = bt.best_bid(), bt.best_ask()
        mid = 0.5 * (best_bid + best_ask)

        if self.should_pull(t, bars_vol, bar_end):
            return None, None

        touch_half = 0.5 * (best_ask - best_bid) / TICK
        half = max(touch_half, self.p.vol_multiplier * self.vol_ticks(t, mid))
        skew = self.p.skew_fraction * half * bt.position / self.p.max_position
        reservation = mid / TICK - skew

        bid = int(math.floor(reservation - half)) * TICK
        ask = int(math.ceil(reservation + half)) * TICK
        bid = min(bid, best_ask - TICK)
        ask = max(ask, best_bid + TICK)

        if bt.position + self.p.quote_size > self.p.max_position:
            bid = None
        if bt.position - self.p.quote_size < -self.p.max_position:
            ask = None
        return bid, ask

    def manage_side(self, bt: Backtester, side: Side, price: int | None, orders) -> None:
        live = [o for o in orders if o.side == side and not o.cancel_requested]
        keep = None
        for o in live:
            if keep is None and price is not None and o.price == price:
                keep = o
            else:
                bt.cancel(o.id)
        if keep is None and price is not None:
            bt.submit(side, price, self.p.quote_size)

    def run(self, files: LobsterFiles, bars: pd.DataFrame) -> RunResult:
        p = self.p
        config = make_config(bar_seconds=float(bars["end_time"].diff().median()), order_latency=p.order_latency, maker_rebate=p.maker_rebate)
        bt = Backtester(str(files.message), str(files.orderbook), config)
        bars_vol = bars["vol_bps"].to_numpy(float)
        bar_end = bars["end_time"].to_numpy(float)

        fills: list[dict] = []
        path: list[tuple] = []
        t = p.start
        while t <= p.stop and not bt.done:
            bt.run_until(t)
            for f in bt.take_fills():
                fills.append(fill_row(f))
            bid, ask = self.targets(bt, t, bars_vol, bar_end)
            orders = bt.open_orders()
            self.manage_side(bt, Side.Bid, bid, orders)
            self.manage_side(bt, Side.Ask, ask, orders)
            mid = bt.mid()
            path.append((t, mid, bt.position, bt.cash, bt.rebates, bid is not None, ask is not None))
            t += p.decision_interval

        for o in bt.open_orders():
            bt.cancel(o.id)
        bt.run_until(p.stop + 1.0)
        for f in bt.take_fills():
            fills.append(fill_row(f))
        path.append((bt.now, bt.mid(), bt.position, bt.cash, bt.rebates, False, False))
        bt.run_to_end()

        path_df = pd.DataFrame(path, columns=["time", "mid", "position", "cash", "rebates", "bid_live", "ask_live"])
        path_df["mid"] = path_df["mid"].ffill()
        path_df["equity"] = (path_df["cash"] + path_df["position"] * path_df["mid"] + path_df["rebates"]) / PRICE_SCALE
        fills_df = pd.DataFrame(fills, columns=["time", "order_id", "side", "price", "volume", "queue_at_entry", "resting_seconds", "mid_at_fill"])
        return RunResult(self.name, p, fills_df, path_df)


def fill_row(f) -> dict:
    return {
        "time": f.time,
        "order_id": f.order_id,
        "side": 1 if f.side == Side.Bid else -1,
        "price": f.price,
        "volume": f.volume,
        "queue_at_entry": f.queue_at_entry,
        "resting_seconds": f.resting_seconds,
        "mid_at_fill": f.mid_at_fill,
    }
