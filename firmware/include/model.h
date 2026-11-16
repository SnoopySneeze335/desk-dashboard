// SPDX-License-Identifier: GPL-3.0-or-later
// The parsed /v1/dashboard response, shared between the network task and the UI.
#pragma once

#include <Arduino.h>

struct DashState {
  // fetch bookkeeping
  uint32_t version = 0;      // bumps on every change
  bool have = false;         // at least one good response
  uint32_t okAtMs = 0;       // millis() of the last good response
  uint32_t failSinceMs = 0;  // millis() of the first failure in a row; 0 when OK
  int lastHttp = 0;          // last HTTP status (-1 transport error)

  // portfolio
  char pStatus[14] = "";
  bool hasDollar = false;
  double dollar = 0;
  bool hasPct = false;
  double pct = 0;
  char label[20] = "";
  bool live = false;
  int pending = 0;
  int32_t pAgeS = -1;  // seconds between the data's as-of time and the response

  // server
  char sStatus[14] = "";
  char name[32] = "Server";
  bool hasCpu = false;
  float cpu = 0;
  bool hasRam = false;
  float ram = 0;
  int32_t sAgeS = -1;
};

namespace model {
void begin();
DashState snapshot();
void update(const DashState& next);
bool parse(const String& json, DashState& out);
}  // namespace model
