# Live test checklist

These are the tests that can only be done against real services and hardware. Everything else runs offline in CI.

The tests form **one batch for a single sitting**, ordered so each one sets up the next: the container in demo mode, then real keys, then access, the web page, Windows and the ESP32. A few tests need the market open or several trading days, so they're marked and can be finished later.

Every test lists **Setup**, **Steps**, **Expected** and **If it fails**. Tick the boxes as you go.

**Before you start**

- [ ] A machine with Docker (the Unraid server, or any PC for test 1).
- [ ] SimpleFIN Access URL, Finnhub API key, Unraid Viewer API key (README §2).
- [ ] Two dashboard tokens, one for browsers and one for the ESP32.
- [ ] Optional: a Tailscale auth key; a Windows PC with Edge; an ESP32-2432S028R and USB cable.
- [ ] **Timing:** start on a trading day before 15:45 New York time if you can. Tests 6 and 7 need the market open and then closed.

Placeholders below: `192.168.1.10` is the server's LAN IP, `example.ts.net` is your tailnet, and `TOKEN` is a dashboard token.

---

## A. Backend

### 1. Container in demo mode

- **Setup:** Docker on any machine. No `.env` needed.
- **Steps:**
  1. `docker run --rm -p 8080:8080 --read-only -e DEMO_MODE=true ghcr.io/snoopysneeze335/desk-dashboard:latest`. Before the first image is published, build it with `docker build -t desk-dashboard .` and run that.
  2. `curl -s localhost:8080/healthz`
  3. `curl -s -H 'Authorization: Bearer demo' localhost:8080/v1/dashboard`
  4. Open `http://localhost:8080/#token=demo`.
- **Expected:**
  - The log says `DEMO_MODE is on` and makes no other network activity.
  - `/healthz` returns `{"ok": true, "sources": {"simplefin": "ok", "finnhub": "ok", "server": "ok"}}`.
  - `/v1/dashboard` returns JSON matching spec §8: `portfolio.status` is `partial` (one demo position is pending on purpose), and `market.label` matches the real clock ("Live" during market hours, otherwise "<Day> close").
  - The page fades in and rotates between the two views every 10 s.
- **If it fails:** `docker logs`. A "configuration error" line names the bad variable. If the port is in use, map `-p 8090:8080`.

### 2. Real keys: first start and SimpleFIN fetch

- **Setup:** On the server, follow `deploy/unraid.md` (or README §3). Fill in `.env` with `DASHBOARD_TOKENS`, `SIMPLEFIN_ACCESS_URL`, `FINNHUB_API_KEY`, `UNRAID_GRAPHQL_URL` and `UNRAID_API_KEY`. Start with an **empty** data folder.
- **Steps:**
  1. `docker compose up -d && docker compose logs -f dashboard`
  2. Wait for `SimpleFIN fetch ok: N account(s), M with holdings; K request(s) left today`.
  3. `curl -s -H "Authorization: Bearer TOKEN" http://192.168.1.10:8080/v1/dashboard | python3 -m json.tool`
  4. Look in the data folder: `ls -la data/` and `cat data/simplefin-quota.json`.
- **Expected:**
  - There's exactly **one** SimpleFIN request, and the quota file lists one timestamp.
  - `holdings-cache.json` exists and is mode 600.
  - `positions.total` equals the number of holdings in your brokerage accounts.
  - The response contains **no** symbols, account names, IDs or balances.
  - The logs contain no Access URL, keys or tokens. Search for them: `docker compose logs | grep -i -e simplefin.org -e "$FINNHUB_API_KEY"` should find nothing.
- **If it fails:**
  - `access denied (403)`: the Access URL was revoked or mistyped. Claim a new one.
  - `0 with holdings`: your brokerage may not return holdings through SimpleFIN. Check the Bridge website. If holdings show there but not here, try removing the `start-date` parameter in `server/desk_dashboard/simplefin.py` (spec §4.1), then rebuild.
  - `DATA_DIR … not writable`: chown the data folder (see `deploy/unraid.md` §3).

### 3. Quota guard and restart without a fetch

