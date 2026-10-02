"""`fella` command line: update prices, build the site, send the newsletter, edit jobs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, newsletter, prices, report, site
from .analysis import Analysis
from .config import ROOT, Job

SITE_DIR = ROOT / "site"
OUT_DIR = ROOT / "out"


def market_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _all_tickers(fund: config.Fund) -> list[str]:
    return fund.tickers + [b.ticker for b in fund.benchmarks if b.ticker not in fund.tickers]


def _load(args) -> tuple[config.Fund, Analysis, dict]:
    fund = config.load_fund()
    problems = fund.validate()
    if problems:
        sys.exit("Roster problems:\n  " + "\n  ".join(problems))
    tickers = _all_tickers(fund)
    try:
        book = prices.PriceBook.from_cache(tickers, fund.total_return)
    except FileNotFoundError:
        cmd_update(args)
        book = prices.PriceBook.from_cache(tickers, fund.total_return)
    today = date.fromisoformat(args.today) if getattr(args, "today", None) else market_today()
    a = Analysis(fund, book, today)
    return fund, a, report.build(a)


def cmd_update(args) -> None:
    fund = config.load_fund()
    failed = prices.fetch(_all_tickers(fund), fund.start)
    if failed:
        sys.exit(f"Price download failed for: {', '.join(failed)} (kept old cache)")
    print(f"Prices updated for {len(_all_tickers(fund))} tickers.")


def cmd_build(args) -> None:
    _, a, r = _load(args)
    path = site.build(r, SITE_DIR)
    p = r["portfolio"]
    print(f"Built {path}  (as of {a.as_of}: {report.money(p['value'])}, "
          f"XIRR {report.pct(p['xirr'])})")


def cmd_email(args) -> None:
    _, a, r = _load(args)
    try:
        secrets = config.load_secrets()
    except FileNotFoundError as e:
        if args.send or args.to_me:
            sys.exit(str(e))
        secrets = None
    OUT_DIR.mkdir(exist_ok=True)
    email = newsletter.render(a, r, secrets, OUT_DIR)
    preview = newsletter.write_preview(email, OUT_DIR)
    print(f"Subject: {email['subject']}\nPreview: {preview}")

    if args.to_me:
        newsletter.send(email, secrets, [secrets.smtp_user])
        print(f"Sent test copy to {secrets.smtp_user}.")
    elif args.send:
        if not email["month"]:
            sys.exit("No completed month to report on yet.")
        sent = newsletter.already_sent(email["month"])
        if sent and not args.force:
            sys.exit(f"Newsletter for {email['month']} already went out at {sent}; use --force to resend.")
        if not secrets.recipients:
            sys.exit("No recipients in the secrets file.")
        newsletter.send(email, secrets, secrets.recipients)
        newsletter.mark_sent(email["month"])
        print(f"Sent to {len(secrets.recipients)} recipients.")
    else:
        print("Dry run: nothing sent (use --to-me to test, --send for real).")


def cmd_publish(args) -> None:
    if not (SITE_DIR / "index.html").exists():
        sys.exit("Nothing to publish; run `fella build` first.")
    subprocess.run(
        ["ghp-import", "--no-jekyll", "--push", "--force",
         "--message", f"Update site {datetime.now():%Y-%m-%d %H:%M}", str(SITE_DIR)],
        cwd=ROOT, check=True,
    )
    print("Published site to the gh-pages branch.")


def cmd_daily(args) -> None:
    cmd_update(args)
    cmd_build(args)
    if not args.no_publish:
        cmd_publish(args)


def cmd_monthly(args) -> None:
    cmd_update(args)
    args.send, args.to_me = True, False
    cmd_email(args)
    cmd_build(args)
    if not args.no_publish:
        cmd_publish(args)


def cmd_check(args) -> None:
    fund = config.load_fund()
    problems = fund.validate()
    known = {f.name for f in fund.fellas}
    for d, (fotm, slotm) in fund.announced_awards.items():
        for n in fotm + slotm:
            if n not in known:
                problems.append(f"announced_awards {d}: unknown fella {n!r}")
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(fund.fellas)} fellas, tickers: {', '.join(fund.tickers)}")
    if problems:
        sys.exit(1)
    print("Roster OK.")


def cmd_job_list(args) -> None:
    fund = config.load_fund()
    for f in fund.fellas:
        print(f.name)
        for j in f.jobs:
            what = j.ticker or "sitting out"
            print(f"  {j.start} to {str(j.end or 'now'):10}  {j.company} ({what})")


def cmd_job_start(args) -> None:
    """Record a new job. Ends the fella's current job the day before, if it's open."""
    fund = config.load_fund()
    try:
        f = fund.fella(args.name)
    except KeyError:
        if not args.new:
            sys.exit(f"No fella named {args.name!r}; pass --new to add them.")
        f = config.Fella(args.name)
        fund.fellas.append(f)
    start = date.fromisoformat(args.date)
    cur = f.current_job
    if cur and cur.start < start:
        cur.end = start - timedelta(days=1)
    ticker = None if args.sit_out else (args.ticker or "").upper() or None
    if ticker is None and not args.sit_out:
        sys.exit("Give --ticker, or --sit-out for a private company / school / unemployed.")
    f.jobs.append(Job(args.company, ticker, start))
    f.jobs.sort(key=lambda j: j.start)
    problems = fund.validate()
    if problems:
        sys.exit("Not saved:\n  " + "\n  ".join(problems))
    if ticker:
        failed = prices.fetch([ticker], fund.start)
        if failed:
            sys.exit(f"Couldn't find prices for {ticker} on Yahoo Finance; not saved.")
    config.save_fund(fund)
    print(f"{f.name}: {args.company} ({ticker or 'sitting out'}) from {start}. Run `fella build`.")


def cmd_job_end(args) -> None:
    """End a fella's current job without a new one (they sit out from then on)."""
    fund = config.load_fund()
    f = fund.fella(args.name)
    cur = f.current_job
    if not cur:
        sys.exit(f"{f.name} has no current job.")
    cur.end = date.fromisoformat(args.date)
    problems = fund.validate()
    if problems:
        sys.exit("Not saved:\n  " + "\n  ".join(problems))
    config.save_fund(fund)
    print(f"{f.name}: {cur.company} ends {cur.end}. Run `fella build`.")


