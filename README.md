# Fella Fund

Pretend money, real bragging rights. On the 1st of every month the fund "buys"
$10,000 of the stock of every company a fella works at, then tracks how those
buys do against the same money put into the S&P 500 (SPY) and Nasdaq-100 (QQQ).

Replaces the old Google Sheet + Apps Script (`main.gs`, `buyNewFunds.gs`,
`sendNewsletter.gs`). The history from Aug 2024 is rebuilt from prices, and the
awards that were already announced are kept as-is (`data/announced_awards.yaml`).

## How it works

Only two things are stored by hand:

- `data/fellas.yaml`: who's in the fund and their job history.
- `data/announced_awards.yaml`: past awards that differ from a clean recompute.

Everything else is derived on each run: the ledger of buys, returns, Fella /
Stinky Loser of the Month, streaks, records, and the benchmark shadow portfolios.
So a job change is a roster edit plus a rebuild, even if it's backdated.

Rules:

- Buys happen on the 1st at the **last close before the 1st**.
- **Old shares are held** after a job change and stay credited to that fella.
- **Private company, school, or unemployed = sit out** (`ticker: null`), no buy.
- Returns are **total return** (dividends reinvested, Yahoo adjusted closes).
  Set `total_return: false` in `fellas.yaml` for price-only like the old sheet.
- Fella of the Month = best return on that month's buy (1st to next 1st);
  Stinky Loser = worst. Ties share the title.
- Fella / Stinky Loser of the Year = most monthly titles in the calendar year,
  ties broken by total monthly return. Announced in the January newsletter.
- Annualized returns are money-weighted (XIRR), same as the sheet.

## Commands

```sh
uv run fella update            # download prices into .cache/prices
uv run fella build             # build site/ (index.html + data.json)
uv run fella email             # dry run: writes out/newsletter.html to preview
uv run fella email --to-me     # send a test copy to yourself only
uv run fella email --send      # send to everyone (once per month; --force to resend)
uv run fella publish           # push site/ to the gh-pages branch
uv run fella daily             # update + build + publish   (daily timer)
uv run fella monthly           # update + send + build + publish (1st-of-month timer)
uv run fella check             # validate the roster
uv run pytest                  # tests
```

### Job changes

```sh
uv run fella job list
uv run fella job start Joe --company Apple --ticker AAPL --date 2026-11-03
uv run fella job start Joe --company "Stanford GSB" --sit-out --date 2026-09-01
uv run fella job end Joe --date 2026-10-31          # left, nothing lined up
uv run fella job start Parker --new --company Nvidia --ticker NVDA --date 2024-08-01
uv run fella build
```

`job start` ends the current job the day before the new one and checks that the
ticker has prices on Yahoo. You can also just edit `data/fellas.yaml` by hand.

## Setup

1. **Secrets**: `~/.config/fella-fund/secrets.toml` (chmod 600), see
   `secrets.example.toml`. Holds the Gmail app password, the mailing list, the
   alert address, and the site URL. The mailing list never goes in the repo.
   Emails go out as one message with everyone on BCC.
2. **GitHub Pages**: push this repo to GitHub, run `uv run fella publish` once,
   then set Pages to deploy from the `gh-pages` branch. Put the URL in
   `site_url` so the newsletter links to it.
3. **Timers** (OMEN, user units, linger is on):

   ```sh
   systemctl --user link ~/Code/fella-fund/systemd/fella-*
   systemctl --user enable --now fella-daily.timer fella-monthly.timer
   systemctl --user list-timers 'fella-*'
   ```

   - `fella-daily.timer`: weekdays 6:30pm ET, refreshes and publishes the site.
   - `fella-monthly.timer`: the 1st at 8am PT, sends the newsletter, then publishes.
     `Persistent=true` catches up after downtime; the sent-log in
     `~/.local/state/fella-fund/sent.json` prevents a double send.
   - Any failure emails `alert_to` with the last 60 journal lines.

## Files

```
data/fellas.yaml             roster + job history (edit this)
data/announced_awards.yaml   historical awards kept as announced
src/fella_fund/              analysis, site, newsletter, CLI
src/fella_fund/templates/    site.html.j2, email.html.j2
systemd/                     timers and services
.cache/prices/               price cache (gitignored)
site/, out/                  build output (gitignored)
```
