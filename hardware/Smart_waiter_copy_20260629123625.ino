#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
#include <time.h>

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ---------- Wi-Fi credentials ----------
const char* ssid     = "iPhone";
const char* password = "2025.....";

// ---------- API server ----------
const char* apiServerIP   = "172.20.10.2";   // computer's actual local IP
const int   apiServerPort = 5001;

// ---------- Tables ----------
const int NUM_TABLES = 3;

struct Table {
  const char*   id;                // "table_1"
  int           requestPin;
  int           confirmPin;
  bool          lastRequestState;
  bool          lastConfirmState;
  bool          requestActive;
  unsigned long lastRequestPress;  // for non-blocking debounce
  unsigned long lastConfirmPress;
  unsigned long windowStart;       // start of the 2-minute counting window
  int           requestCount;
};

// id          reqPin confPin  lastReq lastConf active  rPress cPress winStart count
Table tables[NUM_TABLES] = {
  { "table_1",  4,    15,      HIGH,   HIGH,    false,  0,     0,     0,       0 },
  { "table_2",  2,    14,      HIGH,   HIGH,    false,  0,     0,     0,       0 },
  { "table_3",  13,   27,      HIGH,   HIGH,    false,  0,     0,     0,       0 }
};

// ---------- Timing ----------
const unsigned long DEBOUNCE_MS = 250;            // ignore repeat presses within this window
const unsigned long DISPLAY_DURATION = 10000;    // how long a message stays before default screen
const unsigned long WINDOW_DURATION = 120000;    // 2 minutes
const int MAX_REQUESTS = 10;
const int HTTP_TIMEOUT_MS = 2000;                // faster request timeout to avoid long waits
const unsigned long NTP_UPDATE_INTERVAL = 30000; // update NTP time only every 30 seconds

unsigned long displayTimeout = 0;  // one shared timer for returning to the default screen
unsigned long lastNTPUpdate = 0;   // track last NTP update time
unsigned long lastDisplayTime = 0; // cache the last displayed default screen

// ---------- NTP ----------
WiFiUDP   ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", 0, 60000);  // offset is set in setup() (Rwanda UTC+2)

// ============================================================
//                        Helpers
// ============================================================
String two(int v) {
  return (v < 10) ? "0" + String(v) : String(v);
}

String iso8601FromEpoch(unsigned long epoch) {
  if (epoch < 946684800 || epoch > 4294967295) return "Invalid Time";  // Jan 1, 2000
  time_t rawtime = (time_t)epoch;
  struct tm* ptm = gmtime(&rawtime);
  if (ptm == NULL) return "Invalid Time";
  int y  = ptm->tm_year + 1900;
  int m  = ptm->tm_mon + 1;
  int d  = ptm->tm_mday;
  int hh = ptm->tm_hour;
  int mm = ptm->tm_min;
  int ss = ptm->tm_sec;
  return String(y) + "-" + two(m) + "-" + two(d) + " " +
         two(hh) + ":" + two(mm) + ":" + two(ss);
}

// Calls the API server (logs to Firebase /requests AND sends Telegram)
bool callAPIServer(String tableId, String eventType) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected - cannot call API");
    return false;
  }

  Serial.println("WiFi OK, local IP: " + WiFi.localIP().toString());

  WiFiClient client;
  HTTPClient http;

  String url = "http://" + String(apiServerIP) + ":" + String(apiServerPort) + "/arduino_button";
  Serial.println("URL: " + url);
  http.begin(client, url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(HTTP_TIMEOUT_MS);

  String payload = "{\"table_id\":\"" + tableId + "\",\"event_type\":\"" + eventType + "\"}";
  Serial.println("Calling API: " + payload);

  int code = http.POST(payload);
  bool ok = false;
  if (code > 0) {
    Serial.println("API Response (" + String(code) + "): " + http.getString());
    ok = true;
  } else {
    Serial.println("API call failed (" + String(code) + ")");
    if (code == -1) Serial.println("  -> Could not connect to server");
    if (code == -2) Serial.println("  -> Connection refused or timed out");
    if (code == -11) Serial.println("  -> DNS/connection failed or server unreachable");
  }
  http.end();
  return ok;
}

void logEvent(String table, String type, unsigned long epoch) {
  String isoTime = iso8601FromEpoch(epoch);
  if (isoTime == "Invalid Time") {
    Serial.println("Failed to log for " + table + ": Invalid NTP time");
    return;
  }
  Serial.println("Logging " + type + " for " + table + " at " + isoTime);
  bool success = callAPIServer(table, type);
  Serial.println(success ? "API ok - Firebase logged and Telegram sent"
                         : "API failed - check server connection");
}

// ============================================================
//                        Screen
// ============================================================
void showDefaultScreen() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("PRESS BUTTONS:");
  lcd.setCursor(0, 1);
  lcd.print("T1:W T2:W T3:W");
}

void showMessage(const String& line1, const String& line2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
  displayTimeout = millis() + DISPLAY_DURATION;  // auto-return to default after the duration
}

