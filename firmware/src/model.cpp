// SPDX-License-Identifier: GPL-3.0-or-later
#include "model.h"

#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

namespace {
SemaphoreHandle_t lock = nullptr;
DashState state;

// Days since 1970-01-01 for a civil date (Howard Hinnant's algorithm).
int64_t daysFromCivil(int y, unsigned m, unsigned d) {
  y -= m <= 2;
  const int64_t era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int64_t>(doe) - 719468;
}

// Parses "YYYY-MM-DDTHH:MM:SSZ"; returns -1 if it isn't one.
int64_t parseIso(const char* s) {
  if (!s) return -1;
  int y, mo, d, h, mi, se;
  if (sscanf(s, "%4d-%2d-%2dT%2d:%2d:%2d", &y, &mo, &d, &h, &mi, &se) != 6) return -1;
  return daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + se;
}

void copyStr(char* dst, size_t n, const char* src) { strlcpy(dst, src ? src : "", n); }
}  // namespace

namespace model {

void begin() { lock = xSemaphoreCreateMutex(); }

DashState snapshot() {
  xSemaphoreTake(lock, portMAX_DELAY);
  DashState copy = state;
  xSemaphoreGive(lock);
  return copy;
}

void update(const DashState& next) {
  xSemaphoreTake(lock, portMAX_DELAY);
  uint32_t v = state.version + 1;
  state = next;
  state.version = v;
  xSemaphoreGive(lock);
}

bool parse(const String& json, DashState& out) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) return false;
  JsonObject p = doc["portfolio"];
  JsonObject s = doc["server"];
  if (p.isNull() || s.isNull()) return false;
  const int64_t generated = parseIso(doc["generated_at"]);

  copyStr(out.pStatus, sizeof(out.pStatus), p["status"]);
  out.hasDollar = p["day_change"].is<double>();
  out.dollar = p["day_change"] | 0.0;
  out.hasPct = p["day_change_pct"].is<double>();
  out.pct = p["day_change_pct"] | 0.0;
  copyStr(out.label, sizeof(out.label), p["market"]["label"]);
  out.live = strcmp(p["market"]["state"] | "", "open") == 0;
  out.pending = p["positions"]["pending"] | 0;
  const char* asOf =
      p["as_of"]["quotes"].is<const char*>() ? p["as_of"]["quotes"] : p["as_of"]["holdings"];
  const int64_t pAsOf = parseIso(asOf);
  out.pAgeS = (generated >= 0 && pAsOf >= 0) ? static_cast<int32_t>(generated - pAsOf) : -1;

  copyStr(out.sStatus, sizeof(out.sStatus), s["status"]);
  copyStr(out.name, sizeof(out.name), s["name"] | "Server");
  out.hasCpu = s["cpu_pct"].is<double>();
  out.cpu = s["cpu_pct"] | 0.0f;
  out.hasRam = s["ram_pct"].is<double>();
  out.ram = s["ram_pct"] | 0.0f;
  const int64_t sAsOf = parseIso(s["as_of"]);
  out.sAgeS = (generated >= 0 && sAsOf >= 0) ? static_cast<int32_t>(generated - sAsOf) : -1;
  return true;
}

}  // namespace model
