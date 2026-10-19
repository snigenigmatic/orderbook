from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

CI_LEVEL = 0.95


def bootstrap_mean_ci(x, n_boot: int = 10_000, level: float = CI_LEVEL, seed: int = 0) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return np.nan, np.nan, np.nan
    mean = float(x.mean())
    if len(x) < 2:
        return mean, np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    alpha = (1 - level) / 2
    return mean, float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))


def sign_flip_pvalue(d, n_perm: int = 20_000, seed: int = 0) -> float:
    d = np.asarray(d, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return np.nan
    observed = abs(d.mean())
    if len(d) <= 16:
        signs = np.array(list(itertools.product((-1, 1), repeat=len(d))))
    else:
        signs = np.random.default_rng(seed).choice((-1, 1), size=(n_perm, len(d)))
    flipped = np.abs((signs * d).mean(axis=1))
    return float(np.mean(flipped >= observed - 1e-12))


def aggregate_days(days: pd.DataFrame, by: tuple[str, ...] = ("ticker", "strategy")) -> pd.DataFrame:
    rows = []
    for key, g in days.groupby(list(by), sort=False):
        mean, lo, hi = bootstrap_mean_ci(g["pnl_usd"])
        pnl = g["pnl_usd"].to_numpy(float)
        rows.append({
            **dict(zip(by, key if isinstance(key, tuple) else (key,))),
            "days": len(g),
            "mean_daily_pnl": mean,
            "ci_low": lo,
            "ci_high": hi,
            "total_pnl": float(pnl.sum()),
            "daily_std": float(pnl.std(ddof=1)) if len(pnl) > 1 else np.nan,
            "daily_t_stat": float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl))) if len(pnl) > 1 and pnl.std(ddof=1) > 0 else np.nan,
            "win_rate": float(np.mean(pnl > 0)),
            "mean_drawdown": float(g["max_drawdown_usd"].mean()),
            "mean_uptime": float(g["two_sided_uptime"].mean()),
        })
    return pd.DataFrame(rows)


PAIRED_METRICS = (
    ("pnl_usd", "Daily PnL (USD)"),
    ("max_drawdown_usd", "Max drawdown (USD)"),
    ("two_sided_uptime", "Two-sided uptime"),
    ("minute_sharpe", "Minute Sharpe"),
)


def paired_compare(days: pd.DataFrame, a: str, b: str, metrics=PAIRED_METRICS) -> pd.DataFrame:
    rows = []
    groups = [("All", days)] + [(t, g) for t, g in days.groupby("ticker", sort=False)] if days["ticker"].nunique() > 1 else [(days["ticker"].iloc[0], days)]
    for ticker, g in groups:
        wide = g.pivot_table(index=["ticker", "date"], columns="strategy", values=[m for m, _ in metrics])
        for metric, label in metrics:
            if (metric, a) not in wide or (metric, b) not in wide:
                continue
            d = (wide[(metric, a)] - wide[(metric, b)]).dropna().to_numpy(float)
            mean, lo, hi = bootstrap_mean_ci(d)
            rows.append({
                "ticker": ticker,
                "metric": label,
                "days": len(d),
                "mean_diff": mean,
                "ci_low": lo,
                "ci_high": hi,
                "a_better_days": float(np.mean(d > 0)) if len(d) else np.nan,
                "p_value": sign_flip_pvalue(d),
            })
    return pd.DataFrame(rows)


def paired_skill(day_skill: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    rows = []
    for (ticker, target), g in day_skill.groupby(["ticker", "target"], sort=False):
        wide = g.pivot_table(index="date", columns="model", values="pinball")
        if a not in wide or b not in wide:
            continue
        d = ((wide[b] - wide[a]) / wide[b]).dropna().to_numpy(float)
        mean, lo, hi = bootstrap_mean_ci(d)
        rows.append({
            "ticker": ticker,
            "target": target,
            "days": len(d),
            "pinball_reduction": mean,
            "ci_low": lo,
            "ci_high": hi,
            "a_better_days": float(np.mean(d > 0)) if len(d) else np.nan,
            "p_value": sign_flip_pvalue(d),
        })
    return pd.DataFrame(rows)
