"""Render the static site (site/index.html + site/data.json)."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .report import money, month_name, names, pct

_env = Environment(loader=PackageLoader("fella_fund"), autoescape=select_autoescape(["j2"]))
_env.globals.update(money=money, pct=pct, names=names)


def _month_end_rows(report: dict) -> list[dict]:
    """One row per month (last trading day) for the charts' table views."""
    h = report["history"]
    rows, last_key = [], None
    for i, d in enumerate(h["dates"]):
        key = d[:7]
        row = {
            "date": d,
            "fund": h["fund"][i],
            "contributed": h["contributed"][i],
            "bench": {t: v[i] for t, v in h["bench"].items()},
            "tickers": {t: v[i] for t, v in h["tickers"].items()},
        }
        if key == last_key:
            rows[-1] = row
        else:
            rows.append(row)
            last_key = key
    return list(reversed(rows))


def build(report: dict, out_dir: Path) -> Path:
    from datetime import date

    out_dir.mkdir(parents=True, exist_ok=True)
    html = _env.get_template("site.html.j2").render(
        r=report,
        table_rows=_month_end_rows(report),
        since=month_name(date.fromisoformat(report["start"])),
    )
    (out_dir / "index.html").write_text(html)
    (out_dir / "data.json").write_text(json.dumps(report, indent=1, default=str))
    (out_dir / ".nojekyll").write_text("")
    return out_dir / "index.html"
