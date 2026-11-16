# CLAUDE.md

How Claude Code works in this repository.

## Project

Desk Dashboard is a self-hosted dashboard you can read at a glance. It shows portfolio day change and server CPU/RAM. One backend container serves a browser page, a Windows idle screen and an ESP32 display.

**`spec.md` is the source of truth for behavior.** Read it before changing anything. If you need to deviate from it, update `spec.md` in the same PR and explain why.

## Repository layout

```
CLAUDE.md                    this file
spec.md                      behavior spec (source of truth)
README.md                    user-facing setup guide
TESTING.md                   live test checklist for the maintainer
LICENSE                      GPL-3.0
.env.example                 every env var, placeholder values only
docker-compose.example.yml
config/fund-proxies.yaml     default fund → ETF map
server/                      backend service, its tests and fake fixtures
web/                         dashboard page (served by the backend)
windows/                     LIVELY.md + idle-dashboard.ahk
firmware/                    ESP32 PlatformIO project
deploy/                      Unraid guide, Tailscale sidecar example
.github/workflows/           CI and image publishing
```

## Commands

<!-- Fill this in once the stack is chosen, and keep it current. -->

- Backend: install · run (demo mode) · test · lint · format · type-check
- Web: any build or check step
- Docker: build · run demo
- Firmware: build default · build demo

## How we work

- **Build fully, then hand off.** Implement features end to end without stopping for live verification.
  - When the spec is ambiguous, pick the simplest option that fits it, note it under "Decisions" in the PR description, and keep going.
  - Ask only if you're genuinely blocked.
- **Offline checks only.**
  - Run unit tests, linters, formatters, type checks, the Docker build and the firmware compile when available.
  - Never contact SimpleFIN, Finnhub, Unraid or any other real service, and never ask for or use real credentials.
  - Tests mock all HTTP and must fail if they try to reach the real network.
  - If a toolchain can't be installed here (for example Docker, or a blocked PlatformIO download), skip that check and say so in the PR. CI covers it.
- **Live testing belongs to the maintainer.** Anything that can only be verified against real services or hardware gets an entry in `TESTING.md`: setup, steps, expected result, and what to check if it fails. Keep `TESTING.md` in step with the features.
- **Protect the SimpleFIN quota.** No code path may call SimpleFIN on page load, on a client request, or in tests. Always respect the persisted daily cap.

## Git and GitHub

- Work on a `claude/<short-topic>` branch. Never commit directly to `main`, and never force-push `main`.
- Make small, logical commits with imperative messages, e.g. `server: add quote poller`.
- Open one PR per session to `main`. Include:
  - a summary
  - decisions made
  - known gaps and TODOs
  - offline checks run and skipped
  - a link to `TESTING.md`

## Open-source rules (GPL-3.0-or-later)

- Start each source file with `SPDX-License-Identifier: GPL-3.0-or-later` wherever the language allows a comment.
- Only add dependencies whose licenses are compatible with GPL-3.0 (MIT, BSD, Apache-2.0, LGPL, GPL). Pin their versions and list new ones in the PR.
- **Never commit personal or secret data:** secrets, tokens, access URLs, real holdings, balances, account IDs, hostnames, IP addresses or personal details.
  - This applies everywhere: code, fixtures, docs, screenshots and commit messages.
  - Fixtures use obviously fake values.
- Examples use placeholders (`192.168.1.10`, `example.ts.net`, `changeme`). Real config lives in `.env`, `local/` and the firmware secret/config files, all gitignored.

## Code standards

- Configure a formatter, linter and type checker for each language, and run them before committing.
- **Money math:** use decimals, not floats, and round only at output.
- **Logs:**
  - Redact URL credentials, API keys and tokens.
  - Never log balances or account IDs.
- **TLS:** outbound HTTPS always verifies certificates. No `verify=False`, no `setInsecure()`.
- **Network resilience:**
  - Every network call has a timeout, and retries back off.
  - One failing source must never break the others.
- **Time:** store times in UTC; do market logic in America/New_York.
- **No external calls home:** no telemetry, analytics, CDNs or runtime external assets.
- **Code hygiene:**
  - Keep modules small and remove dead code.
  - Comments explain why, not what.

## Docs to keep current

- `README.md` for setup
- `spec.md` for behavior
- `TESTING.md` for live tests
- the Commands section above
