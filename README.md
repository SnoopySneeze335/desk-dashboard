# Desk Dashboard
 
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
 
A self-hosted dashboard you can read at a glance. It shows your portfolio's day change and your home server's load on a browser tab, a Windows idle screen, or a cheap ESP32 display on your desk.
 
> **Status:** early development. The [specification](spec.md) is complete and the first implementation is in progress. Setup steps below will firm up with the first release.
 
## What it shows
 
Two views that rotate every few seconds:
 
- **Portfolio:** today's change across your brokerage holdings, in dollars and percent. It's close to live during market hours and labeled with the last session (e.g. "Fri close") outside them.
- **Server:** CPU % and RAM % of your Unraid server, or any Docker host.
## How it works
 
```
 Screens                       Backend container                Data sources
 ┌─────────────────────┐       ┌────────────────────────┐       ┌──────────────────────┐
 │ Browser / Lively    │──────▶│ pollers + cache        │──────▶│ SimpleFIN Bridge     │
 │ Windows idle screen │ HTTPS │ day-change math        │──────▶│ Finnhub quotes       │
 │ ESP32 display       │ token │ GET /v1/dashboard      │──────▶│ Unraid API / host    │
 └─────────────────────┘       └────────────────────────┘       └──────────────────────┘
```
 
- **One backend container holds every credential.** It polls each source on its own schedule and serves a small JSON endpoint plus a static web page.
- **Screens are deliberately simple.** They only read `/v1/dashboard` with a bearer token and never see an API key, account number or individual holding.
## Features
 
- **Index mutual funds included.** Mutual funds only price once a day, so their intraday change is estimated from their ETF share-class twin (e.g. VFIAX → VOO, VTSAX → VTI). The default map covers common Vanguard Admiral funds, and you can add your own.
- **Gentle on SimpleFIN.** Holdings are fetched a couple of times a day and cached, with a hard daily request cap that survives restarts.
- **Demo mode.** Run it with no API keys to try it out or design the layout.
- **Windows idle screen.** The dashboard fades in when you walk away, and coming back asks for your password. Use Lively Wallpaper as the screensaver, or an optional AutoHotkey script for a true crossfade.
- **ESP32 desk display.** Firmware for the ESP32-2432S028R ("Cheap Yellow Display"), with certificate-checked HTTPS, auto-dimming and OTA updates.
- **Privacy-minded.** Aggregates only in the API, an optional percent-only mode, no telemetry, no external assets.
## Requirements
 
**Required:**
 
- A Docker host (built and tested on Unraid; any Linux host should work).
- A [SimpleFIN Bridge](https://beta-bridge.simplefin.org) account with your brokerage connected. Holdings must be returned for your brokerage.
- A free [Finnhub](https://finnhub.io) API key.
**Optional:**
 
- An Unraid 7.2+ API key (Viewer role) for server stats. Without it, the container reads host CPU/RAM itself.
- [Tailscale](https://tailscale.com), to reach the dashboard privately from anywhere.
- An ESP32-2432S028R board for the desk display.
## Quick start (planned)
 
> These steps will be finalized with the first release.
 
```bash
git clone https://github.com/<owner>/desk-dashboard.git
cd desk-dashboard
cp .env.example .env              # set DASHBOARD_TOKENS; try DEMO_MODE=true first
cp docker-compose.example.yml docker-compose.yml
docker compose up -d
```
 
Then open `http://<server-ip>:8080/#token=<one of your tokens>`. The token is saved in the browser and removed from the address bar.
 
When demo mode looks right, add your real keys to `.env` and set `DEMO_MODE=false`.
 
### Getting a SimpleFIN access URL
 
SimpleFIN gives you a one-time **setup token**, which you exchange once for a reusable **access URL**:
 
```bash
read -rs -p "SimpleFIN setup token: " SIMPLEFIN_TOKEN; echo
CLAIM_URL=$(echo "$SIMPLEFIN_TOKEN" | base64 --decode)
curl -s -X POST "$CLAIM_URL"      # prints your access URL; it only works once
```
 
Treat the access URL like a password: anyone who has it can read your accounts. Put it in `.env` as `SIMPLEFIN_ACCESS_URL`, and never commit it.
 
## Configuration
 
Every setting is an environment variable. See [`.env.example`](.env.example) and [spec §9](spec.md#9-configuration) for the full list. The main ones:
 
| Variable | Purpose |
| --- | --- |
| `DASHBOARD_TOKENS` | Bearer tokens your screens use (comma-separated) |
| `SIMPLEFIN_ACCESS_URL` | Your SimpleFIN access URL (secret) |
| `FINNHUB_API_KEY` | Your Finnhub key (secret) |
| `UNRAID_GRAPHQL_URL` / `UNRAID_API_KEY` | Unraid server stats (optional) |
| `FUND_PROXIES_FILE` | Your own fund → ETF map, merged over the defaults |
| `HIDE_DOLLAR_AMOUNTS` | Show percent only |
| `DEMO_MODE` | Serve synthetic data with no keys |
 
## Accuracy and limitations
 
- **Fund numbers are estimates.** A fund's change is estimated from its ETF twin and can differ slightly from the official end-of-day price. The difference is largest for international funds, because of fair-value pricing.
- **Holdings lag trades.** They update when SimpleFIN refreshes (about once a day), so on days you trade, the number is approximate.
- **Finnhub's free tier only covers US-listed stocks and ETFs.** Holdings it can't price show as "pending" rather than being counted as zero.
- **This is not financial advice.** It's a glanceable estimate, not a replacement for your brokerage's numbers.
## Roadmap
 
- [ ] M1: Backend with demo mode, data pollers and `/v1/dashboard`
- [ ] M2: Web dashboard page
- [ ] M3: Windows idle screen (Lively guide + AutoHotkey crossfade)
- [ ] M4: ESP32 firmware
- [ ] M5: First release (image on GHCR, full setup guide, test checklist)
## Contributing
 
Issues and pull requests are welcome.
 
- [`spec.md`](spec.md) is the source of truth for how things should behave. If a change alters behavior, update the spec in the same PR.
- [`CLAUDE.md`](CLAUDE.md) describes the working practices, including the rules that keep secrets and personal data out of this public repo.
## License
 
[GPL-3.0-or-later](LICENSE).
 
Not affiliated with SimpleFIN, Finnhub, Unraid, Vanguard, Lively Wallpaper or Tailscale. All trademarks belong to their owners.
 
