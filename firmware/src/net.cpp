// SPDX-License-Identifier: GPL-3.0-or-later
// Wi-Fi provisioning and reconnect, the background fetch task, and OTA.
#include "net.h"

#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <esp_random.h>
#include <esp_task_wdt.h>

#include "config.h"
#include "model.h"
#include "settings.h"
#include "ui.h"

// Mozilla root CA bundle that ships with the ESP-IDF libraries in the core.
extern const uint8_t ca_bundle_start[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t ca_bundle_end[] asm("_binary_x509_crt_bundle_end");

namespace {

volatile bool otaRunning = false;
bool otaStarted = false;
uint32_t nextWifiAttemptMs = 0;
uint32_t wifiBackoffMs = 2000;

String randomPassword() {
  static const char alphabet[] = "abcdefghjkmnpqrstuvwxyz23456789";
  String out;
  for (int i = 0; i < 10; i++) out += alphabet[esp_random() % (sizeof(alphabet) - 1)];
  return out;
}

String viewName(ViewMode v) {
  switch (v) {
    case ViewMode::Portfolio:
      return "portfolio";
    case ViewMode::Server:
      return "server";
    default:
      return "both";
  }
}

ViewMode parseView(String s) {
  s.trim();
  s.toLowerCase();
  if (s == "portfolio") return ViewMode::Portfolio;
  if (s == "server") return ViewMode::Server;
  return ViewMode::Both;
}

// --- fetching ---------------------------------------------------------------

void markFailure(int code) {
  DashState s = model::snapshot();
  if (s.failSinceMs != 0 && s.lastHttp == code) return;  // nothing new to show
  if (s.failSinceMs == 0) s.failSinceMs = millis() | 1;
  s.lastHttp = code;
  if (code == 401) s.have = false;  // like the web page: drop data on a rejected token
  model::update(s);
}

bool fetchOnce(NetworkClientSecure& tls, WiFiClient& plain) {
  const String url = settings.dashboardUrl();
  WiFiClient* client = nullptr;
  if (url.startsWith("https://")) {
    client = &tls;
  } else if (url.startsWith("http://")) {
    client = &plain;  // only for an explicit http:// LAN address
  } else {
    markFailure(-2);
    return false;
  }

  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setReuse(false);
  if (!http.begin(*client, url)) {
    markFailure(-1);
    return false;
  }
  http.addHeader("Authorization", "Bearer " + settings.token);
  const int code = http.GET();
  if (code != 200) {
    http.end();
    markFailure(code);
    return false;
  }
  const String body = http.getString();
  http.end();

  DashState next = model::snapshot();
  if (!model::parse(body, next)) {
    markFailure(-3);
    return false;
  }
  next.have = true;
  next.okAtMs = millis();
  next.failSinceMs = 0;
  next.lastHttp = 200;
  model::update(next);
  return true;
}

void fetchTask(void*) {
  esp_task_wdt_add(nullptr);
  NetworkClientSecure tls;
  tls.setCACertBundle(ca_bundle_start, ca_bundle_end - ca_bundle_start);
  tls.setHandshakeTimeout(HTTP_TIMEOUT_MS / 1000);
  tls.setTimeout(HTTP_TIMEOUT_MS / 1000);
  WiFiClient plain;
  plain.setTimeout(HTTP_TIMEOUT_MS / 1000);

  for (;;) {
    esp_task_wdt_reset();
    uint32_t waitMs = POLL_MS;
    if (otaRunning) {
      waitMs = 1000;
    } else if (WiFi.status() != WL_CONNECTED) {
      markFailure(-1);
      waitMs = 2000;
    } else if (!fetchOnce(tls, plain)) {
      waitMs = BACKOFF_MS;
    }
    for (uint32_t waited = 0; waited < waitMs; waited += 500) {
      esp_task_wdt_reset();
      vTaskDelay(pdMS_TO_TICKS(500));
    }
  }
}

// --- OTA --------------------------------------------------------------------

void startOta() {
  if (otaStarted || settings.otaPassword.isEmpty()) return;  // no password: OTA off
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(settings.otaPassword.c_str());
  ArduinoOTA.onStart([] {
    otaRunning = true;
    esp_task_wdt_delete(nullptr);  // the upload runs inside loop()
    ui::setBlocking(true);
    ui::message("Updating", "Receiving new firmware", "Don't unplug");
  });
  ArduinoOTA.onError([](ota_error_t) { ESP.restart(); });
  ArduinoOTA.begin();
  otaStarted = true;
}

}  // namespace

namespace net {

void provision(bool force) {
  WiFi.mode(WIFI_STA);
  const String apPass = randomPassword();

  char rotateBuf[6], blMinBuf[4], blMaxBuf[4];
  snprintf(rotateBuf, sizeof(rotateBuf), "%u", settings.rotateS);
  snprintf(blMinBuf, sizeof(blMinBuf), "%u", settings.blMin);
  snprintf(blMaxBuf, sizeof(blMaxBuf), "%u", settings.blMax);
  const String view = viewName(settings.view);

  WiFiManager wm;
  WiFiManagerParameter pUrl("url", "Dashboard URL, e.g. https://desk-dashboard.example.ts.net",
                            settings.serverUrl.c_str(), 128);
  WiFiManagerParameter pToken("token", "Dashboard token (blank keeps the saved one)", "", 96,
                              "type='password' autocomplete='off'");
  WiFiManagerParameter pOta("ota", "OTA password (blank keeps the saved one; none disables OTA)",
                            "", 64, "type='password' autocomplete='off'");
  WiFiManagerParameter pView("view", "View: both, portfolio or server", view.c_str(), 10);
  WiFiManagerParameter pRotate("rotate", "Rotate every N seconds", rotateBuf, 5);
  WiFiManagerParameter pPct("pct", "Percent only (1 = yes, 0 = no)", settings.pctOnly ? "1" : "0",
                            2);
  WiFiManagerParameter pBlMin("blmin", "Backlight minimum (0-255)", blMinBuf, 4);
  WiFiManagerParameter pBlMax("blmax", "Backlight maximum (0-255)", blMaxBuf, 4);
  for (WiFiManagerParameter* p :
       {&pUrl, &pToken, &pOta, &pView, &pRotate, &pPct, &pBlMin, &pBlMax}) {
    wm.addParameter(p);
  }

  auto saveParams = [&] {
    settings.serverUrl = pUrl.getValue();
    settings.serverUrl.trim();
    if (strlen(pToken.getValue()) > 0) settings.token = pToken.getValue();
    if (strlen(pOta.getValue()) > 0) settings.otaPassword = pOta.getValue();
    settings.view = parseView(pView.getValue());
    settings.rotateS = constrain(atoi(pRotate.getValue()), 3, 3600);
    settings.pctOnly = atoi(pPct.getValue()) == 1;
    settings.blMin = constrain(atoi(pBlMin.getValue()), 0, 255);
    settings.blMax = constrain(atoi(pBlMax.getValue()), settings.blMin, 255);
    settings.save();
  };
  wm.setSaveParamsCallback(saveParams);
  wm.setSaveConfigCallback(saveParams);
  wm.setBreakAfterConfig(true);
  wm.setConfigPortalTimeout(PORTAL_TIMEOUT_S);
  wm.setConnectTimeout(20);
  wm.setAPCallback([&](WiFiManager*) {
    ui::message("Setup", "Join Wi-Fi \"" SETUP_AP_SSID "\"",
                "password " + apPass + "  then open 192.168.4.1");
  });

  ui::setBlocking(true);
  ui::message("Wi-Fi", "Connecting...");
  bool ok = force ? wm.startConfigPortal(SETUP_AP_SSID, apPass.c_str())
                  : wm.autoConnect(SETUP_AP_SSID, apPass.c_str());
  while (ok && !settings.complete()) {
    ok = wm.startConfigPortal(SETUP_AP_SSID, apPass.c_str());
  }
  if (!ok || WiFi.status() != WL_CONNECTED) {
    ui::message("Setup", "Timed out", "Restarting...");
    delay(2000);
    ESP.restart();
  }
  WiFi.setAutoReconnect(false);  // loop() reconnects with backoff instead
  ui::setBlocking(false);
}

void startFetcher() { xTaskCreatePinnedToCore(fetchTask, "fetch", 12288, nullptr, 1, nullptr, 0); }

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiBackoffMs = 2000;
    startOta();
    if (otaStarted) ArduinoOTA.handle();
    return;
  }
  if (static_cast<int32_t>(millis() - nextWifiAttemptMs) >= 0) {
    WiFi.disconnect();
    WiFi.begin();  // stored credentials
    nextWifiAttemptMs = millis() + wifiBackoffMs;
    wifiBackoffMs = min<uint32_t>(wifiBackoffMs * 2, 60000);
  }
}

bool wifiUp() { return WiFi.status() == WL_CONNECTED; }

bool otaActive() { return otaRunning; }

}  // namespace net
