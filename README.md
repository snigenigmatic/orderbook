# Low Latency Order Book + lobcast

A C++ project implementing a low-latency order book, now extended into an end-to-end market analyser and backtester. Inspiration for the book from the CPPCon 2024 talk ['When Nanoseconds Matter'](https://youtu.be/sX2nF1fW7kI?si=DKKSbIE9MrRW_i24) by [David Gross](https://david-grs.github.io/about/).

The original map and vector books are still here and still benchmarked. On top of them sits **lobcast**:

- a FIFO, order-by-order book that tracks where *your* order sits in the queue,
- a replay engine for real NASDAQ L3 data ([LOBSTER](https://lobsterdata.com/)) that checks itself against LOBSTER's own snapshots after every message,
- a fill simulator with order latency, queue position, trade-throughs and hidden-order priority,
- walk-forward volatility and spread forecasts from [Timestral-209M](https://huggingface.co/mistralai/Timestral-209M), Mistral's time series foundation model,
- a market maker that uses the forecast quantiles to size its quotes and to step away before volatile bars,
- an HTML report comparing it against a naive quoter and an EWMA baseline.

```mermaid
flowchart LR
    A[LOBSTER L3 messages] --> B[FifoOrderBook<br/>C++]
    S[LOBSTER snapshots] -. reconcile .-> B
    B --> C[Bars: vol, spread,<br/>OFI, volume]
    C --> D[Timestral-209M<br/>quantile forecasts]
    D --> E[Market maker<br/>Python]
    B --> F[Fill simulator<br/>queue + latency, C++]
    E -- submit / cancel --> F
    F -- fills --> E
    E --> G[HTML report]
```

The split is deliberate. The book and fill simulator run per message in C++ at roughly a microsecond each. The model runs on 10 second bars, off the hot path, and its forecasts only become usable after its measured inference latency.

## Quick start

```bash
pip install ".[timestral]"
lobcast fetch --tickers AAPL MSFT --data data
lobcast run --tickers AAPL MSFT --data data --out out/report.html
```

`lobcast run --no-model` skips Timestral and runs the baselines only. Forecasts are cached in `out/cache`, so reruns take seconds.

The C++ side builds exactly as before:

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build --output-on-failure
./build/bench_lobster data/AAPL_2012-06-21_34200000_57600000_message_10.csv data/AAPL_2012-06-21_34200000_57600000_orderbook_10.csv
```

## How the fill simulator decides you got filled

Your order joins the back of the real queue at its price, after the order latency (1 ms by default). From then on:

| Event in the data | What happens to your order |
| :--- | :--- |
| Cancel of an order ahead of you | You move up the queue |
| Execution of an order that arrived **after** you | You would have been hit first, so you fill |
| Execution at a worse price than yours | The aggressor went through you, so you fill |
| Hidden order executes at your price | Displayed orders have priority on NASDAQ, so you fill |
| New order arrives that crosses your quote | It would have traded with you, so you fill |
| Your order would cross on arrival | Rejected (post-only) |

Because LOBSTER gives order IDs, "ahead of you" is exact, not estimated. That is the main reason this uses L3 data rather than L2 snapshots.

The main thing this does **not** model is market impact: your fills do not remove the liquidity they hit, and nobody reacts to your quotes.

## Replay fidelity

The 10-level LOBSTER files leave out messages for orders deeper than level 10, and orders resting before 9:30 have no add message. So the replay compares itself against LOBSTER's snapshot after every message and patches any difference, putting unexplained volume at the front of the queue (the conservative choice for your fills). Results on 21 June 2012:

| | AAPL | MSFT |
| :--- | ---: | ---: |
| Messages | 400,391 | 668,765 |
| Top of book needed a correction | 57 messages (0.01%) | 1,116 messages (0.17%) |
| Any level needed a correction | 3.9% | 0.75% |
| Replay with reconciliation | ~0.6 s | ~0.75 s |

Almost all of the remaining corrections are at level 10, which is exactly where the missing deep-book messages show up.

## Results

One trading day per ticker (21 June 2012), 100-share quotes, max inventory 500, 1 ms order latency, quoting 9:35 to 15:55. Three strategies share identical quoting code and differ only in the volatility forecast they read:

- **touch**: always quote at the best bid and ask, skewed by inventory. No forecast.
- **ewma**: widen quotes to the forecast 90th percentile of next-bar volatility, and pull quotes when that forecast is extreme. Forecast from an EWMA with empirical residual quantiles.
- **timestral**: the same rules, with the forecast from Timestral-209M.

| | AAPL touch | AAPL ewma | AAPL timestral | MSFT touch | MSFT ewma | MSFT timestral |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| PnL incl. rebates | -$3,820 | $821 | **$844** | -$68 | **$70** | $64 |
| Max drawdown | -$3,860 | -$215 | **-$162** | -$79 | -$46 | **-$30** |
| Minute Sharpe | -4.8 | 2.0 | **2.2** | -2.6 | **1.8** | 1.6 |
| Two-sided uptime | 99.6% | 95.3% | 98.7% | 100% | 78.6% | 99.2% |
| Markout at 10s (bps) | -0.38 | +0.06 | **+0.12** | -0.83 | **-0.16** | -0.29 |

Forecast skill on the next 10-second bar, walk-forward, 2,279 bars per ticker (lower pinball loss is better):

| | AAPL vol | AAPL spread | MSFT vol | MSFT spread |
| :--- | ---: | ---: | ---: | ---: |
| Timestral pinball loss | **0.282** | **0.913** | **0.368** | **0.0038** |
| EWMA pinball loss | 0.285 | 0.983 | 0.389 | 0.0068 |
| Timestral 80% band coverage | 81.0% | 80.8% | 87.2% | 85.0% |
| EWMA 80% band coverage | 79.5% | 79.3% | 88.0% | 77.8% |

What this says, plainly:

1. **Quoting at the touch loses money on both names.** Negative markouts at every horizon: you get filled right before the price moves against you. That is adverse selection, and the queue-aware fill model is what makes it visible.
2. **Volatility-aware quoting turns that around.** Both forecast-driven strategies are profitable on both names.
3. **Timestral forecasts better than EWMA on every target**, by 1 to 5% on volatility and 7 to 44% on spread. Neither model is clearly better calibrated.
4. **In the strategy, Timestral's edge shows up as risk, not PnL.** It has a lower drawdown on both names and stays two-sided far more often on MSFT (99% vs 79%), while PnL is a wash. One day per ticker is nowhere near enough to call this a durable edge.

## Layout

- `include/orderbook/`, `src/`: the original books plus `fifo_book`, `lobster` (fast CSV loader) and `backtest` (replay, fills, bars).
- `src/bench_lobster.cpp`: replays a real day and prints per-message latency.
- `python/bindings.cpp`: nanobind module `lobcast._core`.
- `python/lobcast/`: data fetch, bars, forecasting, strategy, metrics, report, CLI.
- `tests/`: GoogleTest suite. `python/tests/`: pytest suite, including a check that the C++ book matches an independent Python book on a random L3 stream, and lookahead tests that poison future bars and confirm past forecasts do not move.

## Original book benchmarks

> **Note on Normalization:**
> *   **x64 (Ryzen 8945HS):** Measured in CPU cycles. Converted using estimated ~5.0 GHz (Divide by 5).
> *   **ARM (Apple M2):** Measured in 24 MHz timer ticks. Converted using 41.67 ns per tick (Multiply by 41.67).

### x64 (Ryzen 8945HS)

| Metric | Map (Cycles) | Map (ns) | Vector (Cycles) | Vector (ns) |
| :--- | :--- | :--- | :--- | :--- |
| **p50** | 560 | **112** | 600 | **120** |
| **p90** | 1800 | **360** | 2000 | **400** |
| **p99** | 3440 | **688** | 3520 | **704** |
| **p99.9**| 5440 | **1088** | 5640 | **1128** |

### ARM (Apple M2)

| Metric | Map (Ticks) | Map (ns) | Vector (Ticks) | Vector (ns) |
| :--- | :--- | :--- | :--- | :--- |
| **p50** | 42 | **1,750** | 42 | **1,750** |
| **p90** | 84 | **3,500** | 125 | **5,209** |
| **p99** | 167 | **6,959** | 375 | **15,626** |
| **p99.9**| 1167 | **48,629** | 625 | **26,044** |

### Gradle

```bash
./gradlew assemble
./gradlew :lib:test
./gradlew build
```

## Data

The LOBSTER sample files are free for research and teaching. `lobcast fetch` pulls them from a public Hugging Face mirror since lobsterdata.com now gates them behind a request form. Timestral is released under Mistral's modified MIT license.
