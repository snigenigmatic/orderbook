from __future__ import annotations

import numpy as np
import pandas as pd

from .data import PRICE_SCALE, TICK
from .strategy import RunResult

MARKOUT_HORIZONS = (1, 5, 10, 30, 60)


def mid_at(path: pd.DataFrame, times: np.ndarray) -> np.ndarray:
    t = path["time"].to_numpy(float)
    m = path["mid"].to_numpy(float)
    i = np.clip(np.searchsorted(t, times, side="right") - 1, 0, len(t) - 1)
    return m[i]


def markouts(result: RunResult, horizons=MARKOUT_HORIZONS) -> pd.DataFrame:
    f = result.fills
    if f.empty:
        return pd.DataFrame({"horizon": list(horizons), "markout_bps": [np.nan] * len(horizons)})
    w = f["volume"].to_numpy(float)
    px = f["price"].to_numpy(float)
    side = f["side"].to_numpy(float)
    rows = []
    for h in horizons:
        future = mid_at(result.path, f["time"].to_numpy(float) + h)
        bps = side * (future - px) / px * 1e4
        rows.append({"horizon": h, "markout_bps": float(np.average(bps, weights=w))})
    return pd.DataFrame(rows)


def summarize(result: RunResult) -> dict:
    path, f = result.path, result.fills
    eq = path.set_index(pd.to_timedelta(path["time"], unit="s"))["equity"]
    per_min = eq.resample("60s").last().dropna().diff().dropna()
    drawdown = (eq - eq.cummax()).min()
    last = path.iloc[-1]

    out = {
        "strategy": result.name,
        "pnl_usd": float(last["equity"]),
        "rebates_usd": float(last["rebates"] / PRICE_SCALE),
        "pnl_ex_rebates_usd": float(last["equity"] - last["rebates"] / PRICE_SCALE),
        "close_position": int(last["position"]),
        "max_drawdown_usd": float(drawdown),
        "minute_sharpe": float(per_min.mean() / per_min.std() * np.sqrt(len(per_min))) if per_min.std() > 0 else np.nan,
        "fills": int(len(f)),
        "shares": int(f["volume"].sum()) if len(f) else 0,
        "avg_abs_position": float(path["position"].abs().mean()),
        "two_sided_uptime": float((path["bid_live"] & path["ask_live"]).mean()),
    }
    if len(f):
        w = f["volume"].to_numpy(float)
        px = f["price"].to_numpy(float)
        capture = f["side"].to_numpy(float) * (f["mid_at_fill"].to_numpy(float) - px) / px * 1e4
        out["spread_capture_bps"] = float(np.average(capture, weights=w))
        out["queue_at_entry_median"] = float(f["queue_at_entry"].median())
        out["resting_seconds_median"] = float(f["resting_seconds"].median())
        mk = markouts(result).set_index("horizon")["markout_bps"]
        for h, v in mk.items():
            out[f"markout_{h}s_bps"] = float(v)
    return out
