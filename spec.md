# Desk Dashboard — Specification

Version 1 · License: GPL-3.0-or-later

This file is the source of truth for what the project does. `CLAUDE.md` covers how we work on it.

## 1. Summary

A self-hosted dashboard you can read at a glance, with two views:

- **Portfolio:** today's change across brokerage holdings, in dollars and percent.
- **Server:** CPU % and RAM % of an Unraid server.

One backend container holds every credential, polls each data source on its own schedule, and serves one small JSON endpoint plus a static web page. It's displayed in a browser, on a Windows idle screen, and on an ESP32 board with a 2.8" display.

### Goals

- Day change that's close to live during market hours, including index mutual funds (estimated from their ETF share-class twins).
- No credentials or personal data on any display device or in this repository.
- Recover from restarts and network drops without manual steps.
- Run as one Docker container on a home server; no cloud services beyond the data APIs.

### Non-goals for v1

- Per-position breakdown, history or charts.
- Any write access to financial accounts.
- User accounts; auth is shared bearer tokens.
- Multi-monitor support for the Windows idle screen.

## 2. Architecture

```
 Screens (poll every 15–30 s)         Backend container                 Sources (own schedules)
 ┌──────────────────────────┐  HTTPS  ┌───────────────────────────┐     ┌───────────────────────────┐
 │ Browser / Lively idle    │────────▶│ dashboard server          │────▶│ SimpleFIN Bridge   2×/day │
 │ Windows AutoHotkey idle  │ bearer  │  pollers + cache in /data │────▶│ Finnhub /quote     60 s   │
 │ ESP32 display            │ token   │  day-change math          │────▶│ Unraid GraphQL     5 s    │
 └──────────────────────────┘         │  GET /v1/dashboard        │     │  (or host metrics)        │
                                      │  static web page at /     │     └───────────────────────────┘
                                      └───────────────────────────┘
```

- Screens never talk to the data sources; they only read `/v1/dashboard`.
- `/v1/dashboard` is answered from in-memory state. A client request never triggers an upstream call.
- Default exposure: the tailnet via `tailscale serve`, or the LAN. Tailscale Funnel is optional, for a screen that isn't on the tailnet.

## 3. Implementation constraints

Languages and frameworks are open. Record the choices in `README.md` and the Commands section of `CLAUDE.md`. Whatever is chosen must meet these constraints:

- **Backend:** one Docker image for linux/amd64 and linux/arm64, roughly 200 MB or less, running as a non-root user. Config comes from environment variables; state lives in a `/data` volume.
- **Web page:** static files served by the backend. No runtime CDNs, external fonts or analytics. A build step is allowed only if the Docker build runs it.
- **Windows helper:** a single AutoHotkey v2 script. No compiled binaries in the repo.
- **Firmware:** a PlatformIO project for the ESP32-2432S028R that compiles in CI.
- **Dependencies:** pinned versions, GPL-3.0-compatible licenses only.

## 4. Data sources

### 4.1 SimpleFIN Bridge (holdings)

- **Auth:** an Access URL with Basic Auth credentials embedded in it (`SIMPLEFIN_ACCESS_URL`). It is a secret: never log it, and redact the userinfo part from any error message.
- **Request:** `GET {ACCESS_URL}/accounts`. Ask for the smallest transaction window the protocol allows (for example `start-date` = now). If holdings stop coming back with that parameter, drop it.
- **Response shape** (fake values; numeric fields arrive as strings and must be parsed as decimals):

```json
{"accounts": [{
  "id": "ACT-0001", "name": "Brokerage", "currency": "USD",
  "balance": "25000.00", "balance-date": 1794603600,
  "holdings": [{
    "id": "H-0001", "created": 1777600000, "currency": "USD",
    "cost_basis": "10000.00", "description": "Example 500 Index Fund Admiral Shares",
    "market_value": "12000.00", "purchase_price": "500.00",
    "shares": "20.000", "symbol": "VFIAX"
  }]
}]}
```

- **Holdings are unofficial.** They aren't in the published protocol, but Bridge returns them in practice. An account without a `holdings` array contributes no positions and makes the portfolio status `partial`.
- **Rate limits:** SimpleFIN's suggested use is 24 requests/day; it warns at 48 and blocks at 96. Bridge data refreshes roughly once every 24 hours.
- **Schedule:** fetch at each time in `SIMPLEFIN_FETCH_TIMES` (default `06:00,20:00`, America/New_York). At startup, fetch only if the cache is missing or older than 24 hours.
- **Quota guard:** a hard cap of `SIMPLEFIN_MAX_REQUESTS_PER_DAY` (default 4) per rolling 24 hours, persisted in `/data` so restarts can't exceed it. Nothing may fetch from SimpleFIN on page load, on a client request, or in tests.
- **Account filter:** `SIMPLEFIN_ACCOUNTS` takes comma-separated account IDs or case-insensitive name substrings. Default: every account that has holdings.
- **Cache:** the last good parsed holdings, each account's `balance-date`, and the fetch time are saved in `/data`.

