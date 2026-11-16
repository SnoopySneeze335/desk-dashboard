// SPDX-License-Identifier: GPL-3.0-or-later
// Rendering for the 320x240 panel. Mirrors the web page: portfolio and server
// views, rotation, tap to switch, stale badge and percent-only mode.
#include "ui.h"

#include "config.h"
#include "model.h"
#include "net.h"
#include "settings.h"

LGFX lcd;

namespace {

enum class View : uint8_t { None, Portfolio, Server, Message };

constexpr int W = 320;
constexpr int H = 240;
constexpr int MX = 16;  // side margin

uint16_t cBg, cFg, cMuted, cDim, cUp, cDown, cWarn, cBar, cTrack;

View current = View::None;
uint32_t rotateAtMs = 0;
uint32_t drawnVersion = UINT32_MAX;
uint32_t nextRefreshMs = 0;
bool blocking = false;
bool touchWasDown = false;
uint32_t lastTapMs = 0;
String msgKey;

// backlight
float lightEma = -1;
uint8_t blTarget = BACKLIGHT_MAX_DEFAULT;
uint8_t blNow = 0;
uint32_t nextLightMs = 0;

// ---- backlight --------------------------------------------------------------

void readLight() {
  const int raw = analogRead(PIN_LIGHT_SENSOR);
  lightEma = lightEma < 0 ? raw : lightEma * 0.9f + raw * 0.1f;
  float level = constrain(lightEma / static_cast<float>(LIGHT_RAW_DARK), 0.0f, 1.0f);
#if !LIGHT_SENSOR_INVERTED
  level = 1.0f - level;  // reading rises in the dark, so invert to get "brightness"
#endif
  const uint8_t lo = settings.blMin;
  const uint8_t hi = max(settings.blMax, settings.blMin);
  blTarget = lo + static_cast<uint8_t>((hi - lo) * level);
}

void setBacklight(uint8_t v) {
  blNow = v;
  lcd.setBrightness(v);
}

void fadeBacklight(uint8_t to, uint32_t ms) {
  const uint8_t from = blNow;
  const uint32_t start = millis();
  for (uint32_t t = 0; t < ms; t = millis() - start) {
    setBacklight(from + (static_cast<int>(to) - from) * static_cast<int>(t) / static_cast<int>(ms));
    delay(10);
  }
  setBacklight(to);
}

// ---- formatting ---------------------------------------------------------------

String withCommas(uint64_t n) {
  String s(static_cast<unsigned long>(n % 1000));
  if (n >= 1000) {
    while (s.length() < 3) s = "0" + s;
    return withCommas(n / 1000) + "," + s;
  }
  return s;
}

String fmtMoney(double v) {
  const uint64_t cents = static_cast<uint64_t>(llround(fabs(v) * 100));
  char frac[4];
  snprintf(frac, sizeof(frac), ".%02u", static_cast<unsigned>(cents % 100));
  const char* sign = cents == 0 ? "" : (v > 0 ? "+" : "-");
  return String(sign) + "$" + withCommas(cents / 100) + frac;
}

String fmtPct(double v) {
  char buf[16];
  const double r = round(v * 100) / 100;
  snprintf(buf, sizeof(buf), "%s%.2f%%", r > 0 ? "+" : (r < 0 ? "-" : ""), fabs(r));
  return buf;
}

String fmtAge(int32_t ageS, uint32_t okAtMs) {
  if (ageS < 0) return "";
  const int32_t age = ageS + static_cast<int32_t>((millis() - okAtMs) / 1000);
  if (age < 90) return "as of just now";
  if (age < 3600) return "as of " + String(age / 60) + "m ago";
  if (age < 48 * 3600) return "as of " + String(age / 3600) + "h ago";
  return "as of " + String(age / 86400) + "d ago";
}

uint16_t tone(const DashState& s) {
  const double v = s.hasPct ? s.pct : (s.hasDollar ? s.dollar : 0);
  if (!s.hasPct && !s.hasDollar) return cDim;
  if (v > 0) return cUp;
  if (v < 0) return cDown;
  return cFg;
}

bool bad(const char* status) { return !strcmp(status, "stale") || !strcmp(status, "error"); }

bool failingTooLong(const DashState& s) {
  return s.failSinceMs != 0 && millis() - s.failSinceMs > FAIL_STALE_MS;
}

// ---- drawing ------------------------------------------------------------------

void text(const String& s, int x, int y, const lgfx::IFont* font, uint16_t color, textdatum_t datum,
          int pad = 0) {
  lcd.setFont(font);
  lcd.setTextDatum(datum);
  lcd.setTextColor(color, cBg);
  lcd.setTextPadding(pad);
  lcd.drawString(s, x, y);
}

void badge(bool show, int rightX) {
  const int w = 52, h = 18, y = 13;
  if (!show) {
    lcd.fillRect(rightX - w, y, w, h, cBg);
    return;
  }
  lcd.fillRoundRect(rightX - w, y, w, h, 3, cWarn);
  lcd.setFont(&fonts::FreeSansBold9pt7b);
  lcd.setTextDatum(middle_center);
  lcd.setTextColor(cBg, cWarn);
  lcd.setTextPadding(0);
  lcd.drawString("STALE", rightX - w / 2, y + h / 2 + 1);
}

void header(const char* title, const String& right, bool live, bool stale) {
  String t(title);
  t.toUpperCase();
  text(t, MX, 22, &fonts::FreeSansBold9pt7b, cMuted, middle_left, 190);
  lcd.fillRect(200, 10, W - 200, 26, cBg);
  int rx = W - MX;
  if (right.length()) {
    lcd.setFont(&fonts::DejaVu18);
    const int tw = lcd.textWidth(right);
    text(right, rx, 22, &fonts::DejaVu18, cMuted, middle_right);
    if (live) lcd.fillCircle(rx - tw - 8, 22, 4, cUp);
    rx -= tw + (live ? 18 : 8);
  }
  badge(stale, rx);
}

void footer(const String& left, const String& right) {
  text(left, MX, H - 18, &fonts::DejaVu12, cMuted, middle_left, 180);
  text(right, W - MX, H - 18, &fonts::DejaVu12, cMuted, middle_right, 110);
}

void bigLine(const String& s, int y, uint16_t color, bool large) {
  const lgfx::IFont* fonts_[] = {large ? &fonts::DejaVu72 : &fonts::DejaVu56, &fonts::DejaVu40,
                                 &fonts::DejaVu24};
  const lgfx::IFont* font = fonts_[2];
  for (const lgfx::IFont* f : fonts_) {
    lcd.setFont(f);
    if (lcd.textWidth(s) <= W - 2 * MX) {
      font = f;
      break;
    }
  }
  lcd.fillRect(0, y - 40, W, 80, cBg);
  text(s, MX, y, font, color, middle_left);
}

void drawPortfolio(const DashState& s, bool full) {
  if (full) lcd.fillScreen(cBg);
  header("Portfolio", s.label[0] ? String(s.label) : String("-"), s.live,
         failingTooLong(s) || bad(s.pStatus));
  const uint16_t c = tone(s);
  if (!strcmp(s.pStatus, "unconfigured")) {
    bigLine("Not set up", 110, cDim, false);
    lcd.fillRect(0, 140, W, 50, cBg);
  } else if (!settings.pctOnly && s.hasDollar) {
    bigLine(fmtMoney(s.dollar), 100, c, false);
    lcd.fillRect(0, 140, W, 50, cBg);
    if (s.hasPct) text(fmtPct(s.pct), MX, 160, &fonts::FreeSansBold18pt7b, c, middle_left, 200);
  } else {
    lcd.fillRect(0, 140, W, 50, cBg);
    bigLine(s.hasPct ? fmtPct(s.pct) : String("-"), 120, c, true);
  }
  footer(fmtAge(s.pAgeS, s.okAtMs), s.pending > 0 ? String(s.pending) + " pending" : String(""));
}

void meter(const char* label, bool has, float pct, int y) {
  text(label, MX, y, &fonts::DejaVu18, cMuted, middle_left);
  const int x = 64, w = 160, h = 22;
  lcd.fillRoundRect(x, y - h / 2, w, h, 4, cTrack);
  if (has) {
    const float p = constrain(pct, 0.0f, 100.0f);
    const uint16_t color = p >= 90 ? cDown : (p >= 75 ? cWarn : cBar);
    const int fw = static_cast<int>(w * p / 100.0f);
    if (fw > 0) lcd.fillRoundRect(x, y - h / 2, fw, h, 4, color);
  }
  const String value = has ? String(static_cast<int>(lroundf(pct))) + "%" : String("-");
  text(value, W - MX, y, &fonts::FreeSansBold18pt7b, cFg, middle_right, 76);
}

void drawServer(const DashState& s, bool full) {
  if (full) lcd.fillScreen(cBg);
  header(s.name[0] ? s.name : "Server", "", false, failingTooLong(s) || bad(s.sStatus));
  meter("CPU", s.hasCpu, s.cpu, 95);
  meter("RAM", s.hasRam, s.ram, 150);
  footer(!strcmp(s.sStatus, "unconfigured") ? String("not set up") : fmtAge(s.sAgeS, s.okAtMs), "");
}

void drawMessage(const char* title, const String& l1, const String& l2) {
  lcd.fillScreen(cBg);
  header(title, "", false, false);
  text(l1, W / 2, 105, &fonts::DejaVu18, cFg, middle_center);
  text(l2, W / 2, 140, &fonts::DejaVu12, cMuted, middle_center);
  footer(String("v") + FW_VERSION, "");
}

// What to show instead of data, or "" when data can be shown.
String statusMessage(const DashState& s, String& l2) {
  l2 = "";
#ifndef DEMO
  if (!settings.complete()) {
    l2 = "Hold BOOT while powering on";
    return "Not set up";
  }
  if (s.lastHttp == 401) {
    l2 = "Re-run setup with the right token";
    return "Token rejected";
  }
#endif
  if (s.have) return "";
  if (!net::wifiUp()) return "Connecting to Wi-Fi...";
  if (s.lastHttp == -2) {
    l2 = "URL must start with https:// or http://";
    return "Bad dashboard URL";
  }
  if (s.failSinceMs && millis() - s.failSinceMs > 3000) {
    l2 = s.lastHttp > 0 ? "HTTP " + String(s.lastHttp) : "No response";
    return "Can't reach the server";
  }
  return "Loading...";
}

// ---- rotation -------------------------------------------------------------------

bool sectionOff(const char* status) { return !strcmp(status, "unconfigured"); }

View firstView(const DashState& s) {
  if (settings.view == ViewMode::Server) return View::Server;
  if (settings.view == ViewMode::Portfolio) return View::Portfolio;
  return (sectionOff(s.pStatus) && !sectionOff(s.sStatus)) ? View::Server : View::Portfolio;
}

View nextView(const DashState& s, View from) {
  if (settings.view != ViewMode::Both) return firstView(s);
  View n = from == View::Portfolio ? View::Server : View::Portfolio;
  if (n == View::Portfolio && sectionOff(s.pStatus) && !sectionOff(s.sStatus)) return View::Server;
  if (n == View::Server && sectionOff(s.sStatus) && !sectionOff(s.pStatus)) return View::Portfolio;
  return n;
}

void render(View v, const DashState& s, bool full) {
  if (v == View::Portfolio) drawPortfolio(s, full);
  if (v == View::Server) drawServer(s, full);
}

// Switch views behind a quick backlight dip (~500 ms in total).
void switchTo(View v, const DashState& s) {
  const bool hadContent = current != View::None;
  if (hadContent) fadeBacklight(0, 200);
  current = v;
  render(v, s, true);
  drawnVersion = s.version;
  fadeBacklight(blTarget, hadContent ? 300 : 1500);  // first appearance fades in like the page
  rotateAtMs = millis() + settings.rotateS * 1000UL;
}

}  // namespace

