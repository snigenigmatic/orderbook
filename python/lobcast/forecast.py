from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

TIMESTRAL_LEVELS = np.array([0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50,
                             0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99])
DEFAULT_TARGETS = ("vol_bps", "spread_ticks")
DEFAULT_COVARIATES = ("ofi_k", "volume_k", "log_return_bps")


class QuantileModel(Protocol):
    name: str
    levels: np.ndarray

    def predict(self, context: np.ndarray, covariates: np.ndarray | None, horizon: int) -> np.ndarray: ...


@dataclass
class ForecastTable:
    name: str
    targets: tuple[str, ...]
    levels: np.ndarray
    bar_index: np.ndarray
    available_time: np.ndarray
    values: np.ndarray
    realized: np.ndarray
    latency_seconds: float
    compute_seconds: float
    extra: dict = field(default_factory=dict)

    def lookup(self, t: float) -> int:
        i = int(np.searchsorted(self.available_time, t, side="right")) - 1
        return i

    def quantile(self, t: float, target: str, level: float) -> float:
        i = self.lookup(t)
        if i < 0:
            return float("nan")
        v = self.targets.index(target)
        q = int(np.argmin(np.abs(self.levels - level)))
        return float(self.values[i, v, q])

    def subset(self, mask: np.ndarray) -> "ForecastTable":
        return ForecastTable(
            name=self.name,
            targets=self.targets,
            levels=self.levels,
            bar_index=self.bar_index[mask],
            available_time=self.available_time[mask],
            values=self.values[mask],
            realized=self.realized[mask],
            latency_seconds=self.latency_seconds,
            compute_seconds=self.compute_seconds,
        )

    def save(self, path: str | Path) -> None:
        np.savez_compressed(
            path,
            name=self.name,
            targets=np.array(self.targets),
            levels=self.levels,
            bar_index=self.bar_index,
            available_time=self.available_time,
            values=self.values,
            realized=self.realized,
            latency_seconds=self.latency_seconds,
            compute_seconds=self.compute_seconds,
        )

    @classmethod
    def load(cls, path: str | Path) -> "ForecastTable":
        z = np.load(path, allow_pickle=False)
        return cls(
            name=str(z["name"]),
            targets=tuple(str(t) for t in z["targets"]),
            levels=z["levels"],
            bar_index=z["bar_index"],
            available_time=z["available_time"],
            values=z["values"],
            realized=z["realized"],
            latency_seconds=float(z["latency_seconds"]),
            compute_seconds=float(z["compute_seconds"]),
        )


class TimestralModel:
    def __init__(self, model_id: str = "mistralai/Timestral-209M", device: str | None = None, threads: int | None = None):
        import torch
        from timestral import TimestralForecaster

        if threads:
            torch.set_num_threads(threads)
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.name = model_id.split("/")[-1]
        self.levels = TIMESTRAL_LEVELS
        self.model = TimestralForecaster.from_pretrained(model_id, device=device)

    def predict(self, context: np.ndarray, covariates: np.ndarray | None, horizon: int) -> np.ndarray:
        forecast = self.model.forecast(
            context.astype(np.float32),
            prediction_length=horizon,
            past_covariates=None if covariates is None else covariates.astype(np.float32),
        )
        return forecast.quantiles.detach().cpu().numpy()


def horizon_mean(series: np.ndarray, horizon: int) -> np.ndarray:
    n = len(series)
    out = np.full(n, np.nan)
    csum = np.concatenate([[0.0], np.cumsum(series)])
    for t in range(n - horizon):
        out[t] = (csum[t + 1 + horizon] - csum[t + 1]) / horizon
    return out


def realized_targets(df: pd.DataFrame, targets: tuple[str, ...], horizon: int) -> np.ndarray:
    out = np.stack([horizon_mean(df[t].to_numpy(float), horizon) for t in targets], axis=1)
    if "day" in df:
        day = df["day"].to_numpy()
        n = len(day)
        ahead = np.concatenate([day[horizon:], np.full(horizon, -1)])
        out[ahead[:n] != day] = np.nan
    return out


def valid_indices(df: pd.DataFrame, min_context: int) -> np.ndarray:
    n = len(df)
    idx = np.arange(min_context - 1, n - 1)
    if "day" in df:
        day = df["day"].to_numpy()
        idx = idx[day[idx + 1] == day[idx]]
    return idx