// ============================================================
//             One table = request + confirm logic
// ============================================================
void handleTable(int i, unsigned long epoch, const String& currentTime) {
  Table& t = tables[i];
  int n = i + 1;  // table number for display/serial

  bool reqState  = digitalRead(t.requestPin);
  bool confState = digitalRead(t.confirmPin);

  // ----- Client request (falling edge + debounce) -----
  if (reqState == LOW && t.lastRequestState == HIGH &&
      millis() - t.lastRequestPress > DEBOUNCE_MS) {
    t.lastRequestPress = millis();

    if (currentTime == "Invalid Time") {
      Serial.println("Table " + String(n) + " Request: Invalid NTP time");
    } else {
      Serial.println("Table " + String(n) + " Request at: " + currentTime);

      // Reset the counter if we are outside the 2-minute window
      if (t.requestCount == 0 || (millis() - t.windowStart > WINDOW_DURATION)) {
        t.requestCount = 0;
        t.windowStart  = millis();
      }
      if (t.requestCount < MAX_REQUESTS) {
        t.requestCount++;
        logEvent(t.id, "requested", epoch);
      }
      t.requestActive = true;
    }
    showMessage("T" + String(n) + " REQUEST SENT", "TELEGRAM SENT!");
  }

  // ----- Waiter confirm (falling edge + debounce) -----
  if (confState == LOW && t.lastConfirmState == HIGH && t.requestActive &&
      millis() - t.lastConfirmPress > DEBOUNCE_MS) {
    t.lastConfirmPress = millis();

    if (currentTime == "Invalid Time") {
      Serial.println("Table " + String(n) + " Confirm: Invalid NTP time");
    } else {
      Serial.println("Table " + String(n) + " Confirm at: " + currentTime);
      logEvent(t.id, "served", epoch);
      t.requestCount  = 0;
      t.requestActive = false;
    }
    showMessage("T" + String(n) + " THANK YOU", "ENJOY THE MEAL");
  }

  t.lastRequestState = reqState;
  t.lastConfirmState = confState;
}

// ============================================================
//                         Setup
// ============================================================
void setup() {
  Serial.begin(115200);

  Wire.begin(21, 22);

  for (int i = 0; i < NUM_TABLES; i++) {
    pinMode(tables[i].requestPin, INPUT_PULLUP);
    pinMode(tables[i].confirmPin, INPUT_PULLUP);
  }

  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("  RTSD SYSTEM  ");
  lcd.setCursor(0, 1);
  lcd.print(" MONITOR SYSTEM");
  delay(2000);            // splash screen (was 5000)
  lcd.clear();

  // Connect Wi-Fi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  int wifiAttempts = 0;
  while (WiFi.status() != WL_CONNECTED && wifiAttempts < 20) {
    delay(250);
    if (wifiAttempts % 2 == 0) {  // Update LCD every 2 attempts, not every attempt
      lcd.setCursor(0, 0);
      lcd.print("CONNECT TO WiFi");
      lcd.setCursor((wifiAttempts / 2) % 16, 1);
      lcd.print(".");
    }
    Serial.print(".");
    wifiAttempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nConnected to WiFi");
    Serial.println("WiFi name (SSID): " + WiFi.SSID());
    Serial.println("ESP32 IP address: " + WiFi.localIP().toString());
    Serial.println("API Server:       " + String(apiServerIP) + ":" + String(apiServerPort));

    // Show the network info on the LCD so it can be read without a computer
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(WiFi.SSID().substring(0, 16));     // WiFi name (top line)
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP().toString());        // ESP32's own IP (bottom line)
    delay(5000);                                  // hold 5s so you can read it
  } else {
    Serial.println("\nFailed to connect to WiFi");
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi FAILED");
    delay(3000);
  }

  // Init NTP (Rwanda local time, UTC+2)
  timeClient.begin();
  timeClient.setTimeOffset(7200);  // Rwanda UTC+2  (2 * 3600 = 7200 seconds)

  // Try a few times so we don't continue with an unsynced clock
  bool ntpOk = false;
  for (int i = 0; i < 5; i++) {
    if (timeClient.forceUpdate()) { ntpOk = true; break; }
    Serial.println("NTP retry " + String(i + 1) + "...");
    delay(1000);
  }
  if (ntpOk) {
    Serial.println("NTP synced. Time: " + iso8601FromEpoch(timeClient.getEpochTime()));
  } else {
    Serial.println("NTP initialization failed");
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("NTP FAILED");
    delay(3000);
  }

  showDefaultScreen();
}

// ============================================================
//                          Loop
// ============================================================
void loop() {
  unsigned long now = millis();

  // Update NTP time only every 30 seconds, not every loop iteration
  if (now - lastNTPUpdate > NTP_UPDATE_INTERVAL) {
    timeClient.update();
    lastNTPUpdate = now;
  }

  unsigned long epoch = timeClient.getEpochTime();
  String currentTime  = iso8601FromEpoch(epoch);

  for (int i = 0; i < NUM_TABLES; i++) {
    handleTable(i, epoch, currentTime);
  }

  // Return to the default screen once a message has been shown long enough
  if (displayTimeout > 0 && now > displayTimeout) {
    displayTimeout = 0;
    showDefaultScreen();
    lastDisplayTime = now;
  }

  delay(10);  // small loop delay - responsive button handling
}