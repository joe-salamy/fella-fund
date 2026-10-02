"""Load and save the roster (data/fellas.yaml) and the private settings file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("FELLA_ROOT", Path(__file__).resolve().parents[2]))
ROSTER_PATH = ROOT / "data" / "fellas.yaml"
AWARDS_PATH = ROOT / "data" / "announced_awards.yaml"
SECRETS_PATH = Path(
    os.environ.get("FELLA_SECRETS", Path.home() / ".config" / "fella-fund" / "secrets.toml")
)
STATE_DIR = Path(os.environ.get("FELLA_STATE", Path.home() / ".local" / "state" / "fella-fund"))


@dataclass
class Job:
    company: str
    ticker: str | None
    start: date
    end: date | None = None

    def covers(self, d: date) -> bool:
        return self.start <= d and (self.end is None or d <= self.end)


@dataclass
class Fella:
    name: str
    jobs: list[Job] = field(default_factory=list)

    def job_on(self, d: date) -> Job | None:
        return next((j for j in self.jobs if j.covers(d)), None)

    @property
    def current_job(self) -> Job | None:
        return next((j for j in reversed(self.jobs) if j.end is None), None)


@dataclass
class Benchmark:
    ticker: str
    name: str


@dataclass
class Fund:
    name: str
    start: date
    monthly_buy: float
    total_return: bool
    benchmarks: list[Benchmark]
    fellas: list[Fella]
    # buy date -> (fotm, slotm) as announced, overriding the computed winners
    announced_awards: dict[date, tuple[list[str], list[str]]] = field(default_factory=dict)

    @property
    def tickers(self) -> list[str]:
        seen: dict[str, None] = {}
        for f in self.fellas:
            for j in f.jobs:
                if j.ticker:
                    seen[j.ticker] = None
        return list(seen)

    def fella(self, name: str) -> Fella:
        for f in self.fellas:
            if f.name.lower() == name.lower():
                return f
        raise KeyError(f"No fella named {name!r} in {ROSTER_PATH}")

    def validate(self) -> list[str]:
        problems = []
        names = [f.name.lower() for f in self.fellas]
        if len(names) != len(set(names)):
            problems.append("Duplicate fella names.")
        for f in self.fellas:
            jobs = sorted(f.jobs, key=lambda j: j.start)
            for j in jobs:
                if j.end and j.end < j.start:
                    problems.append(f"{f.name}: {j.company} ends before it starts.")
            for a, b in zip(jobs, jobs[1:]):
                if a.end is None or a.end >= b.start:
                    problems.append(
                        f"{f.name}: {a.company} overlaps {b.company} "
                        f"(give {a.company} an end date before {b.start})."
                    )
        return problems


def _as_date(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load_awards(path: Path = AWARDS_PATH) -> dict[date, tuple[list[str], list[str]]]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    return {
        _as_date(d): (list(v.get("fotm") or []), list(v.get("slotm") or []))
        for d, v in raw.items()
    }


def load_fund(path: Path = ROSTER_PATH, awards_path: Path = AWARDS_PATH) -> Fund:
    raw = yaml.safe_load(path.read_text())
    f = raw["fund"]
    fellas = [
        Fella(
            name=p["name"],
            jobs=[
                Job(
                    company=j["company"],
                    ticker=(j.get("ticker") or None),
                    start=_as_date(j["start"]),
                    end=_as_date(j.get("end")),
                )
                for j in p.get("jobs", [])
            ],
        )
        for p in raw["fellas"]
    ]
    for fe in fellas:
        fe.jobs.sort(key=lambda j: j.start)
    return Fund(
        name=f.get("name", "Fella Fund"),
        start=_as_date(f["start"]),
        monthly_buy=float(f["monthly_buy"]),
        total_return=bool(f.get("total_return", True)),
        benchmarks=[Benchmark(b["ticker"], b["name"]) for b in f["benchmarks"]],
        fellas=fellas,
        announced_awards=load_awards(awards_path),
    )


def save_fund(fund: Fund, path: Path = ROSTER_PATH) -> None:
    """Rewrite the roster, keeping the comment header at the top of the file."""
    text = path.read_text()
    header = text[: text.index("fund:")] if "fund:" in text else ""

    def job(j: Job) -> dict:
        d = {"company": j.company, "ticker": j.ticker, "start": j.start}
        if j.end:
            d["end"] = j.end
        return d

    body = {
        "fund": {
            "name": fund.name,
            "start": fund.start,
            "monthly_buy": int(fund.monthly_buy) if fund.monthly_buy.is_integer() else fund.monthly_buy,
            "total_return": fund.total_return,
            "benchmarks": [{"ticker": b.ticker, "name": b.name} for b in fund.benchmarks],
        },
        "fellas": [{"name": f.name, "jobs": [job(j) for j in f.jobs]} for f in fund.fellas],
    }
    dumped = yaml.safe_dump(body, sort_keys=False, default_flow_style=False, indent=2)
    dumped = dumped.replace("\nfellas:", "\n\nfellas:")
    path.write_text(header + dumped)


@dataclass
class Secrets:
    smtp_user: str
    smtp_password: str
    smtp_host: str
    smtp_port: int
    from_name: str
    recipients: list[str]
    alert_to: str
    site_url: str | None
    newsletter_image: Path | None


def load_secrets(path: Path = SECRETS_PATH) -> Secrets:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy secrets.example.toml there and fill it in."
        )
    raw = tomllib.loads(path.read_text())
    smtp, email = raw.get("smtp", {}), raw.get("email", {})
    img = email.get("newsletter_image")
    return Secrets(
        smtp_user=smtp["user"],
        smtp_password=smtp.get("app_password", ""),
        smtp_host=smtp.get("host", "smtp.gmail.com"),
        smtp_port=int(smtp.get("port", 465)),
        from_name=email.get("from_name", "The Fella Fund Managers"),
        recipients=list(email.get("recipients", [])),
        alert_to=email.get("alert_to", smtp["user"]),
        site_url=email.get("site_url") or None,
        newsletter_image=Path(img).expanduser() if img else None,
    )
