"""Turn an Analysis into plain dicts for the site and the newsletter."""

from __future__ import annotations

from datetime import date

from .analysis import Analysis


def money(x: float, cents: bool = True) -> str:
    s = f"${abs(x):,.2f}" if cents else f"${abs(x):,.0f}"
    return f"-{s}" if x < 0 else s


def pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def long_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def month_name(d: date) -> str:
    return f"{d:%B %Y}"


def names(ps: list[str]) -> str:
    return " / ".join(ps)


def build(a: Analysis) -> dict:
    fund = a.fund
    bench = fund.benchmarks
    primary = bench[0].ticker
    port = a.portfolio
    people = a.by_person()
    tickers = a.by_ticker()
    counts = a.award_counts()
    streaks = a.streaks(primary)
    best, worst = a.extremes()
    company_of = {l.ticker: l.company for l in a.lots}

    leaderboard = []
    for f in fund.fellas:
        pos = people.get(f.name)
        job = f.current_job
        leaderboard.append({
            "name": f.name,
            "now": (f"{job.company} ({job.ticker})" if job and job.ticker
                    else f"{job.company}, sitting out" if job else "Sitting out"),
            "contributed": pos.contributed if pos else 0.0,
            "value": pos.value if pos else 0.0,
            "xirr": pos.xirr if pos else None,
            "bench_value": pos.bench_value if pos else {},
            "bench_xirr": pos.bench_xirr if pos else {},
            "alpha": (pos.value - pos.bench_value[primary]) if pos else 0.0,
            "fotm": counts[f.name][0],
            "slotm": counts[f.name][1],
            "streak": streaks[f.name][0],
            "best_streak": streaks[f.name][1],
            "jobs": [
                {"company": j.company, "ticker": j.ticker,
                 "start": j.start.isoformat(), "end": j.end.isoformat() if j.end else None}
                for j in f.jobs
            ],
        })
    leaderboard.sort(key=lambda r: (r["xirr"] is None, -(r["xirr"] or 0)))

    companies = [
        {"ticker": t, "company": company_of[t], "contributed": p.contributed, "value": p.value,
         "xirr": p.xirr, "holders": sorted({l.person for l in a.lots if l.ticker == t})}
        for t, p in tickers.items()
    ]
    companies.sort(key=lambda r: -r["value"])

    months = [
        {
            "buy_date": m.buy_date.isoformat(),
            "label": f"{m.buy_date:%b %Y}",
            "complete": m.complete,
            "lots": [{"person": l.person, "ticker": l.ticker, "company": l.company,
                      "ret": m.returns[l.person]} for l in m.lots],
            "bench": m.bench,
            "fotm": m.fotm,
            "slotm": m.slotm,
        }
        for m in reversed(a.months)
    ]

    hist = a.history()
    history = {
        "dates": [d.isoformat() for d in hist.index],
        "fund": hist["fund"].round(2).tolist(),
        "contributed": hist["contributed"].round(2).tolist(),
        "bench": {b.ticker: hist[b.ticker].round(2).tolist() for b in bench},
        "tickers": {t: hist[t].round(2).tolist() for t in tickers},
    }

    def extreme(e):
        if e is None:
            return None
        m, l, r = e
        return {"month": f"{m.buy_date:%B %Y}", "person": l.person, "ticker": l.ticker, "ret": r}

    beat_best = max(leaderboard, key=lambda r: r["best_streak"], default=None)
    fotm_leaders, fotm_top = a.leaders(0)
    slotm_leaders, slotm_top = a.leaders(1)

    return {
        "fund_name": fund.name,
        "start": fund.start.isoformat(),
        "today": a.today.isoformat(),
        "as_of": a.as_of.isoformat(),
        "as_of_long": long_date(a.as_of),
        "monthly_buy": fund.monthly_buy,
        "total_return": fund.total_return,
        "benchmarks": [{"ticker": b.ticker, "name": b.name} for b in bench],
        "portfolio": {
            "contributed": port.contributed,
            "value": port.value,
            "gain": port.gain,
            "xirr": port.xirr,
            "bench_value": port.bench_value,
            "bench_xirr": port.bench_xirr,
        },
        "fellas": [f.name for f in fund.fellas],
        "leaderboard": leaderboard,
        "companies": companies,
        "company_names": company_of,
        "months": months,
        "history": history,
        "records": {
            "best": extreme(best),
            "worst": extreme(worst),
            "longest_streak": ({"name": beat_best["name"], "months": beat_best["best_streak"]}
                               if beat_best and beat_best["best_streak"] else None),
            "fotm_leaders": fotm_leaders, "fotm_top": fotm_top,
            "slotm_leaders": slotm_leaders, "slotm_top": slotm_top,
            "years": [
                {"year": y["year"], "complete": y["complete"],
                 "fella": y["fella"], "stinky": y["stinky"]}
                for y in reversed(a.years())
            ],
        },
    }
