// SPDX-License-Identifier: GPL-3.0-or-later
#include "settings.h"

#include <Preferences.h>

#include "config.h"

Settings settings;

namespace {
constexpr const char* NS = "dash";
}

void Settings::load() {
  Preferences prefs;
  prefs.begin(NS, true);
  serverUrl = prefs.getString("url", "");
  token = prefs.getString("token", "");
  otaPassword = prefs.getString("ota", "");
  view = static_cast<ViewMode>(prefs.getUChar("view", 0) % 3);
  rotateS = constrain(prefs.getUShort("rotate", 10), 3, 3600);
  pctOnly = prefs.getBool("pct", false);
  blMin = prefs.getUChar("blmin", BACKLIGHT_MIN_DEFAULT);
  blMax = prefs.getUChar("blmax", BACKLIGHT_MAX_DEFAULT);
  prefs.end();
  if (blMax < blMin) blMax = blMin;
}

void Settings::save() const {
  Preferences prefs;
  prefs.begin(NS, false);
  prefs.putString("url", serverUrl);
  prefs.putString("token", token);
  prefs.putString("ota", otaPassword);
  prefs.putUChar("view", static_cast<uint8_t>(view));
  prefs.putUShort("rotate", rotateS);
  prefs.putBool("pct", pctOnly);
  prefs.putUChar("blmin", blMin);
  prefs.putUChar("blmax", blMax);
  prefs.end();
}

String Settings::dashboardUrl() const {
  String url = serverUrl;
  url.trim();
  int hash = url.indexOf('#');
  if (hash >= 0) url = url.substring(0, hash);
  while (url.endsWith("/")) url.remove(url.length() - 1);
  return url + "/v1/dashboard";
}
