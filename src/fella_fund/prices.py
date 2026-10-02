"""Daily closes from Yahoo Finance, cached as one CSV per ticker."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .config import ROOT

CACHE_DIR = ROOT / ".cache" / "prices"
log = logging.getLogger(__name__)


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.csv"


def fetch(tickers: list[str], start: date) -> list[str]:
    """Download full history since `start` and overwrite the cache.

    Returns the tickers that failed (their old cache, if any, is kept).
    """
    import yfinance as yf

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(
        tickers,
        start=(start - timedelta(days=14)).isoformat(),
        auto_adjust=False,
        progress=False,
        threads=False,
        group_by="column",
    )
    failed = []
    for t in tickers:
        try:
            df = pd.DataFrame(
                {"close": raw[("Close", t)], "adj_close": raw[("Adj Close", t)]}
            ).dropna()
        except KeyError:
            df = pd.DataFrame()
        if df.empty:
            failed.append(t)
            continue
        df.index = pd.to_datetime(df.index).date
        df.index.name = "date"
        df.to_csv(_cache_path(t))
    return failed


class PriceBook:
    """Price lookups. `adjusted=True` uses dividend/split-adjusted closes (total return)."""

    def __init__(self, frames: dict[str, pd.DataFrame], adjusted: bool):
        self.frames = frames
        self.col = "adj_close" if adjusted else "close"

    @classmethod
    def from_cache(cls, tickers: list[str], adjusted: bool) -> "PriceBook":
        frames = {}
        missing = []
        for t in tickers:
            p = _cache_path(t)
            if not p.exists():
                missing.append(t)
                continue
            df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
            df.index = df.index.date
            frames[t] = df.sort_index()
        if missing:
            raise FileNotFoundError(
                f"No cached prices for {', '.join(missing)}; run `fella update` first."
            )
        return cls(frames, adjusted)

    def _series(self, ticker: str, col: str | None = None) -> pd.Series:
        return self.frames[ticker][col or self.col]

    def close_before(self, ticker: str, d: date, raw: bool = False) -> tuple[date, float]:
        """Last close strictly before `d` (the fund buys at the close before the 1st)."""
        s = self._series(ticker, "close" if raw else None)
        s = s[s.index < d]
        if s.empty:
            raise ValueError(f"No {ticker} price before {d}")
        return s.index[-1], float(s.iloc[-1])

    def latest(self, ticker: str, raw: bool = False) -> tuple[date, float]:
        s = self._series(ticker, "close" if raw else None)
        return s.index[-1], float(s.iloc[-1])

    @property
    def as_of(self) -> date:
        """Most recent date that every ticker has a price for."""
        return min(df.index[-1] for df in self.frames.values())

    def matrix(self, tickers: list[str]) -> pd.DataFrame:
        """Trading-day x ticker table of prices, forward-filled across gaps."""
        df = pd.DataFrame({t: self._series(t) for t in tickers}).sort_index()
        return df.ffill()