### 4.2 Finnhub (quotes)

- **Request:** `GET https://finnhub.io/api/v1/quote?symbol=SYM`, with the key in the `X-Finnhub-Token` header so it stays out of URLs and logs.
- **Response** (numbers, not strings):

```json
{"c": 371.11, "d": -1.51, "dp": -0.4052, "h": 374.23, "l": 367.99, "o": 374.15, "pc": 372.62, "t": 1794603600}
```

- **Field meanings:** `d = c − pc` and `dp = d / pc × 100`. `t` is the last trade time. Outside market hours `t` is the last session's close, and `d`/`dp` describe that session.
- **Bad responses:** an invalid or unsupported symbol can come back with `c: 0` or null fields. Treat that as unpriceable.
- **Free tier:** 60 calls/minute; US-listed stocks and ETFs only, no mutual funds. Budget at most 50 calls/minute.
- **Symbols quoted:** every stock/ETF holding plus every proxy ETF for a held fund, deduplicated.
- **Schedule:** every `QUOTE_INTERVAL_SECONDS` (default 60) during the regular session, 09:30–16:00 America/New_York, honoring NYSE holidays and early closes. Also once about 5 minutes after the close, and once at startup. No polling otherwise.

### 4.3 Server metrics

- **Unraid 7.2+ GraphQL:** `POST {UNRAID_GRAPHQL_URL}`. This is the web UI's address plus `/graphql`, including any custom web UI port. Send header `x-api-key` with a Viewer-role key and body:

```json
{"query": "{ metrics { cpu { percentTotal } memory { percentTotal } } }"}
```

  Response: `{"data":{"metrics":{"cpu":{"percentTotal":33.0},"memory":{"percentTotal":58.1}}}}`

- **Host fallback:** with `SERVER_METRICS_SOURCE=host`, read host-wide CPU and memory from `/proc` inside the container. These numbers may differ slightly from Unraid's own dashboard.
- **Polling:** every `METRICS_INTERVAL_SECONDS` (default 5).
- **Smoothing:** CPU is a rolling mean over `CPU_SMOOTHING_SECONDS` (default 30). RAM is shown unsmoothed.

## 5. Day-change calculation

Each included holding falls into one class:

| Class | How it's recognized | Day change from |
| --- | --- | --- |
| Stock / ETF | Has a valid Finnhub quote for its own symbol | Its own quote |
| Fund with proxy | Symbol is in the fund-proxy map | The proxy ETF's quote |
| Cash-like | In `CASH_SYMBOLS`, has no symbol, or `market_value / shares` is within 0.5% of 1.00 | Zero change |
| Pending | None of the above, or its proxy quote is unavailable | Left out, but counted |

For each holding, Δ is its day change and $B$ its previous-close value (the base):

$$\Delta_{\text{stock}} = q \cdot d \qquad B_{\text{stock}} = q \cdot pc$$

$$\Delta_{\text{fund}} = B_{\text{fund}} \cdot \frac{dp_{\text{proxy}}}{100}$$

$$\Delta_{\text{day}} = \sum \Delta \qquad \%_{\text{day}} = 100 \cdot \frac{\Delta_{\text{day}}}{\sum B}$$

Here $q$ is shares from SimpleFIN, and $d$, $dp$ and $pc$ come from Finnhub.

- **Fund base:** a fund's `market_value` $V$ is its value as of its account's `balance-date`.
  - If `balance-date` is before the close of the session the quotes describe, $V$ is the previous-close value: $B_{\text{fund}} = V$.
  - If `balance-date` is at or after that close, $V$ already includes the day's move, so back it out: $B_{\text{fund}} = V / (1 + dp_{\text{proxy}}/100)$.
