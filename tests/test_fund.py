from datetime import date, timedelta

import pandas as pd
import pytest

from fella_fund.analysis import Analysis, month_starts, xirr
from fella_fund.config import Benchmark, Fella, Fund, Job, Secrets
from fella_fund.prices import PriceBook


def book(prices: dict[str, dict[date, float]]) -> PriceBook:
    frames = {}
    for t, rows in prices.items():
        df = pd.DataFrame({"close": rows, "adj_close": rows}).sort_index()
        frames[t] = df
    return PriceBook(frames, adjusted=True)


def daily(start: date, end: date, f) -> dict[date, float]:
    """Weekday prices from f(day_index)."""
    out, d, i = {}, start, 0
    while d <= end:
        if d.weekday() < 5:
            out[d] = f(i)
            i += 1
        d += timedelta(days=1)
    return out


START, END = date(2024, 7, 15), date(2025, 1, 15)
FLAT = daily(START, END, lambda i: 100.0)
UP = daily(START, END, lambda i: 100.0 + i)
DOWN = daily(START, END, lambda i: 200.0 - i * 0.5)


def fund(fellas, awards=None) -> Fund:
    return Fund("Test Fund", date(2024, 8, 1), 10_000, True,
                [Benchmark("SPY", "S&P 500")], fellas, awards or {})


def test_month_starts():
    assert month_starts(date(2024, 8, 1), date(2024, 11, 1)) == [
        date(2024, 8, 1), date(2024, 9, 1), date(2024, 10, 1), date(2024, 11, 1)]
    assert month_starts(date(2024, 8, 15), date(2024, 10, 2)) == [date(2024, 9, 1), date(2024, 10, 1)]


def test_xirr_matches_simple_annual_return():
    r = xirr([(date(2020, 1, 1), -100.0), (date(2021, 1, 1), 110.0)])
    assert r == pytest.approx(1.1 ** (365 / 366) - 1, abs=1e-6)
    assert xirr([(date(2020, 1, 1), 100.0)]) is None


def test_buy_uses_last_close_before_the_1st():
    # Sep 1 2024 was a Sunday: the buy is priced at Friday Aug 30's close.
    a = Analysis(fund([Fella("A", [Job("Up", "UP", date(2024, 8, 1))])]),
                 book({"UP": UP, "SPY": FLAT}), date(2024, 9, 2))
    sep = [l for l in a.lots if l.buy_date == date(2024, 9, 1)][0]
    assert sep.basis_date == date(2024, 8, 30)
    assert sep.basis == UP[date(2024, 8, 30)]


def test_job_change_holds_old_shares_and_sitting_out_skips_buys():
    joe = Fella("Joe", [
        Job("Up Co", "UP", date(2024, 8, 1), date(2024, 9, 15)),
        Job("Grad school", None, date(2024, 9, 16), date(2024, 10, 31)),
        Job("Down Co", "DOWN", date(2024, 11, 1)),
    ])
    a = Analysis(fund([joe]), book({"UP": UP, "DOWN": DOWN, "SPY": FLAT}), date(2024, 12, 5))
    assert [(l.buy_date, l.ticker) for l in a.lots] == [
        (date(2024, 8, 1), "UP"), (date(2024, 9, 1), "UP"),
        (date(2024, 11, 1), "DOWN"), (date(2024, 12, 1), "DOWN")]
    pos = a.by_person()["Joe"]
    assert pos.contributed == 40_000
    # UP shares are still held and valued at today's UP price.
    up_value = sum(l.shares for l in a.lots if l.ticker == "UP") * a.prices.latest("UP")[1]
    assert a.by_ticker()["UP"].value == pytest.approx(up_value)
    assert a.job_changes(date(2024, 9, 1), date(2024, 10, 1)) == [
        "Joe left Up Co", "Joe started at Grad school (sitting out)"]


def test_awards_ties_and_overrides():
    fellas = [Fella(n, [Job(n, t, date(2024, 8, 1))])
              for n, t in [("A", "UP"), ("B", "UP"), ("C", "DOWN")]]
    a = Analysis(fund(fellas), book({"UP": UP, "DOWN": DOWN, "SPY": FLAT}), date(2024, 10, 2))
    aug = a.months[0]
    assert aug.complete and aug.fotm == ["A", "B"] and aug.slotm == ["C"]
    assert not a.months[-1].complete and a.months[-1].fotm == []
    assert a.award_counts()["A"] == (2, 0)

    a2 = Analysis(fund(fellas, {date(2024, 8, 1): (["C"], [])}),
                  book({"UP": UP, "DOWN": DOWN, "SPY": FLAT}), date(2024, 10, 2))
    assert a2.months[0].fotm == ["C"] and a2.months[0].slotm == []


def test_benchmark_shadow_and_streaks():
    a = Analysis(fund([Fella("A", [Job("Up", "UP", date(2024, 8, 1))])]),
                 book({"UP": UP, "SPY": FLAT}), date(2024, 12, 2))
    p = a.portfolio
    assert p.bench_value["SPY"] == pytest.approx(p.contributed)  # flat index
    assert p.value > p.contributed and p.xirr > 0
    assert a.streaks("SPY")["A"] == (4, 4)
    h = a.history()
    assert h["fund"].iloc[-1] == pytest.approx(p.value)
    assert h["SPY"].iloc[-1] == pytest.approx(p.bench_value["SPY"])


def test_validate_catches_overlapping_jobs():
    f = fund([Fella("A", [Job("X", "X", date(2024, 1, 1)), Job("Y", "Y", date(2024, 6, 1))])])
    assert f.validate()  # first job never ended


def test_email_recipients_are_bcc_only(tmp_path):
    from fella_fund import newsletter

    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    s = Secrets("me@example.com", "pw", "smtp.example.com", 465, "Managers",
                ["a@example.com", "b@example.com"], "me@example.com", None, None)
    msg = newsletter._message({"subject": "Hi", "html": "<img src='cid:chart'>",
                               "chart": img, "image": None}, s, s.recipients)
    raw = msg.as_string()
    assert "a@example.com" not in raw and "b@example.com" not in raw
    assert "Content-ID: <chart>" in raw
