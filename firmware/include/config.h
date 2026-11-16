// SPDX-License-Identifier: GPL-3.0-or-later
// Compile-time options. Override with -D build flags in platformio.ini, or
// create include/user_config.h (gitignored) for local tweaks.
#pragma once

#if __has_include("user_config.h")
#include "user_config.h"
#endif

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

// ---- Display ---------------------------------------------------------------
#ifndef DISPLAY_INVERT
#define DISPLAY_INVERT 0  // 1 if black shows as white (common on ST7789 boards)
#endif
#ifndef DISPLAY_ROTATION
#define DISPLAY_ROTATION 1  // landscape, USB connector on the right
#endif

// ---- Pins (ESP32-2432S028R) -------------------------------------------------
#define PIN_TFT_SCLK 14
#define PIN_TFT_MOSI 13
#define PIN_TFT_MISO 12
#define PIN_TFT_CS 15
#define PIN_TFT_DC 2
#define PIN_TFT_BL 21
#define PIN_TOUCH_SCLK 25
#define PIN_TOUCH_MOSI 32
#define PIN_TOUCH_MISO 39
#define PIN_TOUCH_CS 33
#define PIN_TOUCH_IRQ 36
#define PIN_LIGHT_SENSOR 34
#define PIN_BOOT_BUTTON 0
#define PIN_LED_R 4
#define PIN_LED_G 16
#define PIN_LED_B 17

// ---- Backlight / light sensor -----------------------------------------------
#ifndef LIGHT_SENSOR_INVERTED
#define LIGHT_SENSOR_INVERTED 0  // 0: reading rises as the room gets darker
#endif
#ifndef LIGHT_RAW_DARK
#define LIGHT_RAW_DARK 400  // raw ADC reading treated as "fully dark"
#endif
#ifndef BACKLIGHT_MIN_DEFAULT
#define BACKLIGHT_MIN_DEFAULT 12
#endif
#ifndef BACKLIGHT_MAX_DEFAULT
#define BACKLIGHT_MAX_DEFAULT 200
#endif

// ---- Behavior ---------------------------------------------------------------
#define POLL_MS 15000UL
#define BACKOFF_MS 60000UL
#define FAIL_STALE_MS 60000UL
#define HTTP_TIMEOUT_MS 5000
#define WDT_TIMEOUT_MS 30000
#define BOOT_HOLD_MS 1500
#define PORTAL_TIMEOUT_S 600
#define SETUP_AP_SSID "DeskDashboard-Setup"
#define OTA_HOSTNAME "desk-dashboard"
