// SPDX-License-Identifier: GPL-3.0-or-later
// Desk Dashboard page: polls /v1/dashboard and renders a 320x240 canvas.
"use strict";

(() => {
  const POLL_MS = 15000;
  const BACKOFF_MS = 60000;
  const FAIL_STALE_MS = 60000;
  const FIRST_PAINT_MS = 3000;
  const SHIFT_MS = 3 * 60 * 1000;
  const SHIFT_PX = 4;
  const TOKEN_KEY = "deskDashboard.token";

  const $ = (sel, root = document) => root.querySelector(sel);
  const canvas = $("#canvas");
  const views = {
    portfolio: $("#view-portfolio"),
    server: $("#view-server"),
    message: $("#view-message"),
  };
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  // ---- settings from the URL fragment (never sent to the server) ----------

  function readSettings() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    let token = params.get("token");
    if (token) {
      try {
        localStorage.setItem(TOKEN_KEY, token);
      } catch (_) {
        /* storage blocked: keep the token in memory for this session */
      }
      params.delete("token");
      const rest = params.toString();
      history.replaceState(
        null,
        "",
        location.pathname + location.search + (rest ? "#" + rest : ""),
      );
    } else {
      try {
        token = localStorage.getItem(TOKEN_KEY);
      } catch (_) {
        token = null;
      }
    }
    const rotate = Number.parseInt(params.get("rotate") || "10", 10);
    const view = params.get("view");
    return {
      token,
      rotateMs: Math.max(3, Number.isFinite(rotate) ? rotate : 10) * 1000,
      view: view === "portfolio" || view === "server" ? view : "both",
      pctOnly: params.get("pct") === "1",
    };
  }

  let settings = readSettings();

  // ---- layout: scale the logical canvas evenly, shift for burn-in ---------

  function fit() {
    const scale = Math.min(window.innerWidth / 320, window.innerHeight / 240);
    canvas.style.scale = String(scale);
  }

  function shift() {
    const dx = Math.round((Math.random() * 2 - 1) * SHIFT_PX);
    const dy = Math.round((Math.random() * 2 - 1) * SHIFT_PX);
    canvas.style.translate = `${dx}px ${dy}px`;
  }

  window.addEventListener("resize", fit);
  fit();
  setInterval(shift, SHIFT_MS);

  // ---- formatting ---------------------------------------------------------

  const money = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  const dayClock = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });

  function signed(n, text) {
    if (n > 0) return "+" + text;
    if (n < 0) return "−" + text; // real minus sign
    return text;
  }

  const fmtMoney = (n) => signed(n, money.format(Math.abs(n)));
  const fmtPct = (n) => signed(n, Math.abs(n).toFixed(2) + "%");

  function fmtAsOf(iso) {
    if (!iso) return "";
    const t = new Date(iso);
    if (Number.isNaN(t.getTime())) return "";
    const sameDay = new Date().toDateString() === t.toDateString();
    return "as of " + (sameDay ? clock : dayClock).format(t);
  }

  function tone(n) {
    if (n === null || n === undefined) return "none";
    return n > 0 ? "up" : n < 0 ? "down" : "flat";
  }

  // Shrink a single line of text until it fits its box.
  function fitText(el, maxPx) {
    el.style.fontSize = "";
    let size = maxPx || Number.parseFloat(getComputedStyle(el).fontSize);
    const avail = el.parentElement.clientWidth - 32;
    while (el.scrollWidth > avail && size > 16) {
      size -= 2;
      el.style.fontSize = size + "px";
    }
  }

  // ---- state --------------------------------------------------------------

  let data = null;
  let lastOk = 0;
  let firstFailAt = 0;
  let message = null;
  let ready = false;

  function reveal() {
    if (ready) return;
    ready = true;
    canvas.classList.add("ready");
  }
  setTimeout(reveal, FIRST_PAINT_MS);

  const failingTooLong = () => firstFailAt !== 0 && Date.now() - firstFailAt > FAIL_STALE_MS;
  const isBad = (status) => status === "stale" || status === "error";

  function renderPortfolio(p) {
    const v = views.portfolio;
    const primary = $(".primary", v);
    const secondary = $(".secondary", v);
    const market = $(".market", v);
    v.classList.toggle("percent-only", settings.pctOnly);

    const dollars = p ? p.day_change : null;
    const pct = p ? p.day_change_pct : null;
    const t = tone(pct !== null && pct !== undefined ? pct : dollars);
    const showDollars = !settings.pctOnly && dollars !== null && dollars !== undefined;

    if (p && p.status === "unconfigured") {
      primary.textContent = "Not set up";
      secondary.textContent = " ";
    } else if (showDollars) {
      primary.textContent = fmtMoney(dollars);
      secondary.textContent = pct === null || pct === undefined ? " " : fmtPct(pct);
    } else {
      primary.textContent = pct === null || pct === undefined ? "—" : fmtPct(pct);
      secondary.textContent = " ";
    }
    primary.className = "primary fit " + (p && p.status === "unconfigured" ? "none" : t);
    secondary.className = "secondary " + t;
    fitText(primary);

    const m = p && p.market;
    market.textContent = m ? m.label : "—";
    market.classList.toggle("live", !!m && m.state === "open");

    const asOf = p && p.as_of ? p.as_of.quotes || p.as_of.holdings : null;
    $(".asof", v).textContent = fmtAsOf(asOf) || " ";
    const pending = p && p.positions ? p.positions.pending : 0;
    $(".pending", v).textContent = pending > 0 ? `${pending} pending` : "";
    $(".badge", v).hidden = !(failingTooLong() || (p && isBad(p.status)));
  }

  function setMeter(el, pct) {
    const fill = $(".fill", el);
    const value = $(".value", el);
    if (pct === null || pct === undefined) {
      fill.style.width = "0";
      value.textContent = "—";
      return;
    }
    const clamped = Math.max(0, Math.min(100, pct));
    fill.style.width = clamped + "%";
    fill.classList.toggle("high", clamped >= 75 && clamped < 90);
    fill.classList.toggle("critical", clamped >= 90);
    value.textContent = Math.round(clamped) + "%";
  }

  function renderServer(s) {
    const v = views.server;
    $(".name", v).textContent = (s && s.name) || "Server";
    setMeter($(".cpu", v), s ? s.cpu_pct : null);
    setMeter($(".ram", v), s ? s.ram_pct : null);
    $(".asof", v).textContent =
      s && s.status === "unconfigured" ? "not set up" : fmtAsOf(s && s.as_of) || " ";
    $(".badge", v).hidden = !(failingTooLong() || (s && isBad(s.status)));
  }

  function render() {
    if (message) {
      $(".message", views.message).textContent = message;
    }
    renderPortfolio(data && data.portfolio);
    renderServer(data && data.server);
    rotation.refresh();
  }

  // ---- rotation -----------------------------------------------------------

  const rotation = (() => {
    let current = null;
    let timer = null;

    function available() {
      if (message && !data) return ["message"];
      if (settings.view !== "both") return [settings.view];
      const list = [];
      const p = data && data.portfolio;
      const s = data && data.server;
      if (!p || p.status !== "unconfigured") list.push("portfolio");
      if (!s || s.status !== "unconfigured") list.push("server");
      return list.length ? list : ["portfolio"];
    }

    function show(name) {
      if (current === name) return;
      current = name;
      document.documentElement.style.setProperty("--fade", reducedMotion.matches ? "0ms" : "600ms");
      for (const [key, el] of Object.entries(views)) el.classList.toggle("active", key === name);
    }

    function schedule() {
      clearTimeout(timer);
      timer = setTimeout(next, settings.rotateMs);
    }

    function next() {
      const list = available();
      const i = list.indexOf(current);
      show(list[(i + 1) % list.length]);
      schedule();
    }

    function refresh() {
      const list = available();
      if (!list.includes(current)) {
        show(list[0]);
        schedule();
      }
    }

    return { next, refresh };
  })();

  function userSwitch(e) {
    if (e.type === "keydown") {
      const keys = [" ", "Spacebar", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
      if (!keys.includes(e.key)) return;
      e.preventDefault();
    }
    rotation.next();
  }
  document.addEventListener("click", userSwitch);
  document.addEventListener("keydown", userSwitch);

  // ---- polling ------------------------------------------------------------

  let pollTimer = null;

  async function poll() {
    let delay = POLL_MS;
    if (!settings.token) {
      message = "Add #token=YOUR_TOKEN to the page address.";
      render();
      reveal();
      return; // nothing to poll until the fragment changes
    }
    try {
      const ctrl = new AbortController();
      const abort = setTimeout(() => ctrl.abort(), 10000);
      const resp = await fetch("/v1/dashboard", {
        headers: { Authorization: "Bearer " + settings.token },
        cache: "no-store",
        signal: ctrl.signal,
      });
      clearTimeout(abort);
      if (resp.status === 401) {
        message = "Token rejected. Open the page with #token=YOUR_TOKEN.";
        data = null;
        throw new Error("unauthorized");
      }
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      data = await resp.json();
      message = null;
      lastOk = Date.now();
      firstFailAt = 0;
      render();
      reveal();
    } catch (_) {
      if (!firstFailAt) firstFailAt = Date.now();
      delay = BACKOFF_MS;
      if (!data && !message && Date.now() - firstFailAt > FIRST_PAINT_MS) {
        message = "Waiting for the dashboard server…";
      }
      render(); // keep showing the last good data, now possibly with a stale badge
      if (message) reveal();
    }
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, delay);
  }

  window.addEventListener("hashchange", () => {
    if (!location.hash) return;
    settings = readSettings();
    render();
    poll();
  });

  // Resume promptly when a hidden tab / sleeping screen comes back.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - lastOk > POLL_MS) poll();
  });

  render();
  poll();
})();
