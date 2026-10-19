from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ._core import Backtester, BacktestConfig

DATASET = "XNAS.ITCH"
SCHEMA = "mbo"
SESSION_TZ = "America/New_York"
PRICE_DIVISOR = 100_000

EV_SUBMIT = 1
EV_CANCEL = 2
EV_HIDDEN = 5
EV_FILL = 8
EV_CLEAR = 9
EV_MODIFY = 10


@dataclass(frozen=True)
class DatabentoDay:
    ticker: str
    date: str
    path: Path
    kind: str = "databento"

    def make_backtester(self, config: BacktestConfig) -> Backtester:
        ev = load_mbo_events(self.path, self.date)
        return Backtester.from_events(ev["time"], ev["type"], ev["order_id"], ev["size"], ev["price"], ev["direction"], config)


def day_file(dest: str | Path, ticker: str, date: str, synthetic: bool = False) -> Path:
    tag = ".synthetic" if synthetic else ""
    return Path(dest) / f"{ticker}_{date}{tag}.mbo.dbn.zst"


def _read(path: str | Path) -> np.ndarray:
    import databento as db

    store = db.DBNStore.from_file(path)
    arr = store.to_ndarray()
    arr = arr[arr["rtype"] == 160]
    ids = np.unique(arr["instrument_id"])
    if len(ids) > 1:
        raise ValueError(f"{path} holds {len(ids)} instruments; fetch one symbol per file")
    return arr


def mbo_to_events(arr: np.ndarray, date: str) -> dict[str, np.ndarray]:
    action = arr["action"].astype("U1")
    side = arr["side"].astype("U1")

    midnight = pd.Timestamp(date, tz=SESSION_TZ).value
    t = (arr["ts_event"].astype(np.int64) - midnight) / 1e9
    t = np.maximum.accumulate(t)

    direction = np.where(side == "B", 1, np.where(side == "A", -1, 0)).astype(np.int8)
    price = arr["price"].astype(np.int64)
    price = np.where(price == np.iinfo(np.int64).max, 0, price // PRICE_DIVISOR)

    group = arr["ts_event"]
    has_fill = pd.Series(action == "F").groupby(group).transform("any").to_numpy()
    hidden = (action == "T") & ~has_fill & (direction != 0)

    etype = np.zeros(len(arr), dtype=np.int8)
    etype[action == "A"] = EV_SUBMIT
    etype[action == "C"] = EV_CANCEL
    etype[action == "M"] = EV_MODIFY
    etype[action == "R"] = EV_CLEAR
    etype[action == "F"] = EV_FILL
    etype[hidden] = EV_HIDDEN
    direction = np.where(hidden, -direction, direction).astype(np.int8)

    keep = etype != 0
    return {
        "time": np.ascontiguousarray(t[keep], dtype=np.float64),
        "type": np.ascontiguousarray(etype[keep]),
        "order_id": np.ascontiguousarray(arr["order_id"][keep], dtype=np.uint64),
        "size": np.ascontiguousarray(arr["size"][keep], dtype=np.int64),
        "price": np.ascontiguousarray(price[keep], dtype=np.int64),
        "direction": np.ascontiguousarray(direction[keep]),
    }


def load_mbo_events(path: str | Path, date: str) -> dict[str, np.ndarray]:
    return mbo_to_events(_read(path), date)


def trading_days(start: str, end: str) -> list[str]:
    days = pd.bdate_range(start, end)
    return [d.strftime("%Y-%m-%d") for d in days]


def _client(key: str | None):
    import databento as db

    key = key or os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("set DATABENTO_API_KEY or pass --key")
    return db.Historical(key)


def estimate_cost(symbols: list[str], start: str, end: str, key: str | None = None) -> pd.DataFrame:
    client = _client(key)
    rows = []
    for sym in symbols:
        end_excl = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
        cost = client.metadata.get_cost(dataset=DATASET, symbols=[sym], schema=SCHEMA, start=start, end=end_excl)
        size = client.metadata.get_billable_size(dataset=DATASET, symbols=[sym], schema=SCHEMA, start=start, end=end_excl)
        rows.append({"symbol": sym, "start": start, "end": end, "cost_usd": float(cost), "gigabytes": size / 1e9})
    return pd.DataFrame(rows)


def fetch_days(symbols: list[str], start: str, end: str, dest: str | Path, key: str | None = None, max_cost: float | None = None) -> list[DatabentoDay]:
    client = _client(key)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if max_cost is not None:
        total = float(estimate_cost(symbols, start, end, key)["cost_usd"].sum())
        if total > max_cost:
            raise RuntimeError(f"estimated cost ${total:,.2f} is above --max-cost ${max_cost:,.2f}")

    out = []
    for sym in symbols:
        for date in trading_days(start, end):
            target = day_file(dest, sym, date)
            if target.exists() and target.stat().st_size > 0:
                out.append(DatabentoDay(sym, date, target))
                continue
            nxt = (dt.date.fromisoformat(date) + dt.timedelta(days=1)).isoformat()
            tmp = target.with_name(target.name + ".part")
            client.timeseries.get_range(dataset=DATASET, schema=SCHEMA, symbols=[sym], start=date, end=nxt, path=tmp)
            if tmp.stat().st_size == 0 or len(_read(tmp)) == 0:
                tmp.unlink(missing_ok=True)
                continue
            tmp.rename(target)
            out.append(DatabentoDay(sym, date, target))
            print(f"  {sym} {date}: {target.stat().st_size / 1e6:.1f} MB")
    return out
