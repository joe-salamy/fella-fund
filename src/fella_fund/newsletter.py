"""Render and send the monthly newsletter through Gmail SMTP."""

from __future__ import annotations

import json
import mimetypes
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from . import chart
from .analysis import Analysis
from .config import STATE_DIR, Secrets
from .report import long_date, money, names, pct

SENT_LOG = STATE_DIR / "sent.json"

_env = Environment(loader=PackageLoader("fella_fund"), autoescape=select_autoescape(["j2"]))
_env.globals.update(money=money, pct=pct, names=names)


def _leader_text(leaders: list[str], top: int, fella: bool) -> str:
    who = names(leaders)
    many = len(leaders) > 1
    if fella:
        return (f"Our Fella of the Month Leader{'s are' if many else ' is'} <strong>{who}</strong>, "
                f"with <strong>{top}</strong>. Someone get {'these guys' if many else 'this guy'} a beer.")
    return (f"Our Stinky Loser of the Month Leader{'s are' if many else ' is'} <strong>{who}</strong>, "
            f"with <strong>{top}</strong>. {'What a bunch of fatties!' if many else 'What a fatty!'}")


def render(a: Analysis, report: dict, secrets: Secrets | None, out_dir: Path) -> dict:
    """Build subject, HTML, and inline images. Returns a dict describing the email."""
    from markupsafe import Markup

    m = a.last_completed
    chart_path = chart.render(report, out_dir / "chart.png")
    image = secrets.newsletter_image if secrets else None
    has_image = bool(image and image.exists())

    m_rows, m_best, m_worst, m_name = [], None, None, None
    if m:
        m_name = f"{m.buy_date:%B}"
        m_rows = sorted(
            [{"person": l.person, "company": l.company, "ticker": l.ticker,
              "ret": m.returns[l.person]} for l in m.lots],
            key=lambda x: -x["ret"])
        if m.returns:
            m_best, m_worst = max(m.returns.values()), min(m.returns.values())
        if m.fotm and m.slotm:
            # Announced overrides may name a winner whose recomputed return isn't the max.
            m_best = max(m.returns.get(p, m_best) for p in m.fotm)
            m_worst = min(m.returns.get(p, m_worst) for p in m.slotm)

    year = None
    if m and m.buy_date.month == 12:
        year = next((y for y in a.years() if y["year"] == m.buy_date.year), None)

    primary = a.fund.benchmarks[0].ticker
    streakers = sorted(
        [{"name": n, "streak": s[0]} for n, s in a.streaks(primary).items() if s[0] >= 2],
        key=lambda s: -s["streak"])

    changes = a.job_changes(m.buy_date, a.today) if m else []
    fotm_leaders, fotm_top = a.leaders(0)
    slotm_leaders, slotm_top = a.leaders(1)

    html = _env.get_template("email.html.j2").render(
        r=report,
        m=m,
        m_name=m_name,
        m_rows=m_rows,
        m_best=m_best,
        m_worst=m_worst,
        fella_leader_text=Markup(_leader_text(fotm_leaders, fotm_top, True)),
        stinky_leader_text=Markup(_leader_text(slotm_leaders, slotm_top, False)),
        streakers=streakers,
        year=year,
        job_changes=changes,
        site_url=secrets.site_url if secrets else None,
        has_image=has_image,
    )
    return {
        "subject": f"{a.fund.name} Monthly Newsletter - {long_date(a.today)}",
        "html": html,
        "chart": chart_path,
        "image": image if has_image else None,
        "month": m.buy_date.isoformat() if m else None,
    }


def write_preview(email: dict, out_dir: Path) -> Path:
    """Save the email as a local HTML file with the inline images swapped for file paths."""
    html = email["html"].replace("cid:chart", email["chart"].name)
    if email["image"]:
        html = html.replace("cid:newsletter_image", email["image"].as_uri())
    path = out_dir / "newsletter.html"
    path.write_text(f"<!doctype html><meta charset='utf-8'><title>{email['subject']}</title>"
                    f"<p style='font-family:sans-serif;color:#52514e'>Subject: {email['subject']}</p>{html}")
    return path


def _message(email: dict, secrets: Secrets, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = email["subject"]
    msg["From"] = formataddr((secrets.from_name, secrets.smtp_user))
    msg["To"] = formataddr((secrets.from_name, secrets.smtp_user))
    msg.set_content("This newsletter is best viewed in an email client that shows HTML.")
    msg.add_alternative(email["html"], subtype="html")
    html_part = msg.get_payload()[1]
    for cid, path in (("chart", email["chart"]), ("newsletter_image", email["image"])):
        if not path:
            continue
        ctype = mimetypes.guess_type(path.name)[0] or "image/png"
        maintype, subtype = ctype.split("/")
        html_part.add_related(path.read_bytes(), maintype=maintype, subtype=subtype,
                              cid=f"<{cid}>", filename=path.name)
    return msg


def send(email: dict, secrets: Secrets, recipients: list[str]) -> None:
    """Send one message; recipients go on the envelope only (BCC), never in headers."""
    if not secrets.smtp_password:
        raise RuntimeError("No Gmail app password set in the secrets file.")
    msg = _message(email, secrets, recipients)
    with smtplib.SMTP_SSL(secrets.smtp_host, secrets.smtp_port, timeout=60) as s:
        s.login(secrets.smtp_user, secrets.smtp_password)
        s.send_message(msg, from_addr=secrets.smtp_user,
                       to_addrs=sorted(set(recipients) | {secrets.smtp_user}))


def send_plain(secrets: Secrets, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((secrets.from_name, secrets.smtp_user))
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP_SSL(secrets.smtp_host, secrets.smtp_port, timeout=60) as s:
        s.login(secrets.smtp_user, secrets.smtp_password)
        s.send_message(msg)


def already_sent(month: str) -> str | None:
    if not SENT_LOG.exists():
        return None
    return json.loads(SENT_LOG.read_text()).get(month)


def mark_sent(month: str) -> None:
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(SENT_LOG.read_text()) if SENT_LOG.exists() else {}
    log[month] = datetime.now().isoformat(timespec="seconds")
    SENT_LOG.write_text(json.dumps(log, indent=2) + "\n")

