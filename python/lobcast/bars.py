from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ._core import Backtester, BacktestConfig
from .data import TICK, LobsterFiles


def make_config(bar_seconds: float = 10.0, order_latency: float = 0.001, maker_rebate: int = 20) -> BacktestConfig:
    config = BacktestConfig()
    config.bar_seconds = bar_seconds
    config.order_latency = order_latency
    config.maker_rebate = maker_rebate
    config.reconcile = True
    return config


def replay_bars(files: LobsterFiles, bar_seconds: float = 10.0) -> tuple[pd.DataFrame, dict]:
    bt = files.make_backtester(make_config(bar_seconds))
    start = time.perf_counter()
    bt.run_to_end()
    elapsed = time.perf_counter() - start

    raw = {k: np.asarray(v, dtype=float) for k, v in bt.bars().items()}
    df = pd.DataFrame(raw)
    df["mid"] = df["mid"].ffill().bfill()
    df["spread_ticks"] = df["spread"] / TICK
    df["vol_bps"] = np.sqrt(df["realized_var"]) * 1e4
    df["log_return_bps"] = np.log(df["mid"]).diff().fillna(0.0) * 1e4
    df["ofi_k"] = df["ofi"] / 1e3
    df["volume_k"] = df["volume"] / 1e3

    stats = dict(bt.stats())
    stats["replay_seconds"] = elapsed
    stats["messages_per_second"] = stats["messages"] / max(elapsed, 1e-9)
    return df, stats
