from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .databento_data import SESSION_TZ, DatabentoDay, day_file

PRICE_SCALE_1E9 = 1_000_000_000
TICK_1E9 = 10_000_000
F_LAST = 128
F_SNAPSHOT = 32
SIDE_NAMES = {"B": "BID", "A": "ASK"}


@dataclass
class RefBook:
    orders: dict = field(default_factory=dict)
    levels: dict = field(default_factory=lambda: {"B": {}, "A": {}})

    def add(self, oid, side, px, size):
        self.orders[oid] = [side, px, size]
        self.levels[side].setdefault(px, []).append(oid)

    def reduce(self, oid, size):
        side, px, live = self.orders[oid]
        take = min(size, live)
        self.orders[oid][2] -= take
        if self.orders[oid][2] == 0:
            self.levels[side][px].remove(oid)
            if not self.levels[side][px]:
                del self.levels[side][px]
            del self.orders[oid]
        return take

    def best(self, side):
        prices = [p for p, q in self.levels[side].items() if q]
        if not prices:
            return None
        return max(prices) if side == "B" else min(prices)

    def depth(self, side):
        out = {}
        for px, ids in self.levels[side].items():
            out[px] = sum(self.orders[i][2] for i in ids)
        return dict(sorted(out.items(), reverse=(side == "B")))

    def clear(self):
        self.orders.clear()
        self.levels = {"B": {}, "A": {}}