- **Cash-like:** Δ = 0 and $B$ = `market_value`. Cash counts in the denominator.
- **Pending:** left out of both the change and the base. Counted in `positions.pending` and makes the status `partial`.
- **Quotes from an older session** than the current one (for example, one symbol's quote failed today) are treated as pending.
- **Precision:** use decimal arithmetic. Round dollars to cents and percent to 2 decimals only in the response.

## 6. Fund proxy map

- **Default map:** `config/fund-proxies.yaml` ships in the repo. An optional user file at `FUND_PROXIES_FILE` is merged over it.
- **Entry format:** `VIGAX: VUG`, or `SOMEFUND: { proxy: VOO, approximate: true }` for a proxy that isn't the same fund.
- **What the defaults contain:** only pairs that are share classes of the same fund, i.e. Vanguard Admiral shares and their ETF shares. For example VFIAX→VOO, VTSAX→VTI, VTIAX→VXUS, VBTLX→BND, VIGAX→VUG, VVIAX→VTV, VSMAX→VB, VSIAX→VBR, VTMGX→VEA and VEMAX→VWO. Only add a pair when you're sure it's the same fund.
- **International funds** (for example VTMGX and VEMAX): the ETF trades live while the mutual fund's official price uses fair-value pricing. The daily estimate can differ noticeably from the official change on a given day, though it tends to even out. Document this; no special handling.
- **Unmapped symbols:** log a warning naming the symbol once per SimpleFIN fetch, and report the holding as pending. A typo in the map, or an unexpected symbol from the brokerage, must never be silently counted as zero.

## 7. Market state

- `state` is one of: `open`, `pre` (trading day, before the open), `closed` (trading day, after the close), `weekend`, `holiday`.
- `session_date` is the date of the session the numbers describe.
- `label` is for display: "Live" while open, otherwise "<weekday> close" (for example "Fri close").
- Derive these from an NYSE calendar (holidays and early closes) together with the quotes' `t`.

## 8. HTTP API

All timestamps are ISO 8601 in UTC.

### `GET /v1/dashboard`

- **Auth:** requires `Authorization: Bearer <token>`. Tokens come from `DASHBOARD_TOKENS` (comma-separated) and are compared in constant time. A missing or wrong token gets `401` with no detail about what was wrong.
- **Rate limit:** 120 requests/minute total.

```json
{
  "generated_at": "2026-11-16T08:40:00Z",
  "portfolio": {
    "status": "ok",
    "market": {"state": "weekend", "session_date": "2026-11-13", "label": "Fri close"},
    "day_change": -123.45,
    "day_change_pct": -0.41,
    "positions": {"total": 12, "priced": 11, "pending": 1},
    "as_of": {"holdings": "2026-11-16T11:00:00Z", "quotes": "2026-11-13T21:00:00Z"}
  },
  "server": {
    "status": "ok",
    "name": "Server",
    "cpu_pct": 33.0,
    "ram_pct": 58.1,
    "as_of": "2026-11-16T08:39:58Z"
  }
}
```

- **`status` values:** `ok`, `partial`, `stale`, `error` or `unconfigured`. A section whose source isn't configured is `unconfigured` and has null values.
- **Hiding dollars:** `day_change` is null when `HIDE_DOLLAR_AMOUNTS=true`.
- **Stale thresholds:**
  - Quotes: more than 5 minutes old while the market is open.
  - Holdings: last successful fetch more than 36 hours ago.
  - Server metrics: more than 30 seconds old.
- **Never in the response:** symbols, account names or IDs, balances, or holdings. Aggregates only.

### `GET /healthz`

- No auth. Returns `200` with `{"ok": true, "sources": {"simplefin": "ok", "finnhub": "ok", "server": "ok"}}`.
- Source states only, no data values.

### `GET /` and static assets

The web page. No auth needed, because the page itself contains no data.

## 9. Configuration

Every secret can also be read from a file via a `<NAME>_FILE` variant (for Docker secrets).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DASHBOARD_TOKENS` | required | Comma-separated bearer tokens for screens |
| `SIMPLEFIN_ACCESS_URL` | unset | Secret. Portfolio is `unconfigured` without it |
| `SIMPLEFIN_ACCOUNTS` | every account with holdings | Account IDs or name substrings |
| `SIMPLEFIN_FETCH_TIMES` | `06:00,20:00` | Fetch times, America/New_York |
| `SIMPLEFIN_MAX_REQUESTS_PER_DAY` | `4` | Hard cap, rolling 24 h, persisted |
| `FINNHUB_API_KEY` | unset | Secret |
| `QUOTE_INTERVAL_SECONDS` | `60` | Quote polling during the regular session |
| `FUND_PROXIES_FILE` | unset | User proxy map merged over the defaults |
| `CASH_SYMBOLS` | common sweep / money-market tickers | Symbols treated as cash |
| `SERVER_METRICS_SOURCE` | `unraid` if URL set, else `host` | `unraid`, `host` or `off` |
| `UNRAID_GRAPHQL_URL` | unset | e.g. `http://192.168.1.10/graphql` (include a custom port if the web UI uses one) |
| `UNRAID_API_KEY` | unset | Secret, Viewer role |
| `METRICS_INTERVAL_SECONDS` | `5` | Server metrics polling |
| `CPU_SMOOTHING_SECONDS` | `30` | CPU rolling-mean window |
| `SERVER_DISPLAY_NAME` | `Server` | Label on the server view |
| `HIDE_DOLLAR_AMOUNTS` | `false` | Omit dollar change from the API |
| `DEMO_MODE` | `false` | Serve synthetic data; no keys needed |
| `DATA_DIR` | `/data` | Cache and quota state |
| `PORT` | `8080` | HTTP listen port |
| `LOG_LEVEL` | `info` | Log verbosity |

## 10. Web page

- **Canvas:** a fixed logical 320×240 canvas, scaled evenly to fit the window and centered on black. Every layout must read well at 320×240 so it ports to the ESP32.
- **Settings in the URL fragment** (the fragment is never sent to the server):
  - `#token=…` is saved to localStorage (in a try/catch), then removed from the address bar.
  - `rotate=10` sets the rotation interval in seconds.
  - `view=portfolio|server|both` pins one view or rotates both.
  - `pct=1` shows percent only.
- **Polling:** fetch `/v1/dashboard` every 15 s. On errors, back off to 60 s and keep showing the last good data.
- **Portfolio view:** a large signed dollar change, the percent change, the market label and an as-of time. Green when up, red when down.
- **Server view:** the server name, plus CPU and RAM bars with percentages.
- **Rotation:** switch views every `rotate` seconds with a ~600 ms crossfade. A click, tap, Space or arrow key switches immediately.
- **Fade-in on load:** start fully black and fade content in over 1.5 s once the first data arrives (or after 3 s, showing placeholders).
- **Stale badge:** shown on a view when its status is `stale` or `error`, or fetches have failed for over 60 s. Show a small "N pending" note when positions are pending.
- **Burn-in care:** dark background, and shift the whole canvas by up to ±4 px every 3 minutes.
- **Reduced motion:** with `prefers-reduced-motion`, switch instantly and don't animate the shift.
- **No external requests:** system font stack or self-hosted fonts only.

## 11. Windows idle screen

### 11.1 Lively Wallpaper (recommended)

Documentation only, in `windows/LIVELY.md`:

1. Install Lively and add the dashboard URL, including `#token=…`, as a webpage wallpaper.
2. Set Lively as the Windows screensaver, with a 5-minute wait and "On resume, display logon screen" ticked.
3. Set the power plan to turn the display off much later (60 minutes or more), with sleep after that.

Note in the doc: Windows starts screensavers with a hard cut, and the page's fade-in from black softens it.

### 11.2 AutoHotkey v2 crossfade (optional)

`windows/idle-dashboard.ahk`:

- **Settings** at the top of the script: idle minutes (default 5), dashboard URL, fade duration in ms (default 1500), lock on exit (default true), and excluded process names.
- **Idle detection:** `A_TimeIdlePhysical`.
- **When not to activate:** when the foreground window covers its whole monitor (video, games, presentations) or belongs to an excluded process.
- **Activation:**
  1. Fade an always-on-top, borderless black overlay from transparent to opaque over the fade duration.
  2. Launch Microsoft Edge in fullscreen kiosk mode with the URL, using a separate profile directory next to the script, on the primary monitor. Check the current Edge kiosk command-line flags against Microsoft's docs.
  3. Hide the overlay once the page has loaded; the page fades itself in from black.
- **Exit on any physical input:** close the kiosk process, remove the overlay, and call `LockWorkStation` if lock-on-exit is enabled.
- **Tray menu:** enable/disable, "Show now" (for testing) and exit. Add a hotkey that triggers it immediately, also for testing.
- **Docs:** how to start it at login (a Startup-folder shortcut), and a note not to combine it with the screensaver route.

## 12. ESP32 firmware

- **Board:** ESP32-2432S028R, the "Cheap Yellow Display": ESP32, 2.8" 320×240 ILI9341 display (some revisions use ST7789 or need color inversion), XPT2046 resistive touch, light sensor on GPIO 34.
- **Toolchain:** PlatformIO. The framework and libraries are open (Arduino + LVGL is the suggestion). Build flags or a config header select the display driver, color inversion and rotation.
- **Provisioning:** Wi-Fi credentials, server URL and token are entered through a first-boot captive portal (or over serial) and stored in NVS. No secrets in tracked files. Holding the BOOT button during power-up re-enters setup.
- **Networking:**
  - HTTPS with certificate validation using the core's CA bundle; never `setInsecure()`.
  - Plain HTTP only for an explicit `http://` LAN URL.
  - HTTP timeout of 5 s or less.
- **Behavior:** the same as the web page — same JSON, views, rotation, tap to switch, stale badge and percent-only option.
- **Backlight:** auto-dim from the light sensor, clamped between a minimum and maximum.
- **Robustness:**
  - Reconnect Wi-Fi with backoff.
  - Use a watchdog.
  - Network calls must not freeze the UI.
- **Updates:** OTA, protected by a password set during provisioning.
- **Demo build:** a `DEMO` build flag renders synthetic data with no network.

## 13. Deployment

- **`Dockerfile`:** multi-stage build.
- **`docker-compose.example.yml`:** a `/data` volume, an env file, a restart policy and a healthcheck on `/healthz`.
- **Optional Tailscale sidecar:** a compose service using the official Tailscale image, with `tailscale serve` publishing HTTPS on the tailnet. Include the Funnel configuration commented out, with a warning.
- **`deploy/unraid.md`:**
  - Setting it up with Docker Compose on Unraid, and where the `.env` file goes.
  - The container should reach Unraid's GraphQL API at the server's LAN IP, not its Tailscale address.
- **GitHub Actions:**
  - CI on every PR: lint, unit tests, Docker build, firmware compile and a secret scan.
  - Publish the image to GHCR on `v*` tags, and on `main` as `edge`.

## 14. Security and privacy

- **This is a public repository.** No secrets, real holdings, account data, hostnames, IP addresses or personal details in commits, fixtures, screenshots or docs. Ship `.env.example` only. `.env`, `local/` and firmware secret/config files are gitignored.
- **Logs:**
  - Never log the Access URL, API keys, tokens, account IDs or balances.
  - Ticker symbols may appear in warnings, since logs stay on the server.
- **TLS:** every outbound call verifies certificates.
- **API:** responses carry aggregates only.
- **Container:** runs as non-root, with a read-only root filesystem where practical.

## 15. Testing

### 15.1 Offline (automated; run in CI and during development)

- **Fixtures:** obviously fake data matching the shapes in §4.
- **Unit tests cover:**
  - decimal parsing and holding classification
  - Δ and % with stocks, proxied funds, cash and pending positions
  - the post-close back-out rule
  - market state, including weekends, holidays and early closes
  - the quota guard surviving a restart
  - stale thresholds and CPU smoothing
  - Finnhub zero/null handling
  - auth (401 vs 200)
  - that `HIDE_DOLLAR_AMOUNTS` works
  - that responses never contain forbidden fields
- **No real network:** all HTTP is mocked, and a test that tries to reach the real network must fail.
- **Firmware:** compiles in both the default and demo configurations.

### 15.2 Live (manual, in `TESTING.md`)

One batch the maintainer runs in a single sitting, ordered so earlier tests set up later ones. Each test lists setup, steps, the expected result and what to check if it fails. At minimum it covers:

- **Backend:**
  - the container in demo mode, then with real keys
  - a SimpleFIN fetch and the quota counter
  - quotes during market hours and after the close
  - comparing the day change with the brokerage's own figure over 3 or more trading days
- **Server metrics:** Unraid numbers compared with Unraid's dashboard.
- **Access:** token rejection, and tailnet access through `tailscale serve`.
- **Web page:** in a desktop window and full-screen.
- **Windows:**
  - the Lively screensaver, including lock on resume
  - the AutoHotkey crossfade, video skip and lock
- **ESP32:**
  - flashing and provisioning
  - picking the display variant
  - HTTPS to a tailnet or Funnel URL
  - light-sensor dimming
  - recovering from a Wi-Fi drop
  - an OTA update

## 16. Milestones and acceptance

| Milestone | Done when |
| --- | --- |
| M1 Backend | Demo mode serves valid JSON with no keys. With keys, numbers are live during market hours. A restart with a fresh cache makes no SimpleFIN call. All offline tests pass. |
| M2 Web page | Looks right full-screen. Recovers by itself after a backend restart. Percent-only mode works. |
| M3 Windows | Walking away fades into the dashboard. Coming back asks for the password. Full-screen video doesn't trigger it. |
| M4 Firmware | Boots on USB power, shows both views, and recovers from a Wi-Fi drop without a manual reset. Compiles in CI. |
| M5 Release | Image published to GHCR. README covers setup end to end. `TESTING.md` is complete. |

## 17. Known limitations and open questions

- **Fund estimates aren't official.** The ETF-based estimate can differ from the official change, most on international funds.
- **Holdings lag trades.** They update only when SimpleFIN refreshes, so trading days are approximate.
- **Open:** will the ESP32 sit on the server's network, or need a Funnel URL?
- **Open:** should idle screens default to percent-only?
