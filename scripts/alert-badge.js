// Shared alert badge handler for all pages
const alertBadgeConfig = {
  firebaseConfig: {
    apiKey: "AIzaSyDGEmefDNithsiaIjsTMSJC4C7E7u_ad_0",
    authDomain: "smartwaiter-c9a2e.firebaseapp.com",
    databaseURL: "https://smartwaiter-c9a2e-default-rtdb.firebaseio.com",
    projectId: "smartwaiter-c9a2e",
    storageBucket: "smartwaiter-c9a2e.appspot.com",
    messagingSenderId: "405623064041",
    appId: "1:405623064041:web:c69fe02b0fe1fc1efb3778"
  },
  baseAlertMinutes: 2,
  highAlertMinutes: 5,
  repeatedRequestThreshold: 3,
  repeatedWindowMinutes: 2
};

function initializeAlertBadge() {
  const alertsNavBadge = document.getElementById("alertsNavBadge");
  if (!alertsNavBadge) return;

  // Start with badge hidden and empty
  alertsNavBadge.textContent = "";
  alertsNavBadge.classList.remove("visible");

  let connectionEstablished = false;

  try {
    // Initialize Firebase
    if (!firebase.apps.length) {
      firebase.initializeApp(alertBadgeConfig.firebaseConfig);
    }
    
    const db = firebase.database();
    
    // Real-time listener for alert count - load cached data first
    const ref = db.ref("requests");
    ref.limitToLast(100).once("value", (snapshot) => {
      if (!connectionEstablished) {
        connectionEstablished = true;
        const alerts = calculateAlerts(snapshot.val());
        updateBadgeDisplay(alertsNavBadge, alerts.length);
      }
    }).catch(() => {
      // Silent fail - will update on live connection
    });
    
    // Listen for live updates
    ref.on("value", (snapshot) => {
      if (!connectionEstablished) {
        connectionEstablished = true;
      }
      const alerts = calculateAlerts(snapshot.val());
      updateBadgeDisplay(alertsNavBadge, alerts.length);
    });
  } catch (error) {
    console.warn("Alert badge initialization failed:", error);
  }
}

function calculateAlerts(data) {
  if (!data || typeof data !== "object") return [];
  
  const events = Object.entries(data).map(([key, value]) => ({
    id: key,
    tableId: value.table_id || value.tableId || value.table || "unknown",
    eventType: normalizeEventType(value.event_type || value.eventType || value.type || "unknown"),
    timestamp: value.timestamp || value.iso_time || value.time || key
  }));

  const byTable = {};
  const sortedEvents = [...events].sort((a, b) => {
    const aTime = parseTimestamp(a.timestamp)?.getTime() || 0;
    const bTime = parseTimestamp(b.timestamp)?.getTime() || 0;
    return aTime - bTime;
  });

  sortedEvents.forEach((event) => {
    if (!event.tableId || event.tableId === "unknown") return;
    if (!byTable[event.tableId]) {
      byTable[event.tableId] = [];
    }
    byTable[event.tableId].push(event);
  });

  const generated = [];
  Object.entries(byTable).forEach(([tableId, tableEvents]) => {
    const pendingRequests = [];
    tableEvents.forEach((event) => {
      if (event.eventType === "requested") {
        pendingRequests.push(event);
      } else if (event.eventType === "served" && pendingRequests.length) {
        pendingRequests.pop();
      }
    });

    if (!pendingRequests.length) return;

    const latestRequest = pendingRequests[pendingRequests.length - 1];
    const requestTime = parseTimestamp(latestRequest.timestamp);
    const ageMinutes = requestTime ? (Date.now() - requestTime.getTime()) / 60000 : 0;

    if (ageMinutes >= alertBadgeConfig.baseAlertMinutes) {
      generated.push({ level: ageMinutes >= alertBadgeConfig.highAlertMinutes ? "critical" : "warning" });
    }

    const requestWindow = tableEvents.filter((event) => {
      const time = parseTimestamp(event.timestamp);
      if (!time) return false;
      return event.eventType === "requested" && (Date.now() - time.getTime()) <= alertBadgeConfig.repeatedWindowMinutes * 60000;
    });

    if (requestWindow.length >= alertBadgeConfig.repeatedRequestThreshold) {
      generated.push({ level: "warning" });
    }
  });

  return generated;
}

function parseTimestamp(value) {
  if (!value) return null;
  if (typeof value === "number") {
    const milliseconds = value < 1000000000000 ? value * 1000 : value;
    const date = new Date(milliseconds);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function normalizeEventType(value) {
  const text = String(value || "unknown").toLowerCase();
  if (text === "request" || text === "requested" || text === "waiting" || text === "service_requested") return "requested";
  if (text === "served" || text === "complete" || text === "completed") return "served";
  return text;
}

function updateBadgeDisplay(badge, count) {
  badge.textContent = count > 9 ? "9+" : String(count);
  badge.classList.toggle("visible", count > 0);
}

// Initialize when Firebase scripts are loaded
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeAlertBadge);
} else {
  // Check if Firebase is available
  if (typeof firebase !== "undefined") {
    initializeAlertBadge();
  } else {
    // Wait for Firebase to load
    const checkFirebase = setInterval(() => {
      if (typeof firebase !== "undefined") {
        clearInterval(checkFirebase);
        initializeAlertBadge();
      }
    }, 100);
  }
}
