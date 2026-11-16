// SPDX-License-Identifier: GPL-3.0-or-later
// Device settings stored in NVS. Secrets (token, OTA password) live only here,
// never in tracked files.
#pragma once

#include <Arduino.h>

enum class ViewMode : uint8_t { Both = 0, Portfolio = 1, Server = 2 };

struct Settings {
  String serverUrl;  // e.g. https://desk-dashboard.example.ts.net
  String token;
  String otaPassword;
  ViewMode view = ViewMode::Both;
  uint16_t rotateS = 10;
  bool pctOnly = false;
  uint8_t blMin = 0;
  uint8_t blMax = 0;

  void load();
  void save() const;
  bool complete() const { return serverUrl.length() > 0 && token.length() > 0; }
  String dashboardUrl() const;
};

extern Settings settings;
