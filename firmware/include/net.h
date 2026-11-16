// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

namespace net {
// Captive-portal provisioning; returns once Wi-Fi is connected (or restarts).
void provision(bool force);
// Starts the background fetch task (never blocks the UI).
void startFetcher();
// Called from loop(): Wi-Fi reconnect with backoff, OTA.
void loop();
bool wifiUp();
bool otaActive();
}  // namespace net
