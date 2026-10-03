"""Everything the site and the newsletter show, derived from the roster + prices.

Nothing here is stored: the ledger of buys is regenerated from the rule
"on the 1st of each month, buy `monthly_buy` of each employed fella's ticker at
the last close before the 1st", so editing job history and rebuilding is enough.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .config import Fund, Job
from .prices import PriceBook

EPS = 1e-12


@dataclass
class Lot:
    buy_date: date  # the 1st of the month
    basis_date: date  # the close the buy was priced at
    person: str
    company: str
    ticker: str
    amount: float
    basis: float  # price used for returns (adjusted when total_return)
    raw_price: float  # the quoted close, for display

    @property
    def shares(self) -> float:
        return self.amount / self.basis


@dataclass
class Month:
    buy_date: date
    end_date: date | None  # next 1st, or None while in progress
    complete: bool
    lots: list[Lot]
    returns: dict[str, float]  # person -> return of their lot this month
    bench: dict[str, float]  # benchmark ticker -> return over the same window
    fotm: list[str] = field(default_factory=list)
    slotm: list[str] = field(default_factory=list)


@dataclass
class Position:
    """Money-weighted results for a set of lots, plus the same cash flows into each benchmark."""

    contributed: float
    value: float
    xirr: float | None
    bench_value: dict[str, float]
    bench_xirr: dict[str, float | None]

    @property
    def gain(self) -> float:
        return self.value - self.contributed


def month_starts(start: date, through: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    if d < start:
        d = _next_month(d)
    while d <= through:
        out.append(d)
        d = _next_month(d)
    return out


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualized money-weighted return (same convention as Sheets XIRR: 365-day years)."""
    flows = [(d, a) for d, a in flows if abs(a) > EPS]
    if not flows or all(a > 0 for _, a in flows) or all(a < 0 for _, a in flows):
        return None
    t0 = min(d for d, _ in flows)
    ts = [((d - t0).days / 365.0, a) for d, a in flows]

    def npv(r: float) -> float:
        return sum(a / (1.0 + r) ** t for t, a in ts)

    lo, hi = -0.9999, 1.0
    while npv(hi) > 0 and hi < 1e6:
        hi *= 2
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


