// SPDX-License-Identifier: GPL-3.0-or-later
// Desk Dashboard firmware for the ESP32-2432S028R ("Cheap Yellow Display").
#include <Arduino.h>
#include <esp_task_wdt.h>

#include "config.h"
#include "model.h"
#include "net.h"
#include "settings.h"
#include "ui.h"

#ifdef DEMO
namespace demo {
void tick();
}
#endif

namespace {

#ifndef DEMO
// Holding BOOT during power-up re-enters setup.
bool bootHeld() {
  pinMode(PIN_BOOT_BUTTON, INPUT_PULLUP);
  if (digitalRead(PIN_BOOT_BUTTON) != LOW) return false;
  ui::message("Setup", "Keep holding BOOT...");
  const uint32_t start = millis();
  while (digitalRead(PIN_BOOT_BUTTON) == LOW) {
    if (millis() - start > BOOT_HOLD_MS) {
      ui::message("Setup", "Release BOOT");
      while (digitalRead(PIN_BOOT_BUTTON) == LOW) delay(10);
      return true;
    }
    delay(10);
  }
  return false;
}
#endif

void startWatchdog() {
  const esp_task_wdt_config_t cfg = {
      .timeout_ms = WDT_TIMEOUT_MS,
      .idle_core_mask = 0,
      .trigger_panic = true,
  };
  esp_task_wdt_reconfigure(&cfg);
  esp_task_wdt_add(nullptr);  // loop task; the fetch task adds itself
}

}  // namespace

void setup() {
  Serial.begin(115200);
  for (int pin : {PIN_LED_R, PIN_LED_G, PIN_LED_B}) {  // RGB LED is active-low: keep it off
    pinMode(pin, OUTPUT);
    digitalWrite(pin, HIGH);
  }
  model::begin();
  settings.load();
  ui::begin();
  Serial.printf("desk-dashboard firmware %s\n", FW_VERSION);

#ifndef DEMO
  const bool force = bootHeld() || !settings.complete();
  net::provision(force);
  net::startFetcher();
#endif
  startWatchdog();
}

void loop() {
  esp_task_wdt_reset();
#ifdef DEMO
  demo::tick();
#else
  net::loop();
  if (net::otaActive()) return;
#endif
  ui::loop();
  delay(20);
}