def walk_forward(
    model: QuantileModel,
    df: pd.DataFrame,
    targets: tuple[str, ...] = DEFAULT_TARGETS,
    covariates: tuple[str, ...] | None = DEFAULT_COVARIATES,
    context_bars: int = 512,
    horizon: int = 6,
    min_context: int = 30,
    batch_size: int = 32,
    latency_seconds: float | None = None,
    progress: bool = False,
    indices: np.ndarray | None = None,
) -> ForecastTable:
    y = df[list(targets)].to_numpy(float).T
    x = df[list(covariates)].to_numpy(float).T if covariates else None
    n = y.shape[1]
    idx = valid_indices(df, min_context) if indices is None else np.asarray(indices)

    out = np.full((len(idx), len(targets), len(model.levels)), np.nan)
    started = time.perf_counter()
    for start in range(0, len(idx), batch_size):
        chunk = idx[start:start + batch_size]
        ctx = np.full((len(chunk), len(targets), context_bars), np.nan)
        cov = None if x is None else np.full((len(chunk), x.shape[0], context_bars), np.nan)
        for j, t in enumerate(chunk):
            lo = max(0, t + 1 - context_bars)
            width = t + 1 - lo
            ctx[j, :, -width:] = y[:, lo:t + 1]
            if cov is not None:
                cov[j, :, -width:] = x[:, lo:t + 1]
        q = model.predict(ctx, cov, horizon)
        out[start:start + len(chunk)] = q.mean(axis=2)
        if progress:
            done = start + len(chunk)
            print(f"\r  {model.name}: {done}/{len(idx)} forecasts", end="", flush=True)
    if progress:
        print()
    compute = time.perf_counter() - started

    if latency_seconds is None:
        latency_seconds = measure_latency(model, y, x, context_bars, horizon)

    end_time = df["end_time"].to_numpy(float)
    return ForecastTable(
        name=model.name,
        targets=tuple(targets),
        levels=np.asarray(model.levels),
        bar_index=idx,
        available_time=end_time[idx] + latency_seconds,
        values=out,
        realized=realized_targets(df, targets, horizon)[idx],
        latency_seconds=latency_seconds,
        compute_seconds=compute,
    )


def measure_latency(model: QuantileModel, y: np.ndarray, x: np.ndarray | None, context_bars: int, horizon: int, runs: int = 5) -> float:
    t = min(y.shape[1] - 1, context_bars)
    ctx = y[None, :, :t]
    cov = None if x is None else x[None, :, :t]
    model.predict(ctx, cov, horizon)
    times = []
    for _ in range(runs):
        s = time.perf_counter()
        model.predict(ctx, cov, horizon)
        times.append(time.perf_counter() - s)
    return float(np.median(times))


def ewma_baseline(
    df: pd.DataFrame,
    targets: tuple[str, ...] = DEFAULT_TARGETS,
    horizon: int = 6,
    min_context: int = 30,
    span: int = 30,
    residual_window: int = 360,
    levels: np.ndarray = TIMESTRAL_LEVELS,
) -> ForecastTable:
    idx = valid_indices(df, min_context)
    realized_all = realized_targets(df, targets, horizon)
    out = np.full((len(idx), len(targets), len(levels)), np.nan)

    for v, name in enumerate(targets):
        series = df[name].to_numpy(float)
        ewma = pd.Series(series).ewm(span=span, adjust=False).mean().to_numpy()
        point = np.maximum(ewma, 1e-9)
        ratio = realized_all[:, v] / point
        for k, t in enumerate(idx):
            known_end = t - horizon
            lo = max(0, known_end - residual_window + 1)
            past = ratio[lo:known_end + 1] if known_end >= 0 else np.array([])
            past = past[np.isfinite(past)]
            if len(past) < 10:
                past = np.array([0.5, 1.0, 1.5])
            out[k, v, :] = point[t] * np.quantile(past, levels)

    end_time = df["end_time"].to_numpy(float)
    return ForecastTable(
        name="EWMA",
        targets=tuple(targets),
        levels=np.asarray(levels),
        bar_index=idx,
        available_time=end_time[idx],
        values=out,
        realized=realized_all[idx],
        latency_seconds=0.0,
        compute_seconds=0.0,
    )


def pinball(values: np.ndarray, realized: np.ndarray, levels: np.ndarray) -> float:
    diff = realized[:, None] - values
    loss = np.maximum(levels * diff, (levels - 1) * diff)
    return float(np.nanmean(loss))


def score(tables: list[ForecastTable], warmup_bars: int = 60) -> pd.DataFrame:
    rows = []
    common = set(tables[0].bar_index.tolist())
    for tb in tables[1:]:
        common &= set(tb.bar_index.tolist())
    for tb in tables:
        keep = np.isin(tb.bar_index, sorted(common)) & (tb.bar_index >= warmup_bars)
        for v, target in enumerate(tb.targets):
            vals = tb.values[keep, v, :]
            real = tb.realized[keep, v]
            ok = np.isfinite(real) & np.all(np.isfinite(vals), axis=1)
            vals, real = vals[ok], real[ok]
            lo = np.argmin(np.abs(tb.levels - 0.1))
            hi = np.argmin(np.abs(tb.levels - 0.9))
            med = np.argmin(np.abs(tb.levels - 0.5))
            rows.append({
                "model": tb.name,
                "target": target,
                "n": int(ok.sum()),
                "pinball": pinball(vals, real, tb.levels),
                "median_mae": float(np.mean(np.abs(vals[:, med] - real))),
                "coverage_80": float(np.mean((real >= vals[:, lo]) & (real <= vals[:, hi]))),
                "band_width_80": float(np.mean(vals[:, hi] - vals[:, lo])),
            })
    return pd.DataFrame(rows)