- **Setup:** Continue from test 2.
- **Steps:**
  1. `docker compose restart dashboard` and watch the logs.
  2. Stop the container, delete only `data/holdings-cache.json`, then set `SIMPLEFIN_MAX_REQUESTS_PER_DAY=1` in `.env` and start it again.
  3. Restore `SIMPLEFIN_MAX_REQUESTS_PER_DAY=4`. **Don't** delete the quota file. Restart.
- **Expected:**
  1. After the restart: `holdings cache is fresh; no SimpleFIN fetch at startup`. The quota file is unchanged.
  2. `SimpleFIN daily cap (1 per 24 h) reached; skipping fetch`. No request is made, `/healthz` shows `simplefin: error`, and the portfolio status is `error`.
  3. With the cache gone and a cap of 4, it fetches once more (quota file now has 2 entries) and the portfolio comes back.
- **If it fails:** If step 1 fetched, the cache timestamp may be over 24 hours old, or the data folder isn't persistent. Check the volume mapping.

### 4. Pending and unmapped symbols

- **Setup:** Continue. Quotes have been fetched at least once (at startup).
- **Steps:**
  1. Look for `no quote or fund proxy for XXXX; counting it as pending` in the logs.
  2. Compare `positions.pending` with the warnings.
- **Expected:** Each pending symbol is logged once per SimpleFIN fetch, not on every request. Money-market and sweep positions count as priced, not pending. A Vanguard Admiral fund in `config/fund-proxies.yaml` (for example VFIAX) counts as priced.
- **If it fails:**
  - A money-market ticker shows as pending: add it to `CASH_SYMBOLS`. That replaces the default list, so include the defaults too.
  - A fund shows as pending: add it to your own `FUND_PROXIES_FILE` (spec §6). Only add a same-fund ETF share class unless you mark it `approximate: true`.

### 5. Server metrics against Unraid's dashboard

- **Setup:** `UNRAID_GRAPHQL_URL` uses the LAN IP; the key has the Viewer role.
- **Steps:**
  1. Open Unraid's Dashboard tab next to the dashboard's server view (or `curl` the API every few seconds).
  2. Start a CPU-heavy job on the server (for example a parity check, or `stress` in a container) for a minute, then stop it.
- **Expected:**
  - RAM % matches Unraid's within about 1 point.
  - CPU % follows Unraid's but smoothed: a 30 s rolling mean, so it lags and is steadier.
  - `server.as_of` stays under 30 s old, and `/healthz` shows `server: ok`.
- **If it fails:**
  - `GraphQL error (check the API key's role)`: recreate the key with the Viewer role.
  - `HTTP 3xx` or timeouts: the URL is missing a custom port, or "Use SSL/TLS" is set to Strict (use the myunraid.net URL; see `deploy/unraid.md` §5).
  - Fallback: set `SERVER_METRICS_SOURCE=host`.

### 6. Quotes during market hours ⏱ market open

- **Setup:** A trading day, 09:30–16:00 New York time.
- **Steps:**
  1. Poll `/v1/dashboard` twice, 2 minutes apart.
  2. Compare `day_change_pct` with your brokerage's live day change.
- **Expected:**
  - `market.state` is `open` and `label` is `Live`.
  - `as_of.quotes` advances every minute or so, and `day_change` moves.
  - Status is `ok`, or `partial` if anything is pending. It's never `stale` while the container has internet.
  - The numbers are in the same direction and roughly the same size as the brokerage's figure (see test 8 for the exact comparison).
- **If it fails:**
  - `Finnhub rejected the API key`: check `FINNHUB_API_KEY`.
  - `stale` while open: quote polls are failing. Look for `quote for X failed` warnings and check outbound HTTPS from the container.

### 7. Quotes after the close ⏱ after 16:05 New York time

- **Setup:** The same day, after the close (13:05 on early-close days).
- **Steps:** At about 16:06, check the logs (set `LOG_LEVEL=debug` to see `quotes updated`) and query `/v1/dashboard`. Query it again later in the evening.
- **Expected:**
  - One quote poll at about 16:05, then no more polls until the next open.
  - `market.state` is `closed` and `label` is "<Day> close".
  - `day_change` stays fixed through the evening.
  - After the 20:00 SimpleFIN fetch, the number barely changes: post-close fund balances are backed out (spec §5).