def cmd_alert(args) -> None:
    """Email the manager that a scheduled run failed (used by the systemd OnFailure unit)."""
    secrets = config.load_secrets()
    log = subprocess.run(
        ["journalctl", "--user", "-u", args.unit, "-n", "60", "--no-pager"],
        capture_output=True, text=True,
    ).stdout
    newsletter.send_plain(secrets, secrets.alert_to, f"Fella Fund: {args.unit} failed",
                          f"The scheduled job {args.unit} failed on {datetime.now():%Y-%m-%d %H:%M}.\n\n{log}")
    print(f"Alert sent to {secrets.alert_to}.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fella", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        p = sub.add_parser(name, help=help, description=help)
        p.set_defaults(fn=fn)
        p.add_argument("--today", help="Pretend today is YYYY-MM-DD (for testing).")
        return p

    add("update", cmd_update, "Download prices into the cache.")
    add("build", cmd_build, "Build the static site into site/.")
    e = add("email", cmd_email, "Render the newsletter (dry run by default).")
    g = e.add_mutually_exclusive_group()
    g.add_argument("--send", action="store_true", help="Send to the whole mailing list.")
    g.add_argument("--to-me", action="store_true", help="Send a test copy only to yourself.")
    e.add_argument("--force", action="store_true", help="Send even if this month already went out.")
    add("publish", cmd_publish, "Push site/ to the gh-pages branch.")
    d = add("daily", cmd_daily, "update + build + publish (the daily timer).")
    d.add_argument("--no-publish", action="store_true")
    m = add("monthly", cmd_monthly, "update + send newsletter + build + publish (the 1st-of-month timer).")
    m.add_argument("--no-publish", action="store_true")
    m.add_argument("--force", action="store_true")
    add("check", cmd_check, "Validate the roster.")
    al = add("alert", cmd_alert, "Email a failure notice for a systemd unit.")
    al.add_argument("unit")

    job = sub.add_parser("job", help="View or change job history.").add_subparsers(dest="job", required=True)
    job.add_parser("list", help="Show everyone's job history.").set_defaults(fn=cmd_job_list)
    js = job.add_parser("start", help="Record a new job (closes the current one the day before).")
    js.add_argument("name")
    js.add_argument("--company", required=True)
    js.add_argument("--ticker")
    js.add_argument("--sit-out", action="store_true", help="Private company, school, or unemployed.")
    js.add_argument("--date", required=True, help="First day at the new job, YYYY-MM-DD.")
    js.add_argument("--new", action="store_true", help="Add a fella who isn't on the roster yet.")
    js.set_defaults(fn=cmd_job_start)
    je = job.add_parser("end", help="End the current job with nothing lined up (sits out after).")
    je.add_argument("name")
    je.add_argument("--date", required=True, help="Last day at the job, YYYY-MM-DD.")
    je.set_defaults(fn=cmd_job_end)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