namespace ui {

void begin() {
  lcd.init();
  lcd.setRotation(DISPLAY_ROTATION);
  setBacklight(0);
  cBg = lcd.color565(0, 0, 0);
  cFg = lcd.color565(0xE8, 0xE8, 0xE8);
  cMuted = lcd.color565(0x8C, 0x8C, 0x8C);
  cDim = lcd.color565(0x3A, 0x3A, 0x3A);
  cUp = lcd.color565(0x3D, 0xDC, 0x84);
  cDown = lcd.color565(0xFF, 0x5A, 0x5F);
  cWarn = lcd.color565(0xFF, 0xB0, 0x20);
  cBar = lcd.color565(0x4C, 0x8D, 0xFF);
  cTrack = lcd.color565(0x16, 0x16, 0x16);
  lcd.fillScreen(cBg);
  analogSetPinAttenuation(PIN_LIGHT_SENSOR, ADC_0db);  // the sensor's voltage swing is small
  readLight();
}

void setBlocking(bool on) {
  blocking = on;
  if (!on) {
    current = View::None;
    msgKey = "";
  }
}

void message(const char* title, const String& line1, const String& line2) {
  drawMessage(title, line1, line2);
  if (blNow == 0) fadeBacklight(blTarget, 600);
}

void loop() {
  const uint32_t now = millis();
  if (now >= nextLightMs) {
    nextLightMs = now + 250;
    readLight();
    if (!blocking && current != View::Message && current != View::None && blNow != blTarget) {
      setBacklight(blNow + (blTarget > blNow ? 1 : -1));  // drift gently
    }
  }
  if (blocking) return;

  const DashState s = model::snapshot();

  String l2;
  const String msg = statusMessage(s, l2);
  if (msg.length()) {
    if (current != View::Message || msgKey != msg + l2) {
      current = View::Message;
      msgKey = msg + l2;
      drawMessage("Desk Dashboard", msg, l2);
      if (blNow == 0) fadeBacklight(blTarget, 1500);
    }
    return;
  }
  msgKey = "";

  // Tap anywhere to switch view.
  uint16_t tx, ty;
  const bool down = lcd.getTouch(&tx, &ty) > 0;
  if (down && !touchWasDown && now - lastTapMs > 300) {
    lastTapMs = now;
    switchTo(nextView(s, current == View::Message ? View::None : current), s);
  }
  touchWasDown = down;

  if (current == View::None || current == View::Message) {
    switchTo(firstView(s), s);
  } else if (static_cast<int32_t>(now - rotateAtMs) >= 0) {
    const View n = nextView(s, current);
    if (n != current) {
      switchTo(n, s);
    } else {
      rotateAtMs = now + settings.rotateS * 1000UL;
    }
  } else if (s.version != drawnVersion || now >= nextRefreshMs) {
    render(current, s, false);  // in-place update; no full clear, no flicker
    drawnVersion = s.version;
    nextRefreshMs = now + 5000;  // keeps "as of" text and the stale badge current
  }
}

}  // namespace ui