- **If it fails:** If the number jumps after the 20:00 fetch, note the size and which funds moved. It may be the back-out rule meeting a brokerage whose `balance-date` isn't what we expect. Report it with the before/after numbers (no account data).

### 8. Day change against the brokerage, over 3+ trading days ⏱ multi-day

- **Setup:** Running normally.
- **Steps:** On at least three trading days, after 16:05 New York time, write down the dashboard's `day_change` and `day_change_pct`, and the brokerage's own day change once it updates (often the next morning for mutual funds).
- **Expected:** The total is usually within a few dollars, or about 0.05 percentage points, of the brokerage. Days with international funds can differ more (spec §6). Over several days the differences don't build up in one direction.
- **If it fails:**
  - A consistent bias: check for pending positions (they're excluded) and approximate proxies.
  - A one-day spike: often the fair-value pricing of international funds.

### 9. Token rejection

- **Steps:**
  1. `curl -i http://192.168.1.10:8080/v1/dashboard`
  2. `curl -i -H 'Authorization: Bearer wrong' http://192.168.1.10:8080/v1/dashboard`
  3. `curl -i -H "Authorization: Bearer TOKEN" http://192.168.1.10:8080/v1/dashboard`
  4. Send 130 requests in under a minute: `for i in $(seq 130); do curl -s -o /dev/null -w '%{http_code} ' -H "Authorization: Bearer TOKEN" http://192.168.1.10:8080/v1/dashboard; done`
- **Expected:**
  1. `401` with body `{"error": "unauthorized"}`.
  2. The same `401`, with nothing that says which part was wrong.
  3. `200`.
  4. `429` after about 120 requests.
- **If it fails:** Check `DASHBOARD_TOKENS` for stray spaces or quotes. Values are trimmed, but quotes are kept.

### 10. Tailnet access through `tailscale serve`

- **Setup:** `TS_AUTHKEY` in `.env`; HTTPS certificates turned on in the Tailscale admin console.
- **Steps:**
  1. `docker compose -f docker-compose.yml -f deploy/tailscale/compose.tailscale.yml up -d`
  2. From another device on the tailnet: `curl -s https://desk-dashboard.example.ts.net/healthz`
  3. Open `https://desk-dashboard.example.ts.net/#token=TOKEN`.
  4. Optional, Funnel: switch `TS_SERVE_CONFIG` to `serve-funnel.json`, allow Funnel in your ACLs, restart, and test from a phone on mobile data. **Switch it back afterwards** unless you need it.
- **Expected:** A valid certificate with no warnings. The first request can take a few seconds while the certificate is issued. Port 8080 is no longer published on the LAN.
- **If it fails:**
  - Check `docker logs desk-dashboard-tailscale` for auth errors.
  - Check the node appears in the admin console.
  - Check `tailscale serve status` with `docker exec desk-dashboard-tailscale tailscale serve status`.

---

## B. Web page

### 11. Desktop window

- **Setup:** Any desktop browser, using the URL from test 10 (or the LAN URL).
- **Steps:**
  1. Open `…/#token=TOKEN`.
  2. Resize the window from tall and narrow to wide.
  3. Click, then press Space, then press the arrow keys.
  4. Open the browser's devtools Network tab and reload.
  5. Add `#view=server`, then `#view=portfolio&pct=1`, then `#rotate=4`.
- **Expected:**
  - The token disappears from the address bar after loading, and a reload still works because the token is remembered.
  - The 320×240 canvas scales evenly and stays centered on black at any size.
  - Every input switches the view at once, with a ~0.6 s crossfade.
  - The only requests are to the dashboard origin: no fonts, CDNs or analytics.
  - The fragment options act as described in README §4, and percent-only hides the dollars.
- **If it fails:** If the page says "Token rejected", re-open it with the right `#token=`. If you see a blank page, check the browser console for CSP errors and report them.

### 12. Full screen, recovery and reduced motion

- **Steps:**
  1. Press F11 for full screen and leave it for at least 3 minutes.
  2. `docker compose restart dashboard` and keep watching.
  3. Stop the container for 2 minutes (`docker compose stop dashboard`), then start it again.
  4. Turn on the OS "reduce motion" setting (Windows: Settings → Accessibility → Visual effects → Animation effects off) and reload.
- **Expected:**
  1. The whole canvas shifts by a few pixels every 3 minutes.
  2. A short restart may go unnoticed. Data continues by itself.
  3. After about 60 s a **STALE** badge appears while the last numbers stay on screen. Within about 60 s of the backend returning, the badge clears with no reload.
  4. View switches and the shift become instant. The initial fade-in still happens.
- **If it fails:** If it doesn't recover, check whether the browser put the tab to sleep. The page refetches when it becomes visible again.

---

## C. Windows

Use **one** of tests 13 and 14 day to day. Test both now, then turn off the one you don't keep.

### 13. Lively screensaver, with lock on resume

- **Setup:** Follow `windows/LIVELY.md`, Option A. For testing, set the screensaver wait to **1 minute**.
- **Steps:**
  1. Don't touch the PC for 1 minute.
  2. Move the mouse.
  3. Start a full-screen YouTube video and wait 2 minutes.
  4. Set the wait back to 5 minutes.
- **Expected:**
  1. A hard cut to black, then the dashboard fades in.
  2. The Windows lock screen appears and asks for your password or PIN.
  3. The screensaver does not start during video playback (browsers hold a wake lock while playing).
- **If it fails:**
  - "Lively" isn't in the screensaver list: re-check Lively's screensaver setting; the menu name may differ by version.
  - No lock: tick "On resume, display logon screen".

### 14. AutoHotkey crossfade, video skip and lock

- **Setup:** Follow `windows/LIVELY.md`, Option B. Set `DashboardUrl`, set `IdleMinutes := 1` for testing, and set the screensaver to *(None)*.
- **Steps:**
  1. Press Ctrl+Alt+Win+D, wait for the dashboard, then press a key.
  2. Leave the PC idle for 1 minute.
  3. Move the mouse.
  4. Play a full-screen video (YouTube in F11, or VLC full screen) and stay idle for 2 minutes.
  5. Put a maximized (not full-screen) window in front and stay idle for 1 minute.
  6. Untick **Enabled** in the tray menu and stay idle for 1 minute.
  7. Check the Edge flags against Microsoft's current "Configure Microsoft Edge kiosk mode" docs. They couldn't be checked from the build environment.
  8. Set `IdleMinutes` back to 5 and add the Startup-folder shortcut.
- **Expected:**
  1. The screen fades to black over about 1.5 s, the dashboard appears full-screen on the primary monitor, and a key press closes it and locks Windows.
  2. The same happens without the hotkey.
  3. The kiosk closes and the lock screen appears. Your normal Edge windows and profile are untouched.
  4. Nothing happens while the video plays.
  5. The dashboard does activate.
  6. Nothing happens.
  7. `--kiosk <url> --edge-kiosk-type=fullscreen` is still documented. If not, update `cmd` in `Activate()`.
- **If it fails:**
  - "Microsoft Edge not found": Edge is installed somewhere unusual. Set the path in `FindEdge()`.
  - The overlay stays black for 15 s: the page title didn't become "Desk Dashboard". Check the URL and token.
  - The dashboard closes immediately after the hotkey: increase the grace period in `ShowNow()` (`Activate(1500)`).

---

## D. ESP32

### 15. Flash, and pick the display variant

- **Setup:** PlatformIO installed; the board on USB.
- **Steps:**
  1. `cd firmware && pio run -e cyd-demo -t upload`
  2. If the screen is white or garbled, add `-DDISPLAY_ST7789` to `[env:cyd-demo]` `build_flags` (or test with `cyd-st7789`) and flash again.
  3. If colors are inverted, add `-DDISPLAY_INVERT=1`. If it's upside down, add `-DDISPLAY_ROTATION=3`.
  4. Tap the screen.
- **Expected:** The demo portfolio view fades in, with green/red numbers and "1 pending". Views rotate every 10 s, and a tap switches immediately with a quick dip. Note which variant worked; you need it for test 16.
- **If it fails:**
  - Upload errors: hold BOOT while the upload starts, or try another USB cable or port.
  - Touch does nothing: it may be a touch wiring or calibration difference. Report the board revision.

### 16. Provisioning

- **Steps:**
  1. Flash the real build from test 15 (`pio run -e cyd -t upload` or `cyd-st7789`).
  2. Join "DeskDashboard-Setup" with the password on screen.
  3. Choose your Wi-Fi and enter the dashboard URL (LAN `http://192.168.1.10:8080` first), the ESP32 token and an OTA password. Save.
- **Expected:** The board joins Wi-Fi and shows "Loading...", then the live dashboard within about 15 s. The token is never shown on screen.
- **If it fails:**
  - "Token rejected": re-provision (test 21) with the right token.
  - "Can't reach the server / No response": the URL or port is wrong, or a firewall is blocking it.
  - The setup page doesn't open: browse to `192.168.4.1`.

### 17. HTTPS to a tailnet or Funnel URL

- **Steps:**
  1. Re-provision (test 21) with your HTTPS URL: the Funnel URL, or the tailnet URL if your LAN routes to the tailnet.
  2. As a negative test, provision a URL with a bad certificate, for example a self-signed HTTPS server on the LAN.
- **Expected:**
  1. Data loads over HTTPS.
  2. "Can't reach the server". The firmware never falls back to insecure TLS.
- **If it fails:** A `*.ts.net` address only resolves to a `100.x` address the board can't route to, unless your LAN routes the tailnet. Use Funnel or the LAN URL (spec §17, open question).

### 18. Light-sensor dimming

- **Steps:** Cover the sensor, the small window near the screen's top edge (on most boards), for 10 s. Then shine a light on it.
- **Expected:** The backlight eases toward the minimum in the dark and toward the maximum in bright light. It never goes fully dark unless you set the minimum to 0.
- **If it fails:**
  - It's backwards: build with `-DLIGHT_SENSOR_INVERTED=1`.
  - The range is wrong: watch `analogRead(34)` values over serial and set `-DLIGHT_RAW_DARK=<reading in a dark room>`.

### 19. Recovering from a Wi-Fi drop

- **Steps:**
  1. Turn the Wi-Fi access point off for 2 minutes, then on again.
  2. Separately, `docker compose stop dashboard` for 2 minutes, then start it.
- **Expected:**
  1. "Connecting to Wi-Fi..." or a STALE badge while it's down. Data returns within about a minute of the AP coming back, without a reset.
  2. A STALE badge after about 60 s, with the last numbers kept. It clears within about 60 s of the backend returning.
- **If it fails:** Capture the serial log (`pio device monitor`). Repeated resets point at the watchdog; report what was on screen.

### 20. OTA update

- **Steps:**
  1. Change something visible, for example `FW_VERSION` in `platformio.ini`.
  2. `OTA_PASSWORD='…' pio run -e cyd-ota -t upload --upload-port desk-dashboard.local`, or use the board's IP.
  3. Try again with a wrong password.
- **Expected:**
  1. The board shows "Updating", restarts, and shows the new version on its "Loading..." screen.
  2. The wrong password is refused.
- **If it fails:** mDNS may not resolve; use the IP address. If no OTA password was set during provisioning, OTA is turned off. Re-provision with one.

### 21. Re-entering setup with BOOT

- **Steps:** Unplug the board, hold BOOT, plug it in, and keep holding until "Release BOOT" appears.
- **Expected:** The setup portal opens with the current URL filled in. Leaving the token and OTA fields blank keeps the saved values.
- **If it fails:** Hold BOOT for longer (more than 1.5 s after power-up).

---

## E. Release

### 22. GHCR image

- **Steps:**
  1. Merge the PR. The **Publish image** workflow builds `edge`.
  2. Tag a release: `git tag v1.0.0 && git push origin v1.0.0`.
  3. In GitHub → Packages → desk-dashboard → Package settings, set visibility to **Public** if you want unauthenticated pulls.
  4. `docker pull ghcr.io/snoopysneeze335/desk-dashboard:latest` on the server, then `docker compose up -d`.
- **Expected:** The `edge`, `1.0.0`, `1.0`, `1` and `latest` tags exist, each for amd64 and arm64. The container comes back with the same quota counter and cache.
- **If it fails:** Look at the workflow log. Check that the repository's Actions settings allow `GITHUB_TOKEN` to write packages.
