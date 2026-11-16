# Desk Dashboard

A self-hosted dashboard you can read at a glance. It shows two things:

- **Portfolio:** today's change across your brokerage holdings, in dollars and percent. Index mutual funds are estimated live from their ETF share-class twins.
- **Server:** CPU % and RAM % of an Unraid server, or of whatever host runs the container.

One small Docker container holds every credential, polls each data source on its own schedule, and serves a single JSON endpoint and a static web page. Show it in a browser, as a Windows idle screen, or on a $15 ESP32 "Cheap Yellow Display" board. Display devices hold only a bearer token, never your financial credentials.

```
 Screens (poll every 15 s)        Backend container               Sources
 browser / Lively / AutoHotkey ─▶  /v1/dashboard (aggregates) ─▶  SimpleFIN Bridge (holdings, 2×/day)
 ESP32 display                     static page at /               Finnhub (quotes, 60 s in market hours)
                                   cache + quota in /data         Unraid GraphQL or /proc (5 s)
```

[`spec.md`](spec.md) is the full behavior spec. [`TESTING.md`](TESTING.md) is the live test checklist.

## Contents

1. [Try it in demo mode](#1-try-it-in-demo-mode)
2. [Get your keys](#2-get-your-keys)
3. [Deploy the container](#3-deploy-the-container)
4. [Open the web page](#4-open-the-web-page)
5. [Windows idle screen](#5-windows-idle-screen)
6. [ESP32 display](#6-esp32-display)
7. [Configuration reference](#7-configuration-reference)
8. [How the day change is calculated](#8-how-the-day-change-is-calculated)
9. [Privacy and security](#9-privacy-and-security)
10. [Development](#10-development)

## 1. Try it in demo mode

Demo mode serves synthetic data and makes no network calls. You don't need any keys.

```bash
docker run --rm -p 8080:8080 -e DEMO_MODE=true ghcr.io/snoopysneeze335/desk-dashboard:latest
```

Open <http://localhost:8080/#token=demo>. Without `DASHBOARD_TOKENS`, demo mode accepts the token `demo`.

## 2. Get your keys

Everything here goes into a `.env` file next to your compose file. Start from [`.env.example`](.env.example), which lists every variable, and never commit the real file.

### Dashboard tokens (required)

Make one random token per screen, and put them comma-separated in `DASHBOARD_TOKENS`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

With one token per screen, you can revoke a lost device by removing its token.

### SimpleFIN Bridge (holdings)

1. Create an account at SimpleFIN Bridge and connect your brokerage.
2. Create a **setup token** for a new app.
3. Claim it once to get your **Access URL**. The setup token is base64; decode it to get a claim URL, then POST to that URL:

   ```bash
   CLAIM_URL=$(echo 'PASTE_SETUP_TOKEN' | base64 -d)
   curl -s -X POST "$CLAIM_URL"
   ```

   The response is the Access URL (`https://user:pass@…/simplefin`). Put it in `SIMPLEFIN_ACCESS_URL`. It's a secret: anyone with it can read your accounts.

The backend fetches holdings at `SIMPLEFIN_FETCH_TIMES` (default 06:00 and 20:00 New York time). It never fetches more than `SIMPLEFIN_MAX_REQUESTS_PER_DAY` (default 4) times in any 24 hours, and the counter survives restarts. A restart with a fresh cache makes no SimpleFIN call at all.

To limit the portfolio to some accounts, set `SIMPLEFIN_ACCOUNTS` to account IDs or parts of account names, for example `SIMPLEFIN_ACCOUNTS=brokerage,roth`.

### Finnhub (quotes)

Sign up for a free API key at Finnhub and put it in `FINNHUB_API_KEY`. Quotes are fetched every 60 seconds during the regular NYSE session, and once more about 5 minutes after the close. The free tier allows 60 calls per minute; the backend stays under 50.

### Unraid (server metrics)

On Unraid 7.2 or later, create an API key with the **Viewer** role. Then set:

```dotenv
UNRAID_GRAPHQL_URL=http://192.168.1.10/graphql   # your server's LAN IP; add :port for a custom web UI port
UNRAID_API_KEY=...
```

Not on Unraid? Use `SERVER_METRICS_SOURCE=host` to read CPU and RAM of the Docker host from `/proc`, or `off` to hide the server view.

## 3. Deploy the container

### Docker Compose

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env        # then edit .env
docker compose up -d
docker compose logs -f
```

The example uses a named volume for `/data`, a restart policy, a `/healthz` healthcheck, a read-only root filesystem and no Linux capabilities. The image runs as a non-root user (uid 10001) and supports linux/amd64 and linux/arm64.

### Unraid

See [`deploy/unraid.md`](deploy/unraid.md). It covers Compose Manager, where `.env` goes, folder permissions, and why the container should use the server's LAN IP for GraphQL.

### Tailscale (HTTPS on your tailnet)

[`deploy/tailscale/compose.tailscale.yml`](deploy/tailscale/compose.tailscale.yml) adds the official Tailscale container as a sidecar. It runs `tailscale serve`, so the dashboard is at `https://desk-dashboard.<your-tailnet>.ts.net/` with a real certificate:

```bash
# add TS_AUTHKEY=tskey-auth-... to .env, then:
docker compose -f docker-compose.yml -f deploy/tailscale/compose.tailscale.yml up -d
```

A Funnel configuration (public internet) is included but commented out. Read the warning in that file before turning it on.

### Image tags

| Tag | Built from |
| --- | --- |
| `latest`, `1`, `1.0`, `1.0.0` | release tags `v*` |
| `edge` | every push to `main` |

## 4. Open the web page

Open the server's address with your token in the URL fragment:

```
https://desk-dashboard.example.ts.net/#token=YOUR_TOKEN
```

The fragment never goes to the server. The page saves the token in local storage and then removes it from the address bar. You can add more options to the fragment:

| Option | Effect |
| --- | --- |
| `rotate=10` | Seconds between view switches |
| `view=portfolio` / `view=server` / `view=both` | Pin one view, or rotate both |
| `pct=1` | Percent only, no dollars |

For example: `#token=YOUR_TOKEN&view=both&rotate=15&pct=1`.

Click, tap, Space or an arrow key switches views. A **STALE** badge appears when a source is stale or failing, or the page hasn't reached the server for over 60 seconds. In that case the page keeps showing the last good numbers.

## 5. Windows idle screen

See [`windows/LIVELY.md`](windows/LIVELY.md). There are two options:

- **Lively Wallpaper as the screensaver** (recommended): no scripts, and Windows asks for your password on resume.
- **`windows/idle-dashboard.ahk`** (AutoHotkey v2): crossfades from the desktop into an Edge kiosk window, skips full-screen video, and locks the PC when you come back.

## 6. ESP32 display

Hardware: an **ESP32-2432S028R** ("Cheap Yellow Display") with a 2.8" 320×240 screen and resistive touch.

### Build and flash

Install [PlatformIO](https://platformio.org/) (`pip install platformio`), connect the board over USB, then:

```bash
cd firmware
pio run -e cyd -t upload          # most boards (ILI9341)
pio run -e cyd-st7789 -t upload   # boards with an ST7789 panel
pio run -e cyd-demo -t upload     # synthetic data, no Wi-Fi: handy for checking the display
```

**Which panel do I have?** Flash `cyd` first. If the screen stays white or garbled, flash `cyd-st7789`. If colors are inverted (black shows as white), add `-DDISPLAY_INVERT=1` to the env's `build_flags`. `-DDISPLAY_ROTATION=3` flips the screen 180°.

### Provision

1. On first boot, the screen shows **Join Wi-Fi "DeskDashboard-Setup"** and a one-time password.
2. Join that network from a phone. A setup page opens; if it doesn't, browse to `192.168.4.1`.
3. Choose your Wi-Fi network, then fill in:
   - **Dashboard URL**: `https://desk-dashboard.example.ts.net`, or `http://192.168.1.10:8080` on the LAN. HTTPS certificates are always validated. Plain HTTP is used only when you type `http://`.
   - **Dashboard token**: one of your `DASHBOARD_TOKENS`.
   - **OTA password**: needed for over-the-air updates. Leave it empty to turn OTA off.
   - View, rotation seconds, percent-only, and backlight minimum/maximum.
4. Save. The board connects and starts showing data.

Everything is stored in the board's flash (NVS), never in this repository. To change settings later, **hold BOOT while plugging in power** until the screen says "Release BOOT". Leaving the token or OTA password blank keeps the saved value.

**Tailnet URL from the ESP32:** the board can't run Tailscale, so it needs to reach the dashboard over the LAN (`http://<server-lan-ip>:8080`) or through a Tailscale Funnel URL.

### Over-the-air updates

```bash
OTA_PASSWORD='your-ota-password' pio run -e cyd-ota -t upload --upload-port desk-dashboard.local
```

You can use the board's IP address if mDNS doesn't resolve.

### Behavior

The display shows the same views, rotation, tap-to-switch, stale badge and percent-only mode as the web page. The backlight dims with room light between the minimum and maximum you set. If Wi-Fi drops, the board reconnects with backoff, and a watchdog restarts it if it ever hangs.

## 7. Configuration reference

Every variable, with its default, is in [`.env.example`](.env.example) and [spec §9](spec.md#9-configuration). Any secret can come from a file instead: set `NAME_FILE=/run/secrets/name`, which works with Docker secrets.

The fund proxy map is in [`config/fund-proxies.yaml`](config/fund-proxies.yaml). It maps Vanguard Admiral funds to their own ETF share class, for example VFIAX→VOO. To add your own entries, mount a YAML file and point `FUND_PROXIES_FILE` at it:

```yaml
SOMEFUND: { proxy: VOO, approximate: true }   # not the same fund: mark it approximate
```

## 8. How the day change is calculated

- **Stocks and ETFs:** shares × Finnhub's day change, with shares × previous close as the base.
- **Mutual funds with a proxy:** fund value × the proxy ETF's percent change. If the holdings snapshot was taken after the close, the day's move is backed out first.
- **Cash and money-market funds:** zero change, but they count in the percent's denominator.
- **Anything else is pending:** it's left out and counted as "N pending" on the screen. Unknown symbols are logged once per holdings fetch, so nothing is silently counted as zero.

Known limitations:

- Fund numbers are estimates. International funds (VTIAX, VTMGX, VEMAX) can differ noticeably from the official change on a given day, because their NAVs use fair-value pricing.
- Holdings update only when SimpleFIN refreshes (about daily), so the numbers lag same-day trades.

## 9. Privacy and security

- The API returns aggregates only: no symbols, account names or IDs, balances or holdings.
- Logs never contain the Access URL, API keys, tokens, account IDs or balances. Ticker symbols can appear in warnings.
- Every outbound HTTPS call verifies certificates, on both the backend and the ESP32.
- The web page makes no external requests: no CDNs, fonts or analytics.
- The container runs as non-root on a read-only filesystem. Only `/data` is writable.

## 10. Development

The stack and the reasons for it:

| Part | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.13, aiohttp, PyYAML | `decimal` for money math, one async library for both server and client, about 108 MB Alpine image |
| Web | Plain HTML/CSS/JS, no build step | Nothing to install or bundle, and no external assets |
| Windows | AutoHotkey v2 script | The spec asks for one script and no binaries |
| Firmware | PlatformIO, Arduino core 3.x (pioarduino), LovyanGFX, ArduinoJson, WiFiManager | Arduino 3.x ships the ESP-IDF CA bundle for proper HTTPS validation; LovyanGFX drives both panel types and the touch controller |

The commands for install, run, test, lint, format, type-check, Docker and firmware builds are in [CLAUDE.md → Commands](CLAUDE.md#commands). CI runs all of them on every pull request, plus a gitleaks secret scan.

## License

[GPL-3.0-or-later](LICENSE).
 
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
 
A self-hosted dashboard you can read at a glance. It shows your portfolio's day change and your home server's load on a browser tab, a Windows idle screen, or a cheap ESP32 display on your desk.
 
> **Status:** early development. The [specification](spec.md) is complete and the first implementation is in progress. Setup steps below will firm up with the first release.

**DISCLAIMER**: This code for this project was entirely generated with Claude Code. Use at your own risk, always keep backups. 
 
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
 
