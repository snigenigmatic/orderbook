from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lobcast import Side
from lobcast.bars import make_config, replay_bars
from lobcast.cli import main
from lobcast.data import discover_days
from lobcast.databento_data import EV_FILL, EV_HIDDEN, load_mbo_events
from lobcast.forecast import TIMESTRAL_LEVELS, ewma_baseline, realized_targets, valid_indices, walk_forward
from lobcast.multiday import combine, run_ticker, split
from lobcast.stats import aggregate_days, bootstrap_mean_ci, paired_compare, sign_flip_pvalue
from lobcast.strategy import MarketMakerParams
from lobcast.synthetic import synthetic_days, synthetic_mbo_day


@pytest.fixture(scope="module")
def mbo_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("mbo")
    synthetic_days(d, "SYN", "2024-03-04", 3, seed=11, session_events=8000)
    return d


def test_databento_replay_matches_reference_book(tmp_path):
    day, ref = synthetic_mbo_day(tmp_path, "SYN", "2024-03-12", seed=5, session_events=8000)
    config = make_config()
    config.reconcile = False
    bt = day.make_backtester(config)
    bt.run_to_end()
    assert bt.stats()["unknown_orders"] == 0
    for side, enum in (("B", Side.Bid), ("A", Side.Ask)):
        expected = [(p // 100_000, v) for p, v in ref.depth(side).items()]
        assert bt.depth(enum, 10_000) == expected


def test_databento_events_are_ordered_and_classified(tmp_path):
    day, _ = synthetic_mbo_day(tmp_path, "SYN", "2024-03-12", seed=6, session_events=8000)
    ev = load_mbo_events(day.path, day.date)
    assert np.all(np.diff(ev["time"]) >= 0)
    assert ev["time"][0] < 0
    assert (ev["type"] == EV_FILL).sum() > 0
    assert (ev["type"] == EV_HIDDEN).sum() > 0
    assert set(np.unique(ev["direction"][ev["type"] == EV_HIDDEN])) <= {-1, 1}


def test_discover_days_finds_sorted_synthetic_files(mbo_dir):
    days = discover_days(mbo_dir, "SYN")
    assert [d.date for d in days] == ["2024-03-04", "2024-03-05", "2024-03-06"]
    assert all(d.kind == "synthetic" for d in days)


def frame_of(mbo_dir):
    from lobcast.multiday import DayOutcome

    outcomes = []
    for src in discover_days(mbo_dir, "SYN"):
        bars, stats = replay_bars(src)
        outcomes.append(DayOutcome(src, bars, stats))
    return outcomes


class EchoModel:
    name = "echo"
    levels = TIMESTRAL_LEVELS

    def predict(self, context, covariates, horizon):
        last = np.nanmean(context[:, :, -3:], axis=2)
        spread = np.linspace(0.5, 1.5, len(self.levels))
        return last[:, :, None, None] * spread[None, None, None, :] * np.ones((1, 1, horizon, 1))


def test_forecasts_never_target_the_next_day(mbo_dir):
    days = frame_of(mbo_dir)
    frame, offsets = combine(days)
    idx = valid_indices(frame, 30)
    day = frame["day"].to_numpy()
    assert np.all(day[idx + 1] == day[idx])
    real = realized_targets(frame, ("vol_bps",), 1)
    last_bars = offsets[1:] - 1
    assert np.all(np.isnan(real[last_bars, 0]))


def test_cross_day_context_has_no_lookahead(mbo_dir):
    days = frame_of(mbo_dir)
    frame, offsets = combine(days)
    base = walk_forward(EchoModel(), frame, horizon=1, latency_seconds=0.1)
    poisoned = frame.copy()
    cut = offsets[2]
    poisoned.loc[cut:, ["vol_bps", "spread_ticks", "ofi_k", "volume_k", "log_return_bps"]] *= 40.0
    again = walk_forward(EchoModel(), poisoned, horizon=1, latency_seconds=0.1)
    before = base.bar_index < cut
    np.testing.assert_allclose(base.values[before], again.values[before])

    per_day = split(base, frame, offsets, days)
    assert sorted(per_day) == [d.date for d in days]
    for d in days:
        t = per_day[d.date]
        assert np.all(np.diff(t.available_time) > 0)
        assert t.bar_index.max() < len(d.bars)


def test_ewma_split_matches_single_day_for_first_day(mbo_dir):
    days = frame_of(mbo_dir)
    frame, offsets = combine(days)
    multi = split(ewma_baseline(frame, horizon=1), frame, offsets, days)[days[0].date]
    single = ewma_baseline(days[0].bars, horizon=1)
    n = min(len(single.bar_index), len(multi.bar_index))
    np.testing.assert_allclose(multi.values[:n], single.values[:n])


def test_run_ticker_and_paired_stats(mbo_dir):
    sources = discover_days(mbo_dir, "SYN")
    days = run_ticker(sources, MarketMakerParams(), model_id=None)
    summaries = pd.concat([d.summaries for d in days], ignore_index=True)
    assert set(summaries["strategy"]) == {"touch", "ewma"}
    agg = aggregate_days(summaries)
    assert set(agg["days"]) == {3}
    assert (agg["ci_low"] <= agg["mean_daily_pnl"]).all() and (agg["mean_daily_pnl"] <= agg["ci_high"]).all()
    paired = paired_compare(summaries, "ewma", "touch")
    assert len(paired) == 4 and (paired["days"] == 3).all()


def test_stats_edge_cases():
    m, lo, hi = bootstrap_mean_ci([5.0])
    assert m == 5.0 and np.isnan(lo) and np.isnan(hi)
    assert sign_flip_pvalue([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) == pytest.approx(2 / 64)


def test_cli_multi_day_report(mbo_dir, tmp_path):
    out = tmp_path / "r.html"
    main(["run", "--tickers", "SYN", "--data", str(mbo_dir), "--out", str(out), "--cache", str(tmp_path / "c"), "--no-model"])
    text = out.read_text()
    assert "Across days" in text and "Synthetic data" in text
    assert (tmp_path / "r_aggregate.csv").exists()