class Analysis:
    def __init__(self, fund: Fund, prices: PriceBook, today: date):
        self.fund = fund
        self.prices = prices
        self.today = today
        self.as_of = prices.as_of
        self.bench_tickers = [b.ticker for b in fund.benchmarks]
        self.buy_dates = month_starts(fund.start, today)
        self.lots = self._build_lots()
        self.months = self._build_months()

    # ---- ledger -------------------------------------------------------------

    def _build_lots(self) -> list[Lot]:
        lots = []
        for d in self.buy_dates:
            for f in self.fund.fellas:
                job = f.job_on(d)
                if job is None or job.ticker is None:
                    continue
                basis_date, basis = self.prices.close_before(job.ticker, d)
                _, raw = self.prices.close_before(job.ticker, d, raw=True)
                lots.append(
                    Lot(d, basis_date, f.name, job.company, job.ticker,
                        self.fund.monthly_buy, basis, raw)
                )
        return lots

    def _end_price(self, ticker: str, end: date | None) -> float:
        if end is None:
            return self.prices.latest(ticker)[1]
        return self.prices.close_before(ticker, end)[1]

    def _build_months(self) -> list[Month]:
        by_date: dict[date, list[Lot]] = defaultdict(list)
        for lot in self.lots:
            by_date[lot.buy_date].append(lot)
        months = []
        for i, d in enumerate(self.buy_dates):
            nxt = self.buy_dates[i + 1] if i + 1 < len(self.buy_dates) else None
            complete = nxt is not None
            lots = by_date.get(d, [])
            rets = {l.person: self._end_price(l.ticker, nxt) / l.basis - 1 for l in lots}
            bench = {
                b: self._end_price(b, nxt) / self.prices.close_before(b, d)[1] - 1
                for b in self.bench_tickers
            }
            m = Month(d, nxt, complete, lots, rets, bench)
            if complete and d in self.fund.announced_awards:
                m.fotm, m.slotm = (list(x) for x in self.fund.announced_awards[d])
            elif complete and len(rets) >= 2:
                hi, lo = max(rets.values()), min(rets.values())
                m.fotm = [p for p, r in rets.items() if r >= hi - EPS]
                m.slotm = [p for p, r in rets.items() if r <= lo + EPS]
            months.append(m)
        return months

    @property
    def completed_months(self) -> list[Month]:
        return [m for m in self.months if m.complete]

    @property
    def last_completed(self) -> Month | None:
        done = self.completed_months
        return done[-1] if done else None

    @property
    def current_month(self) -> Month | None:
        return self.months[-1] if self.months and not self.months[-1].complete else None

    # ---- money-weighted results ---------------------------------------------

    def position(self, lots: list[Lot]) -> Position:
        contributed = sum(l.amount for l in lots)
        value = sum(l.shares * self.prices.latest(l.ticker)[1] for l in lots)
        flows = [(l.buy_date, -l.amount) for l in lots]
        bench_value, bench_xirr = {}, {}
        for b in self.bench_tickers:
            bv = sum(
                l.amount / self.prices.close_before(b, l.buy_date)[1] * self.prices.latest(b)[1]
                for l in lots
            )
            bench_value[b] = bv
            bench_xirr[b] = xirr(flows + [(self.as_of, bv)])
        return Position(contributed, value, xirr(flows + [(self.as_of, value)]),
                        bench_value, bench_xirr)

    @property
    def portfolio(self) -> Position:
        return self.position(self.lots)

    def by_person(self) -> dict[str, Position]:
        return {f.name: self.position([l for l in self.lots if l.person == f.name])
                for f in self.fund.fellas if any(l.person == f.name for l in self.lots)}

    def by_ticker(self) -> dict[str, Position]:
        return {t: self.position([l for l in self.lots if l.ticker == t])
                for t in dict.fromkeys(l.ticker for l in self.lots)}

    # ---- time series ---------------------------------------------------------

    def history(self) -> pd.DataFrame:
        """Daily value of the fund, each benchmark shadow, each ticker, and money contributed."""
        if not self.lots:
            return pd.DataFrame()
        tickers = list(dict.fromkeys(l.ticker for l in self.lots))
        px = self.prices.matrix(tickers + self.bench_tickers)
        px = px[px.index >= min(l.basis_date for l in self.lots)]
        px = px[px.index <= self.as_of]
        out = pd.DataFrame(index=px.index)
        out["contributed"] = 0.0
        out["fund"] = 0.0
        for t in tickers:
            out[t] = 0.0
        for b in self.bench_tickers:
            out[b] = 0.0
        for l in self.lots:
            held = px.index >= l.basis_date
            out.loc[held, "contributed"] += l.amount
            val = px.loc[held, l.ticker] * l.shares
            out.loc[held, l.ticker] += val
            out.loc[held, "fund"] += val
            for b in self.bench_tickers:
                b_basis = self.prices.close_before(b, l.buy_date)[1]
                out.loc[held, b] += px.loc[held, b] * (l.amount / b_basis)
        return out

    # ---- awards, streaks, records -------------------------------------------

    def award_counts(self, months: list[Month] | None = None) -> dict[str, tuple[int, int]]:
        months = self.completed_months if months is None else months
        counts = {f.name: [0, 0] for f in self.fund.fellas}
        for m in months:
            for p in m.fotm:
                counts[p][0] += 1
            for p in m.slotm:
                counts[p][1] += 1
        return {k: (v[0], v[1]) for k, v in counts.items()}

    def leaders(self, which: int) -> tuple[list[str], int]:
        """All-time FotM (which=0) or SLotM (which=1) leaders and their count."""
        counts = self.award_counts()
        top = max((c[which] for c in counts.values()), default=0)
        return [p for p, c in counts.items() if c[which] == top and top > 0], top

    def streaks(self, benchmark: str = "SPY") -> dict[str, tuple[int, int]]:
        """(current, longest) run of completed months each fella's lot beat `benchmark`."""
        out = {}
        for f in self.fund.fellas:
            cur = best = 0
            for m in self.completed_months:
                if f.name not in m.returns:
                    continue
                if m.returns[f.name] > m.bench[benchmark]:
                    cur += 1
                    best = max(best, cur)
                else:
                    cur = 0
            out[f.name] = (cur, best)
        return out

    def extremes(self) -> tuple[tuple[Month, Lot, float] | None, tuple[Month, Lot, float] | None]:
        """Best and worst single completed month for any lot."""
        rows = [(m, l, m.returns[l.person]) for m in self.completed_months for l in m.lots]
        if not rows:
            return None, None
        return max(rows, key=lambda r: r[2]), min(rows, key=lambda r: r[2])

    def years(self) -> list[dict]:
        """Fella and Stinky Loser of the Year: most monthly titles in a calendar year,
        ties broken by the sum of that fella's monthly returns that year."""
        out = []
        for y in sorted({m.buy_date.year for m in self.completed_months}):
            ms = [m for m in self.completed_months if m.buy_date.year == y]
            counts = self.award_counts(ms)
            total = defaultdict(float)
            for m in ms:
                for p, r in m.returns.items():
                    total[p] += r

            def pick(i: int, sign: int) -> list[str]:
                cands = [p for p in counts if p in total]
                if not cands:
                    return []
                key = lambda p: (counts[p][i], sign * total[p])  # noqa: E731
                best = max(key(p) for p in cands)
                return [p for p in cands if key(p) == best]

            out.append({
                "year": y,
                "complete": any(m.buy_date.month == 12 for m in ms),
                "fella": pick(0, 1),
                "stinky": pick(1, -1),
                "counts": counts,
            })
        return out

    def job_changes(self, start: date, end: date) -> list[str]:
        """Human-readable job moves with a start or end date in [start, end)."""
        events: list[tuple[date, str]] = []
        for f in self.fund.fellas:
            for j in f.jobs:
                if start <= j.start < end and j.start > self.fund.start:
                    events.append((j.start, f"{f.name} started at {_job_label(j)}"))
                if j.end and start <= j.end < end:
                    events.append((j.end, f"{f.name} left {j.company}"))
        return [s for _, s in sorted(events)]


def _job_label(j: Job) -> str:
    return f"{j.company} ({j.ticker})" if j.ticker else f"{j.company} (sitting out)"
