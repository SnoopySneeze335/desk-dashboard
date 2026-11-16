// SPDX-License-Identifier: GPL-3.0-or-later
// DEMO build: synthetic data, no network at all.
#ifdef DEMO
#include <Arduino.h>

#include "model.h"

namespace demo {

void tick() {
  static uint32_t next = 0;
  if (millis() < next) return;
  next = millis() + 5000;
  const float t = millis() / 1000.0f;
  DashState s = model::snapshot();
  s.have = true;
  s.okAtMs = millis();
  s.failSinceMs = 0;
  s.lastHttp = 200;
  strlcpy(s.pStatus, "partial", sizeof(s.pStatus));
  s.hasPct = true;
  s.pct = 1.2 * sin(2 * PI * t / 120);
  s.hasDollar = true;
  s.dollar = 31000.0 * s.pct / 100.0;
  strlcpy(s.label, "Live", sizeof(s.label));
  s.live = true;
  s.pending = 1;
  s.pAgeS = 20;
  strlcpy(s.sStatus, "ok", sizeof(s.sStatus));
  strlcpy(s.name, "Demo Server", sizeof(s.name));
  s.hasCpu = true;
  s.cpu = 30 + 18 * sin(2 * PI * t / 40) + 6 * sin(2 * PI * t / 7);
  s.hasRam = true;
  s.ram = 58 + 4 * sin(2 * PI * t / 300);
  s.sAgeS = 2;
  model::update(s);
}

}  // namespace demo
#endif
