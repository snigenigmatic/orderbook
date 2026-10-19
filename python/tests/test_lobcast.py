from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lobcast import Backtester, OrderStatus, Side
from lobcast.bars import make_config, replay_bars
from lobcast.data import LobsterFiles
from lobcast.forecast import TIMESTRAL_LEVELS, ewma_baseline, walk_forward
from lobcast.metrics import summarize
from lobcast.strategy import MarketMaker, MarketMakerParams

LEVELS = 5


def synthetic_day(path: Path, n: int = 6000, seed: int = 7) -> LobsterFiles:
    rng = random.Random(seed)
    books = {1: {}, -1: {}}
    orders = {}
    rows, snaps = [], []
    next_id = 1
    t = 34200.0
    mid = 1_000_000

    def level_volume(direction, px):
        return sum(orders[o][2] for o in books[direction].get(px, []))

    def snapshot():
        row = []
        asks = sorted(p for p in books[-1] if books[-1][p])
        bids = sorted((p for p in books[1] if books[1][p]), reverse=True)
        for k in range(LEVELS):
            a = asks[k] if k < len(asks) else None
            b = bids[k] if k < len(bids) else None
            row += [a if a else 9999999999, level_volume(-1, a) if a else 0,
                    b if b else -9999999999, level_volume(1, b) if b else 0]
        return row

    def add(direction, px, size):
        nonlocal next_id
        oid = next_id
        next_id += 1
        orders[oid] = [direction, px, size]
        books[direction].setdefault(px, []).append(oid)
        return oid

    def remove(oid, size):
        direction, px, live = orders[oid]
        take = min(size, live)
        orders[oid][2] -= take
        if orders[oid][2] == 0:
            books[direction][px].remove(oid)
            if not books[direction][px]:
                del books[direction][px]
            del orders[oid]
        return take

    while len(rows) < n:
        t += rng.expovariate(1 / 3.0)
        best_bid = max((p for p in books[1] if books[1][p]), default=mid - 100)
        best_ask = min((p for p in books[-1] if books[-1][p]), default=mid + 100)
        r = rng.random()
        if r < 0.5 or len(orders) < 20:
            direction = rng.choice([1, -1])
            offset = rng.randint(0, 6) * 100
            px = best_bid - offset if direction == 1 else best_ask + offset
            if direction == 1 and px >= best_ask:
                px = best_ask - 100
            if direction == -1 and px <= best_bid:
                px = best_bid + 100
            size = rng.choice([100, 100, 200, 300, 500])
            oid = add(direction, px, size)
            rows.append((t, 1, oid, size, px, direction))
        elif r < 0.65:
            oid = rng.choice(list(orders))
            direction, px, live = orders[oid]
            if live <= 100:
                continue
            take = remove(oid, 100)
            rows.append((t, 2, oid, take, px, direction))
        elif r < 0.85:
            oid = rng.choice(list(orders))
            direction, px, live = orders[oid]
            remove(oid, live)
            rows.append((t, 3, oid, live, px, direction))
        else:
            direction = rng.choice([1, -1])
            best = best_bid if direction == 1 else best_ask
            queue = books[direction].get(best)
            if not queue:
                continue
            oid = queue[0]
            size = min(orders[oid][2], rng.choice([100, 200]))
            remove(oid, size)
            rows.append((t, 4, oid, size, best, direction))
        snaps.append(snapshot())
        if t > 57000:
            break

    msg = path / "SYN_2012-06-21_34200000_57600000_message_5.csv"
    ob = path / "SYN_2012-06-21_34200000_57600000_orderbook_5.csv"
    pd.DataFrame(rows).to_csv(msg, header=False, index=False, float_format="%.9f")
    pd.DataFrame(snaps).to_csv(ob, header=False, index=False)
    return LobsterFiles("SYN", "2012-06-21", LEVELS, msg, ob)


@pytest.fixture(scope="module")
def day(tmp_path_factory) -> LobsterFiles:
    return synthetic_day(tmp_path_factory.mktemp("lobster"))


def test_cpp_book_matches_independent_reference(day):
    bt = Backtester(str(day.message), str(day.orderbook), make_config())
    bt.run_to_end()
    stats = bt.stats()
    assert stats["messages"] > 1000
    assert stats["unknown_orders"] == 0
    assert stats["reconcile_events"] == 0


def test_bars_cover_session(day):
    bars, stats = replay_bars(day, bar_seconds=10.0)
    assert len(bars) == 2340
    assert np.all(np.diff(bars["end_time"]) == 10.0)
    assert bars["mid"].notna().all()


def test_order_lifecycle_through_bindings(day):
    bt = Backtester(str(day.message), str(day.orderbook), make_config())
    bt.run_until(35000.0)
    bid = bt.best_bid()
    oid = bt.submit(Side.Bid, bid, 100)
    assert bt.order(oid).status == OrderStatus.Pending
    bt.run_until(35000.01)
    assert bt.order(oid).status in (OrderStatus.Active, OrderStatus.Filled)
    assert bt.order(oid).queue_at_entry >= 0
    bt.cancel(oid)
    bt.run_until(35001.0)
    assert bt.order(oid).status in (OrderStatus.Cancelled, OrderStatus.Filled)
    assert not any(o.id == oid for o in bt.open_orders())


class EchoModel:
    name = "echo"
    levels = TIMESTRAL_LEVELS

    def predict(self, context, covariates, horizon):
        last = np.nanmean(context[:, :, -3:], axis=2)
        spread = np.linspace(0.5, 1.5, len(self.levels))
        return last[:, :, None, None] * spread[None, None, None, :] * np.ones((1, 1, horizon, 1))


def test_walk_forward_has_no_lookahead(day):
    bars, _ = replay_bars(day)
    base = walk_forward(EchoModel(), bars, horizon=1, latency_seconds=0.2)

    cut = 1000
    poisoned = bars.copy()
    poisoned.loc[cut + 1:, ["vol_bps", "spread_ticks", "ofi_k", "volume_k", "log_return_bps"]] *= 50.0
    again = walk_forward(EchoModel(), poisoned, horizon=1, latency_seconds=0.2)

    upto = base.bar_index <= cut
    np.testing.assert_allclose(base.values[upto], again.values[upto])
    assert np.all(base.available_time >= bars["end_time"].to_numpy()[base.bar_index] + 0.2)


def test_ewma_baseline_has_no_lookahead(day):
    bars, _ = replay_bars(day)
    base = ewma_baseline(bars, horizon=1)
    cut = 1200
    poisoned = bars.copy()
    poisoned.loc[cut + 1:, ["vol_bps", "spread_ticks"]] *= 50.0
    again = ewma_baseline(poisoned, horizon=1)
    upto = base.bar_index <= cut
    np.testing.assert_allclose(base.values[upto], again.values[upto])


def test_market_maker_runs_and_respects_limits(day):
    bars, _ = replay_bars(day)
    params = MarketMakerParams(quote_size=100, max_position=300)
    result = MarketMaker("ewma", params, ewma_baseline(bars, horizon=1)).run(day, bars)
    assert result.path["position"].abs().max() <= 300
    summary = summarize(result)
    assert summary["fills"] >= 0
    assert np.isfinite(summary["pnl_usd"])
