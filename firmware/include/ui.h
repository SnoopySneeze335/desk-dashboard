// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <Arduino.h>

#include "lgfx_cyd.h"

extern LGFX lcd;

namespace ui {
void begin();
void loop();  // touch, rotation, redraws, backlight
void message(const char* title, const String& line1, const String& line2 = "");
void setBlocking(bool on);  // pause normal rendering (setup screens, OTA)
}  // namespace ui
