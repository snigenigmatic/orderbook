from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

HF_MIRROR = "https://huggingface.co/datasets/totalorganfailure/lobster-data/resolve/main"
SAMPLE_DATE = "2012-06-21"
SAMPLE_TICKERS = ("AAPL", "AMZN", "GOOG", "INTC", "MSFT")
TICK = 100
PRICE_SCALE = 10_000


@dataclass(frozen=True)
class LobsterFiles:
    ticker: str
    date: str
    levels: int
    message: Path
    orderbook: Path


def sample_name(ticker: str, kind: str, levels: int) -> str:
    return f"{ticker}_{SAMPLE_DATE}_34200000_57600000_{kind}_{levels}.csv"


def find_lobster_files(data_dir: str | Path, ticker: str, levels: int = 10) -> LobsterFiles:
    data_dir = Path(data_dir)
    messages = sorted(data_dir.glob(f"{ticker}_*_message_{levels}.csv"))
    if not messages:
        raise FileNotFoundError(
            f"no {ticker} level-{levels} message file in {data_dir}; run `lobcast fetch --ticker {ticker}`"
        )
    message = messages[0]
    orderbook = message.with_name(message.name.replace("_message_", "_orderbook_"))
    if not orderbook.exists():
        raise FileNotFoundError(f"missing orderbook file {orderbook}")
    date = message.name.split("_")[1]
    return LobsterFiles(ticker, date, levels, message, orderbook)


def fetch_sample(ticker: str, dest: str | Path, levels: int = 10) -> LobsterFiles:
    if ticker not in SAMPLE_TICKERS:
        raise ValueError(f"sample data covers {', '.join(SAMPLE_TICKERS)}")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    folder = f"LOBSTER_SampleFile_{ticker}_{SAMPLE_DATE}_{levels}"
    for kind in ("message", "orderbook"):
        name = sample_name(ticker, kind, levels)
        target = dest / name
        if target.exists() and target.stat().st_size > 0:
            continue
        url = f"{HF_MIRROR}/{folder}/{name}"
        tmp = target.with_suffix(".part")
        with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        tmp.rename(target)
    return find_lobster_files(dest, ticker, levels)