def synthetic_mbo_day(
    dest: str | Path,
    ticker: str,
    date: str,
    seed: int,
    session_events: int = 30_000,
    start_price: float = 100.0,
    vol_scale: float | None = None,
) -> tuple[DatabentoDay, RefBook]:
    import databento_dbn as dbn

    rng = random.Random(seed)
    vol_scale = vol_scale if vol_scale is not None else rng.uniform(0.6, 1.8)
    midnight_local = pd.Timestamp(date, tz=SESSION_TZ)
    day_start_utc = pd.Timestamp(date, tz="UTC")
    book = RefBook()
    records = []
    seq = 0
    next_id = 1_000_000 + seed * 10_000_000

    def ts(sec_local: float) -> int:
        return int(midnight_local.value + sec_local * 1e9)

    def emit(t_ns, action, side, oid, px, size, flags=F_LAST):
        nonlocal seq
        seq += 1
        records.append(dbn.MBOMsg(
            publisher_id=2, instrument_id=1, ts_event=t_ns, order_id=oid, price=px, size=size,
            action=getattr(dbn.Action, action), side=getattr(dbn.Side, SIDE_NAMES.get(side, side)), ts_recv=t_ns + 500,
            flags=flags, sequence=seq,
        ))

    def new_id():
        nonlocal next_id
        next_id += 1
        return next_id

    mid = int(round(start_price * PRICE_SCALE_1E9 / TICK_1E9)) * TICK_1E9
    snap_ns = day_start_utc.value
    emit(snap_ns, "CLEAR", "NONE", 0, 2**63 - 1, 0, F_SNAPSHOT)
    for k in range(30):
        side = "B" if k % 2 == 0 else "A"
        px = mid - TICK_1E9 * (1 + k // 2) if side == "B" else mid + TICK_1E9 * (1 + k // 2)
        oid = new_id()
        size = rng.choice([100, 200, 300, 500])
        book.add(oid, side, px, size)
        emit(snap_ns, "ADD", side, oid, px, size, F_SNAPSHOT | (F_LAST if k == 29 else 0))

    def step(t_sec: float, intensity: float):
        bb, ba = book.best("B"), book.best("A")
        if bb is None or ba is None:
            side = "B" if bb is None else "A"
            ref = (ba - TICK_1E9) if side == "B" else (bb + TICK_1E9)
            if ref is None or (bb is None and ba is None):
                ref = mid
            oid = new_id()
            book.add(oid, side, ref, 100)
            emit(ts(t_sec), "ADD", side, oid, ref, 100)
            return
        r = rng.random()
        t_ns = ts(t_sec)
        if r < 0.44 or len(book.orders) < 30:
            side = rng.choice("BA")
            offset = int(abs(rng.gauss(0, 2.5 * intensity)))
            improve = 0.6 if ba - bb > TICK_1E9 else 0.05
            if side == "B":
                px = min(bb + TICK_1E9 if rng.random() < improve else bb - offset * TICK_1E9, ba - TICK_1E9)
            else:
                px = max(ba - TICK_1E9 if rng.random() < improve else ba + offset * TICK_1E9, bb + TICK_1E9)
            oid = new_id()
            size = rng.choice([100, 100, 100, 200, 300, 500, 1000])
            book.add(oid, side, px, size)
            emit(t_ns, "ADD", side, oid, px, size)
        elif r < 0.66:
            oid = rng.choice(list(book.orders))
            side, px, live = book.orders[oid]
            book.reduce(oid, live)
            emit(t_ns, "CANCEL", side, oid, px, live)
        elif r < 0.72:
            oid = rng.choice(list(book.orders))
            side, px, live = book.orders[oid]
            if live <= 100:
                return
            book.reduce(oid, 100)
            emit(t_ns, "CANCEL", side, oid, px, 100)
        elif r < 0.79:
            oid = rng.choice(list(book.orders))
            side, px, live = book.orders[oid]
            kind = rng.random()
            if kind < 0.5 and live > 100:
                new_size, new_px = live - 100, px
                book.orders[oid][2] = new_size
            else:
                if kind < 0.75:
                    new_size, new_px = live + 100, px
                else:
                    new_size = live
                    new_px = px - TICK_1E9 if side == "B" else px + TICK_1E9
                book.reduce(oid, live)
                book.add(oid, side, new_px, new_size)
            emit(t_ns, "MODIFY", side, oid, new_px, new_size)
        elif r < 0.95:
            aggressor = rng.choice("BA")
            resting = "A" if aggressor == "B" else "B"
            want = int(rng.choice([100, 200, 300, 500, 800, 1500]) * intensity * rng.uniform(0.5, 3.0))
            first = book.best(resting)
            fills = []
            while want > 0 and book.best(resting) is not None and abs(book.best(resting) - first) <= 2 * TICK_1E9 and len(book.orders) > 12:
                price = book.best(resting)
                oid = book.levels[resting][price][0]
                take = min(want, book.orders[oid][2])
                fills.append((oid, price, take))
                want -= take
                book.reduce(oid, take)
            if not fills:
                return
            emit(t_ns, "TRADE", "ASK" if aggressor == "A" else "BID", 0, fills[0][1], sum(f[2] for f in fills), 0)
            for i, (oid, px, take) in enumerate(fills):
                emit(t_ns, "FILL", "ASK" if resting == "A" else "BID", oid, px, take, 0)
                emit(t_ns, "CANCEL", "ASK" if resting == "A" else "BID", oid, px, take, F_LAST if i == len(fills) - 1 else 0)
        else:
            aggressor = rng.choice("BA")
            px = book.best("A" if aggressor == "B" else "B")
            emit(t_ns, "TRADE", "ASK" if aggressor == "A" else "BID", 0, px, rng.choice([100, 200]))

    t = 4 * 3600.0
    while t < 9.5 * 3600:
        t += rng.expovariate(1 / 20.0)
        step(min(t, 9.5 * 3600 - 0.001), 0.5)

    session = 6.5 * 3600
    base_gap = session / session_events
    t = 9.5 * 3600
    while t < 16 * 3600:
        frac = (t - 9.5 * 3600) / session
        intraday = 1.6 - 1.2 * frac + 1.4 * frac * frac
        intensity = vol_scale * intraday
        t += rng.expovariate(1 / (base_gap / intraday))
        if t >= 16 * 3600:
            break
        step(t, intensity)

    target = day_file(dest, ticker, date, synthetic=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    meta = dbn.Metadata(dataset="XNAS.ITCH", start=snap_ns, stype_in=dbn.SType.RAW_SYMBOL,
                        stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.MBO, symbols=[ticker])
    payload = bytearray(meta.encode())
    for rec in records:
        payload += bytes(rec)
    import zstandard

    target.write_bytes(zstandard.ZstdCompressor().compress(bytes(payload)))
    return DatabentoDay(ticker, date, target, kind="synthetic"), book


def synthetic_days(dest: str | Path, ticker: str, start: str, days: int, seed: int = 1, session_events: int = 30_000) -> list[DatabentoDay]:
    out = []
    price = 100.0
    for i, d in enumerate(pd.bdate_range(start, periods=days)):
        day, book = synthetic_mbo_day(dest, ticker, d.strftime("%Y-%m-%d"), seed + i, session_events, start_price=price)
        bb, ba = book.best("B"), book.best("A")
        if bb and ba:
            price = (bb + ba) / 2 / PRICE_SCALE_1E9
        out.append(day)
    return out
