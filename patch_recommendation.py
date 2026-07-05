from pathlib import Path

path = Path('pages/recommendation.html')
text = path.read_text(encoding='utf-8')
old = '''  <script>
    const connectionDot = document.getElementById("connectionDot");
    const connectionText = document.getElementById("connectionText");
    const lastSync = document.getElementById("lastSync");
    const refreshButton = document.getElementById("refreshButton");

    function updateLastSync() {
      lastSync.textContent = "Last sync: " + new Date().toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      });
    }

    function setConnection(state, message) {
      const normalized = state || "reconnecting";
      connectionDot.className = "dot " + normalized;
      connectionText.textContent = message;
      if (normalized === "connected") updateLastSync();
    }

    setConnection("connected", "Firebase connected");

    refreshButton.addEventListener("click", () => {
      window.location.reload();
    });

    updateLastSync();
  </script>'''
new = '''  <script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
  <script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-database-compat.js"></script>
  <script>
    const firebaseConfig = {
      apiKey: "AIzaSyDGEmefDNithsiaIjsTMSJC4C7E7u_ad_0",
      authDomain: "smartwaiter-c9a2e.firebaseapp.com",
      databaseURL: "https://smartwaiter-c9a2e-default-rtdb.firebaseio.com",
      projectId: "smartwaiter-c9a2e",
      storageBucket: "smartwaiter-c9a2e.firebasestorage.app",
      messagingSenderId: "405623064041",
      appId: "1:405623064041:web:c69fe02b0fe1fc1efb3778"
    };

    const connectionDot = document.getElementById("connectionDot");
    const connectionText = document.getElementById("connectionText");
    const lastSync = document.getElementById("lastSync");
    const refreshButton = document.getElementById("refreshButton");
    const recommendationList = document.getElementById("recommendationList");

    const TABLE_LABELS = {
      table_1: "Table 1",
      table_2: "Table 2",
      table_3: "Table 3",
      table_4: "Table 4",
      table_5: "Table 5"
    };

    const DEMAND_LABELS = {
      recurring: {
        title: "Recurring demand",
        icon: "🔥",
        badge: "High demand"
      },
      occasional: {
        title: "Occasional demand",
        icon: "⚡",
        badge: "Medium demand"
      },
      low: {
        title: "Low demand",
        icon: "🌿",
        badge: "Low demand"
      }
    };

    function updateLastSync() {
      lastSync.textContent = "Last sync: " + new Date().toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      });
    }

    function setConnection(state, message) {
      const normalized = state || "reconnecting";
      connectionDot.className = "dot " + normalized;
      connectionText.textContent = message;
      if (normalized === "connected") updateLastSync();
    }

    function normalizeTableName(tableId) {
      return TABLE_LABELS[tableId] || tableId.replace(/_/g, " ").replace(/\b\w/g, (chr) => chr.toUpperCase());
    }

    function classifyTableDemand(stats) {
      if (stats.totalRequests >= 8 || stats.days.size >= 4 || stats.recentHoursPeak >= 3) {
        return "recurring";
      }
      if (stats.totalRequests >= 3 || stats.days.size >= 2 || stats.recent24 >= 2) {
        return "occasional";
      }
      return "low";
    }

    function describePattern(stats, tableName) {
      const lines = [];
      if (stats.demandType === "recurring") {
        if (stats.topHour >= 11 && stats.topHour < 15) {
          lines.push(`${tableName} usually needs attention around lunch.`);
        } else if (stats.topHour >= 17 && stats.topHour < 21) {
          lines.push(`${tableName} often shows repeat demand during dinner.`);
        } else {
          lines.push(`${tableName} frequently requests service at ${stats.topHour}:00.`);
        }
      } else if (stats.demandType === "occasional") {
        lines.push(`${tableName} has occasional demand and may need staffing support.`);
      } else {
        lines.push(`${tableName} typically has low demand and stays quiet after service.`);
      }

      if (stats.lastRequestAgeHours > 24 && stats.demandType === "low") {
        lines.push(`${tableName} rarely requests again after being served.`);
      }

      if (stats.topDay && stats.demandType !== "low") {
        lines.push(`${tableName} is most active on ${stats.topDay}.`);
      }

      return lines.join(" ");
    }

    function buildPatternCard(tableName, stats) {
      const model = DEMAND_LABELS[stats.demandType];
      const card = document.createElement("article");
      card.className = `recommendation-card ${stats.demandType}`;
      card.innerHTML = `
        <div class="rec-icon">${model.icon}</div>
        <div class="rec-content">
          <div class="rec-title">${tableName} — ${model.title}</div>
          <div class="rec-description">${describePattern(stats, tableName)}</div>
          <div class="rec-badge">${model.badge}</div>
        </div>
      `;
      return card;
    }

    function computeDemandPatterns(events) {
      const now = new Date();
      const statsByTable = {};

      events.forEach((event) => {
        if (!event || event.event_type !== "requested") return;
        const tableId = event.table_id;
        const timestamp = new Date(event.timestamp || event.iso_time || event.time || event.created_at);
        if (Number.isNaN(timestamp.getTime())) return;

        const hour = timestamp.getHours();
        const weekday = timestamp.toLocaleDateString(undefined, { weekday: "long" });
        const ageHours = (now - timestamp) / 36e5;

        if (!statsByTable[tableId]) {
          statsByTable[tableId] = {
            totalRequests: 0,
            recent24: 0,
            days: new Set(),
            hourCounts: {},
            dayCounts: {},
            recentHoursPeak: 0,
            lastRequestAgeHours: 0,
            topHour: null,
            topDay: null
          };
        }

        const stats = statsByTable[tableId];
        stats.totalRequests += 1;
        stats.days.add(weekday);
        stats.hourCounts[hour] = (stats.hourCounts[hour] || 0) + 1;
        stats.dayCounts[weekday] = (stats.dayCounts[weekday] || 0) + 1;

        if (ageHours <= 24) stats.recent24 += 1;
        stats.recentHoursPeak = Math.max(stats.recentHoursPeak, stats.hourCounts[hour]);
        stats.lastRequestAgeHours = stats.lastRequestAgeHours === 0 ? ageHours : Math.min(stats.lastRequestAgeHours, ageHours);
      });

      Object.values(statsByTable).forEach((stats) => {
        const topHour = Object.entries(stats.hourCounts).sort((a, b) => b[1] - a[1])[0];
        const topDay = Object.entries(stats.dayCounts).sort((a, b) => b[1] - a[1])[0];
        stats.topHour = topHour ? Number(topHour[0]) : null;
        stats.topDay = topDay ? topDay[0] : null;
        stats.demandType = classifyTableDemand(stats);
      });

      return statsByTable;
    }

    function renderDemandPatterns(events) {
      const statsByTable = computeDemandPatterns(events);
      recommendationList.innerHTML = "";

      if (Object.keys(statsByTable).length === 0) {
        recommendationList.innerHTML = `
          <article class="recommendation-card low">
            <div class="rec-icon">🟡</div>
            <div class="rec-content">
              <div class="rec-title">Waiting for demand data</div>
              <div class="rec-description">No requested events were found in Firebase yet. Table demand profiles will appear once the system receives requests.</div>
              <div class="rec-badge">No data</div>
            </div>
          </article>
        `;
        return;
      }

      Object.keys(statsByTable).sort().forEach((tableId) => {
        const tableName = normalizeTableName(tableId);
        recommendationList.appendChild(buildPatternCard(tableName, statsByTable[tableId]));
      });
    }

    function loadTableDemandPatterns() {
      if (!firebase.apps.length) {
        firebase.initializeApp(firebaseConfig);
      }
      const db = firebase.database();
      const requestsRef = db.ref("requests");

      requestsRef.once("value")
        .then((snapshot) => {
          const data = snapshot.val() || {};
          const events = Object.values(data);
          renderDemandPatterns(events);
          setConnection("connected", "Firebase connected");
        })
        .catch((error) => {
          recommendationList.innerHTML = `
            <article class="recommendation-card low">
              <div class="rec-icon">⚠️</div>
              <div class="rec-content">
                <div class="rec-title">Unable to load demand patterns</div>
                <div class="rec-description">Firebase error: ${error.message}</div>
                <div class="rec-badge">Error</div>
              </div>
            </article>
          `;
          setConnection("error", "Firebase error");
        });
    }

    refreshButton.addEventListener("click", () => {
      loadTableDemandPatterns();
    });

    setConnection("reconnecting", "Connecting to Firebase...");
    loadTableDemandPatterns();
  </script>
</body>
</html>
'''
if old not in text:
    raise SystemExit('old block not found')
path.write_text(text.replace(old, new), encoding='utf-8')
print('updated')
