const tankGrid = document.querySelector("#tank-grid");
const controlGrid = document.querySelector("#control-grid");
const title = document.querySelector("#dashboard-title");
const clock = document.querySelector("#top-clock");
const insideTemp = document.querySelector("#inside-temp");
const outsideTemp = document.querySelector("#outside-temp");
const batteryFill = document.querySelector("#battery-fill");
const batteryPercent = document.querySelector("#battery-percent");
const aferiyCard = document.querySelector("#aferiy-card");
const aferiyLabel = document.querySelector("#aferiy-label");
const aferiyFill = document.querySelector("#aferiy-fill");
const aferiyPercent = document.querySelector("#aferiy-percent");
const aferiyFlow = document.querySelector("#aferiy-flow");
const aferiyState = document.querySelector("#aferiy-state");
const connectionStatus = document.querySelector("#connection-status");
const dashboardView = document.querySelector("#dashboard-view");
const temperatureView = document.querySelector("#temperature-view");
const temperatureChart = document.querySelector("#temperature-chart");
const temperatureEmpty = document.querySelector("#temperature-empty");
const temperatureHistoryMeta = document.querySelector("#temperature-history-meta");
const temperatureChartTitle = document.querySelector("#temperature-chart-title");
const temperatureLatestInside = document.querySelector("#temperature-latest-inside");
const temperatureLatestOutside = document.querySelector("#temperature-latest-outside");
const temperatureLatestHumidity = document.querySelector("#temperature-latest-humidity");
const temperatureRangeButtons = document.querySelectorAll("[data-temperature-range]");
const settingsView = document.querySelector("#settings-view");
const settingsGrid = document.querySelector("#settings-grid");
const settingsBackButton = document.querySelector("#settings-back-button");
const navItems = document.querySelectorAll(".nav-item[data-view-target]");

// Screensaver Elements
const screensaverOverlay = document.querySelector("#screensaver-overlay");
const screensaverTrigger = document.querySelector("#screensaver-trigger");
const screensaverCanvas = document.querySelector("#screensaver-canvas");
const ssClock = document.querySelector("#ss-clock");
const ssDate = document.querySelector("#ss-date");
const ssBattery = document.querySelector("#ss-battery");
const ssFresh = document.querySelector("#ss-fresh");
const ssGrey = document.querySelector("#ss-grey");
const ssBatteryRing = document.querySelector("#ss-battery-ring");
const ssFreshRing = document.querySelector("#ss-fresh-ring");
const ssGreyRing = document.querySelector("#ss-grey-ring");
const ssTempIn = document.querySelector("#ss-temp-in");
const ssTempOut = document.querySelector("#ss-temp-out");
const ssPowerFlow = document.querySelector("#ss-power-flow");
const ssTerminalLog = document.querySelector("#ss-terminal-log");

let lastData = null;
let pendingControl = null;
let activeView = "dashboard";
let settingsData = null;
let settingsError = null;
let settingsRequested = false;
let temperatureHistory = null;
let temperatureHistoryError = null;
let temperatureHistoryLoading = false;
let temperatureHistoryRange = "day";
let statusFetchInFlight = false;

const STATUS_REFRESH_MS = 10000;
const STATUS_TIMEOUT_MS = 25000;

const temperatureRangeTitles = {
  day: "Last 24 Hours",
  week: "Last 7 Days",
  month: "Last 30 Days",
};

const temperatureRangeEndpoints = new Set(Object.keys(temperatureRangeTitles));

// Screensaver States
let screensaverActive = false;
let ssTimeoutPref = localStorage.getItem("ss_timeout") || "60000"; // default 1 min
let ssTimeoutMs = parseInt(ssTimeoutPref, 10);
let idleTimer = null;
let animationFrameId = null;
let terminalInterval = null;
let animTime = 0;
let canvasCtx = null;
let canvasWidth = 0;
let ssActivationTime = 0;
let lastMouseX = null;
let lastMouseY = null;
let canvasHeight = 0;

function icon(name) {
  return `<svg aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
}

function escapeHtml(value) {
  const text = String(value ?? "");
  const replacements = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  };

  return text.replace(/[&<>"']/g, (character) => replacements[character]);
}

function capPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return 0;
  }

  return Math.max(0, Math.min(100, number));
}

function tankReading(tank) {
  const hasPercent = tank.percent !== null
    && tank.percent !== undefined
    && tank.percent !== "";
  const percent = hasPercent ? capPercent(tank.percent) : null;
  const litres = Number(tank.litres);
  const capacity = Number(tank.capacity_litres);
  const isOffline = Boolean(tank.sensor_error || tank.connected === false);
  const litresText = Number.isFinite(litres) ? Math.round(litres) : "--";
  const capacityText = Number.isFinite(capacity) ? Math.round(capacity) : "--";
  const level = percent === null ? 0 : percent;

  return {
    capacityText: isOffline ? "Sensor offline" : `${litresText} / ${capacityText} L`,
    fillOpacity: level === 0 ? "0" : "1",
    isOffline,
    level,
    percentText: percent === null ? "--%" : `${percent}%`,
  };
}

function temp(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--\u00b0C";
  }

  return `${Math.round(number)}\u00b0C`;
}

function tempDetail(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--\u00b0C";
  }

  return `${number.toFixed(1)}\u00b0C`;
}

function watt(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-- W";
  }

  return `${Math.round(number)} W`;
}

function yesNo(value) {
  if (value === true) {
    return "On";
  }

  if (value === false) {
    return "Off";
  }

  return "--";
}

function settingValue(value, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "--";
  }

  return `${value}${suffix}`;
}

function boolConfigured(value) {
  return value ? "Configured" : "Missing";
}

function sourceLabel(value) {
  if (value === "ads1115") {
    return "ADS1115";
  }

  if (value === "tapo") {
    return "Tapo P100";
  }

  if (value === "mqtt") {
    return "BrightEMS MQTT";
  }

  if (value === "ble") {
    return "AFERIY BLE";
  }

  if (value === "switchbot") {
    return "SwitchBot";
  }

  if (value === "switchbot_ble") {
    return "SwitchBot BLE";
  }

  if (value === "static") {
    return "Static";
  }

  return "Local";
}

function hexAddress(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return settingValue(value);
  }

  return `0x${number.toString(16).toUpperCase()}`;
}

function percent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--";
  }

  return `${Math.round(number)}%`;
}

function humidity(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--%";
  }

  return `${Math.round(number)}%`;
}

function settingsPill(text, tone = "neutral") {
  return `<span class="settings-pill settings-pill-${tone}">${escapeHtml(text)}</span>`;
}

function settingRows(rows) {
  return `
    <dl class="settings-list">
      ${rows
        .map((row) => `
          <div class="settings-row">
            <dt>${escapeHtml(row.label)}</dt>
            <dd>${row.html ?? escapeHtml(settingValue(row.value))}</dd>
          </div>
        `)
        .join("")}
    </dl>
  `;
}

function settingsCard({ iconName, title: cardTitle, statusHtml = "", rows = [], bodyHtml = "", className = "" }) {
  return `
    <section class="settings-card ${className}">
      <div class="settings-card-heading">
        <span class="settings-card-icon" aria-hidden="true">${icon(iconName)}</span>
        <h3>${escapeHtml(cardTitle)}</h3>
        ${statusHtml ? `<div class="settings-card-status">${statusHtml}</div>` : ""}
      </div>
      ${rows.length ? settingRows(rows) : ""}
      ${bodyHtml}
    </section>
  `;
}

function controlState(control) {
  if (!control) {
    return {
      text: "--",
      tone: "neutral",
    };
  }

  if (control.connected === false) {
    return {
      text: "OFFLINE",
      tone: "danger",
    };
  }

  if (control.is_on === true) {
    return {
      text: "ON",
      tone: "good",
    };
  }

  if (control.is_on === false) {
    return {
      text: "OFF",
      tone: "neutral",
    };
  }

  return {
    text: "--",
    tone: "neutral",
  };
}

function liveControl(controlId) {
  return (lastData?.controls || []).find((control) => control.id === controlId);
}

function liveTank(tankId) {
  return (lastData?.tanks || []).find((tank) => tank.id === tankId);
}

function renderControlSettings(controls) {
  if (!controls?.length) {
    return `<p class="settings-empty">--</p>`;
  }

  return `
    <div class="settings-module-grid controls-settings-grid">
      ${controls
        .map((control) => {
          const live = liveControl(control.id);
          const state = controlState(live);

          return `
            <article class="settings-module">
              <div class="settings-module-heading">
                <span class="settings-module-icon" aria-hidden="true">${icon(control.icon)}</span>
                <strong>${escapeHtml(control.label)}</strong>
                ${settingsPill(state.text, state.tone)}
              </div>
              ${settingRows([
                { label: "Control ID", value: control.id },
                { label: "Source", value: sourceLabel(control.source) },
              ])}
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderTankSettings(tanks) {
  if (!tanks?.length) {
    return `<p class="settings-empty">--</p>`;
  }

  return `
    <div class="settings-module-grid tank-settings-grid">
      ${tanks
        .map((tank) => {
          const live = liveTank(tank.id);
          const sensor = tank.sensor;
          const isOffline = Boolean(live?.sensor_error || live?.connected === false);
          const percentNumber = Number(live?.percent);
          const litresNumber = Number(live?.litres);
          const currentPercent = !Number.isFinite(percentNumber)
            ? "--"
            : `${capPercent(percentNumber)}%`;
          const currentLitres = !Number.isFinite(litresNumber)
            ? "--"
            : `${Math.round(litresNumber)} L`;
          const status = isOffline
            ? settingsPill("OFFLINE", "danger")
            : settingsPill(tank.source === "ads1115" ? "LIVE" : "STATIC", "good");
          const rows = [
            { label: "Source", value: sourceLabel(tank.source) },
            { label: "Capacity", value: settingValue(tank.capacity_litres, " L") },
            { label: "Current level", value: currentPercent },
            { label: "Current volume", value: currentLitres },
          ];

          if (sensor) {
            rows.push(
              { label: "ADC address", value: hexAddress(sensor.address) },
              { label: "ADC channel", value: sensor.channel },
              { label: "Supply", value: settingValue(sensor.supply_v, " V") },
              { label: "Fixed resistor", value: settingValue(sensor.fixed_ohms, " ohms") },
              { label: "Divider", value: sensor.divider },
              { label: "Empty", value: settingValue(sensor.empty_ohms, " ohms") },
              { label: "Full", value: settingValue(sensor.full_ohms, " ohms") },
            );
          }

          if (live?.sensor_error) {
            rows.push({ label: "Sensor message", value: live.sensor_error });
          }

          return `
            <article class="settings-module" style="--accent: ${escapeHtml(tank.accent || "#29d8ff")}">
              <div class="settings-module-heading">
                <span class="settings-module-icon tank-settings-icon" aria-hidden="true">${icon(tank.icon)}</span>
                <strong>${escapeHtml(tank.label)}</strong>
                ${status}
              </div>
              ${settingRows(rows)}
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderPowerDeviceSettings(devices) {
  if (!devices?.length) {
    return `<p class="settings-empty">--</p>`;
  }

  return `
    <div class="settings-module-grid power-settings-grid">
      ${devices
        .map((device) => {
          const live = (lastData?.power_devices || [])
            .find((item) => item.id === device.id);
          const isOffline = live?.connected === false;
          const isLiveSource = device.source === "mqtt" || device.source === "ble";
          const status = isOffline
            ? settingsPill("OFFLINE", "danger")
            : settingsPill(isLiveSource ? "LIVE" : "STATIC", isLiveSource ? "good" : "neutral");
          const rows = [
            { label: "Model", value: device.model },
            { label: "Source", value: sourceLabel(device.source) },
            { label: "Capacity", value: settingValue(device.capacity_wh, " Wh") },
            { label: "Charge", value: Number.isFinite(Number(live?.percent)) ? `${capPercent(live.percent)}%` : "--" },
            { label: "Input", value: watt(live?.input_w) },
            { label: "Output", value: watt(live?.output_w) },
            { label: "AC output", value: yesNo(live?.ac_output_on) },
            { label: "DC output", value: yesNo(live?.dc_output_on) },
            { label: "USB output", value: yesNo(live?.usb_output_on) },
          ];

          if (device.source === "mqtt" && device.mqtt) {
            rows.push(
              { label: "MQTT host", value: device.mqtt.host },
              { label: "MQTT port", value: device.mqtt.port },
              { label: "Device ID", value: boolConfigured(device.mqtt.device_id_configured) },
              { label: "API token", value: boolConfigured(device.mqtt.api_token_configured) },
              { label: "Telemetry TTL", value: settingValue(device.mqtt.telemetry_ttl_s, " s") },
            );
          }

          if (device.source === "ble" && device.ble) {
            rows.push(
              { label: "BLE address", value: live?.ble_address || (device.ble.address_configured ? "Configured" : "Auto-discover") },
              { label: "BLE name", value: live?.ble_name || device.ble.name_prefixes },
              { label: "BLE RSSI", value: live?.ble_rssi === null || live?.ble_rssi === undefined ? "--" : `${live.ble_rssi} dBm` },
              { label: "BLE scan", value: settingValue(device.ble.scan_seconds, " s") },
              { label: "BLE poll", value: settingValue(device.ble.poll_seconds, " s") },
            );
          }

          if (live?.error) {
            rows.push({ label: "Message", value: live.error });
          }

          return `
            <article class="settings-module">
              <div class="settings-module-heading">
                <span class="settings-module-icon" aria-hidden="true">${icon("power")}</span>
                <strong>${escapeHtml(device.label)}</strong>
                ${status}
              </div>
              ${settingRows(rows)}
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderSettings() {
  if (!settingsGrid) {
    return;
  }

  if (settingsError && !settingsData) {
    settingsGrid.innerHTML = settingsCard({
      iconName: "settings",
      title: "Settings unavailable",
      statusHtml: settingsPill("ERROR", "danger"),
      rows: [{ label: "Message", value: settingsError }],
      className: "settings-card-full",
    });
    return;
  }

  if (!settingsData) {
    settingsGrid.innerHTML = settingsCard({
      iconName: "settings",
      title: "Loading",
      statusHtml: settingsPill("SYNC", "neutral"),
      className: "settings-card-wide",
    });
    return;
  }

  const dashboard = settingsData.dashboard || {};
  const tapo = settingsData.tapo || {};
  const tapoOnline = Boolean(lastData?.tapo?.connected);
  const tapoStatus = tapoOnline
    ? settingsPill("ONLINE", "good")
    : settingsPill("OFFLINE", lastData?.tapo?.error ? "danger" : "neutral");
  const mappedControl = (settingsData.controls || [])
    .find((control) => control.id === tapo.control_id);
  const tapoRows = [
    { label: "Device host", value: tapo.host },
    { label: "Connection", value: tapo.connection },
    { label: "Timeout", value: settingValue(tapo.timeout_s, " s") },
    { label: "Control", value: mappedControl?.label || tapo.control_id },
    { label: "Username", value: boolConfigured(tapo.username_configured) },
    { label: "Password", value: boolConfigured(tapo.password_configured) },
    { label: "Alias", value: lastData?.tapo?.device?.alias },
    { label: "Model", value: lastData?.tapo?.device?.model },
    { label: "MAC", value: lastData?.tapo?.device?.mac },
  ];

  if (lastData?.tapo?.error) {
    tapoRows.push({ label: "Message", value: lastData.tapo.error });
  }

  const battery = settingsData.battery?.percent;
  const batteryText = Number.isFinite(Number(battery))
    ? `${capPercent(battery)}%`
    : "--";
  const liveEnvironment = lastData?.environment || {};
  const switchbot = settingsData.switchbot || {};
  const outdoorSource = switchbot.source || settingsData.environment?.outside_source || "static";
  const isSwitchBotOutdoor = outdoorSource === "switchbot" || outdoorSource === "switchbot_ble";
  const outdoorStatus = liveEnvironment.outside_connected === false
    ? settingsPill("OFFLINE", "danger")
    : settingsPill(isSwitchBotOutdoor ? "LIVE" : "STATIC", isSwitchBotOutdoor ? "good" : "neutral");
  const outdoorRows = [
    { label: "Inside", value: temp(settingsData.environment?.inside_c) },
    { label: "Outside", value: temp(liveEnvironment.outside_c ?? settingsData.environment?.outside_c) },
    { label: "Outdoor source", value: sourceLabel(outdoorSource) },
    { label: "Battery", value: batteryText },
  ];

  if (isSwitchBotOutdoor) {
    outdoorRows.push(
      { label: "Humidity", value: percent(liveEnvironment.outside_humidity) },
      { label: "Sensor battery", value: percent(liveEnvironment.outside_battery_percent) },
      { label: "Device", value: switchbot.device_id_configured ? "Configured" : "Auto-discover" },
    );
    if (outdoorSource === "switchbot") {
      outdoorRows.push(
        { label: "API token", value: boolConfigured(switchbot.token_configured) },
        { label: "API secret", value: boolConfigured(switchbot.secret_configured) },
        { label: "Timeout", value: settingValue(switchbot.timeout_s, " s") },
      );
    } else {
      outdoorRows.push(
        { label: "BLE address", value: switchbot.ble_address_configured ? "Configured" : "Device ID" },
        { label: "BLE scan", value: settingValue(switchbot.ble_scan_seconds, " s") },
      );
    }
  }

  if (liveEnvironment.outside_error) {
    outdoorRows.push({ label: "Message", value: liveEnvironment.outside_error });
  }

  settingsGrid.innerHTML = [
    settingsCard({
      iconName: "settings",
      title: "Dashboard",
      statusHtml: settingsPill("LOCAL", "good"),
      rows: [
        { label: "Title", value: dashboard.title },
        { label: "Bind address", value: dashboard.host },
        { label: "Port", value: dashboard.port },
        { label: "Status refresh", value: "10 s" },
      ],
      className: "settings-card-wide",
    }),
    settingsCard({
      iconName: "battery",
      title: "Telemetry",
      statusHtml: outdoorStatus,
      rows: outdoorRows,
    }),
    settingsCard({
      iconName: "power",
      title: "Power Devices",
      bodyHtml: renderPowerDeviceSettings(settingsData.power_devices || []),
      className: "settings-card-full",
    }),
    settingsCard({
      iconName: "power",
      title: "Tapo Plug",
      statusHtml: tapoStatus,
      rows: tapoRows,
      className: "settings-card-wide",
    }),
    settingsCard({
      iconName: "light",
      title: "Controls",
      bodyHtml: renderControlSettings(settingsData.controls || []),
    }),
    settingsCard({
      iconName: "screensaver",
      title: "Screensaver",
      statusHtml: settingsPill(ssTimeoutMs > 0 ? "ENABLED" : "DISABLED", ssTimeoutMs > 0 ? "good" : "neutral"),
      bodyHtml: `
        <dl class="settings-list">
          <div class="settings-row">
            <dt>Idle Timeout</dt>
            <dd>
              <div class="screensaver-settings-row">
                <select class="screensaver-select" id="ss-timeout-select">
                  <option value="30000" ${ssTimeoutPref === "30000" ? "selected" : ""}>30 Seconds</option>
                  <option value="60000" ${ssTimeoutPref === "60000" ? "selected" : ""}>1 Minute</option>
                  <option value="180000" ${ssTimeoutPref === "180000" ? "selected" : ""}>3 Minutes</option>
                  <option value="300000" ${ssTimeoutPref === "300000" ? "selected" : ""}>5 Minutes</option>
                  <option value="0" ${ssTimeoutPref === "0" ? "selected" : ""}>Never (Disabled)</option>
                </select>
              </div>
            </dd>
          </div>
          <div class="settings-row">
            <dt>Theme Style</dt>
            <dd>AI Diagnostic Core</dd>
          </div>
        </dl>
      `
    }),
    settingsCard({
      iconName: "water",
      title: "Tank Sensors",
      bodyHtml: renderTankSettings(settingsData.tanks || []),
      className: "settings-card-full",
    }),
  ].join("");

  // Bind screensaver dropdown events
  const timeoutSelect = document.querySelector("#ss-timeout-select");
  if (timeoutSelect) {
    timeoutSelect.addEventListener("change", (e) => {
      const newVal = e.target.value;
      localStorage.setItem("ss_timeout", newVal);
      ssTimeoutPref = newVal;
      ssTimeoutMs = parseInt(newVal, 10);
      renderSettings();
      resetIdleTimer();
    });
  }
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatHistoryTime(timestamp, range) {
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }

  if (range === "day") {
    return new Intl.DateTimeFormat([], {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  if (range === "week") {
    return new Intl.DateTimeFormat([], {
      weekday: "short",
      hour: "2-digit",
    }).format(date);
  }

  return new Intl.DateTimeFormat([], {
    month: "short",
    day: "numeric",
  }).format(date);
}

function temperatureLinePath(points, key, xForTimestamp, yForValue) {
  let path = "";
  let drawing = false;

  points.forEach((point) => {
    const value = finiteNumber(point[key]);
    if (value === null) {
      drawing = false;
      return;
    }

    const x = xForTimestamp(point.timestamp).toFixed(1);
    const y = yForValue(value).toFixed(1);
    path += `${drawing ? "L" : "M"}${x} ${y} `;
    drawing = true;
  });

  return path.trim();
}

function renderTemperatureChart(data) {
  if (!temperatureChart) {
    return;
  }

  const points = data?.points || [];
  const values = [];
  points.forEach((point) => {
    ["inside_c", "outside_c"].forEach((key) => {
      const value = finiteNumber(point[key]);
      if (value !== null) {
        values.push(value);
      }
    });
  });

  const hasValues = values.length > 0;
  if (temperatureEmpty) {
    temperatureEmpty.hidden = hasValues;
    temperatureEmpty.textContent = temperatureHistoryError
      ? "History unavailable"
      : temperatureHistoryLoading
        ? "Loading"
        : "Collecting readings";
  }

  if (!hasValues) {
    temperatureChart.innerHTML = "";
    return;
  }

  const viewWidth = 800;
  const viewHeight = 320;
  const plot = {
    left: 56,
    right: 22,
    top: 22,
    bottom: 46,
  };
  const plotWidth = viewWidth - plot.left - plot.right;
  const plotHeight = viewHeight - plot.top - plot.bottom;
  const rangeStart = Number(data.start_ts);
  const rangeEnd = Number(data.end_ts);
  const startTs = Number.isFinite(rangeStart) ? rangeStart : points[0].timestamp;
  const endTs = Number.isFinite(rangeEnd) ? rangeEnd : points[points.length - 1].timestamp;
  const span = Math.max(1, endTs - startTs);
  let minTemp = Math.floor(Math.min(...values) - 1);
  let maxTemp = Math.ceil(Math.max(...values) + 1);
  if (maxTemp - minTemp < 4) {
    const midpoint = (minTemp + maxTemp) / 2;
    minTemp = Math.floor(midpoint - 2);
    maxTemp = Math.ceil(midpoint + 2);
  }

  const tempSpan = Math.max(1, maxTemp - minTemp);
  const xForTimestamp = (timestamp) => {
    const value = Number(timestamp);
    return plot.left + ((value - startTs) / span) * plotWidth;
  };
  const yForValue = (value) => (
    plot.top + ((maxTemp - value) / tempSpan) * plotHeight
  );
  const insidePath = temperatureLinePath(points, "inside_c", xForTimestamp, yForValue);
  const outsidePath = temperatureLinePath(points, "outside_c", xForTimestamp, yForValue);
  const yTicks = Array.from({ length: 5 }, (_, index) => (
    minTemp + (tempSpan * index / 4)
  )).reverse();
  const xTicks = Array.from({ length: 5 }, (_, index) => (
    startTs + (span * index / 4)
  ));
  const latestInside = [...points].reverse().find((point) => finiteNumber(point.inside_c) !== null);
  const latestOutside = [...points].reverse().find((point) => finiteNumber(point.outside_c) !== null);

  temperatureChart.innerHTML = `
    <rect class="chart-bg" x="${plot.left}" y="${plot.top}" width="${plotWidth}" height="${plotHeight}"></rect>
    ${yTicks.map((tick) => {
      const y = yForValue(tick);
      return `
        <line class="chart-grid-line" x1="${plot.left}" y1="${y}" x2="${viewWidth - plot.right}" y2="${y}"></line>
        <text class="chart-y-label" x="${plot.left - 12}" y="${y + 4}">${Math.round(tick)}°</text>
      `;
    }).join("")}
    ${xTicks.map((tick) => {
      const x = xForTimestamp(tick);
      return `
        <line class="chart-grid-line vertical" x1="${x}" y1="${plot.top}" x2="${x}" y2="${viewHeight - plot.bottom}"></line>
        <text class="chart-x-label" x="${x}" y="${viewHeight - 14}">${escapeHtml(formatHistoryTime(tick, data.range))}</text>
      `;
    }).join("")}
    <path class="temperature-chart-line chart-inside" d="${insidePath}"></path>
    <path class="temperature-chart-line chart-outside" d="${outsidePath}"></path>
    ${latestInside ? `<circle class="chart-dot chart-inside-dot" cx="${xForTimestamp(latestInside.timestamp)}" cy="${yForValue(latestInside.inside_c)}" r="4"></circle>` : ""}
    ${latestOutside ? `<circle class="chart-dot chart-outside-dot" cx="${xForTimestamp(latestOutside.timestamp)}" cy="${yForValue(latestOutside.outside_c)}" r="4"></circle>` : ""}
  `;
}

function renderTemperatureView() {
  const latest = temperatureHistory?.latest || {};
  const liveEnvironment = lastData?.environment || {};
  const latestInside = latest.inside_c ?? liveEnvironment.inside_c;
  const latestOutside = latest.outside_c ?? liveEnvironment.outside_c;
  const latestHumidity = latest.outside_humidity ?? liveEnvironment.outside_humidity;
  const titleText = temperatureRangeTitles[temperatureHistoryRange] || temperatureRangeTitles.day;

  updateTextIfChanged(temperatureLatestInside, tempDetail(latestInside));
  updateTextIfChanged(temperatureLatestOutside, tempDetail(latestOutside));
  updateTextIfChanged(temperatureLatestHumidity, humidity(latestHumidity));
  updateTextIfChanged(temperatureChartTitle, titleText);

  temperatureRangeButtons.forEach((button) => {
    const isActive = button.dataset.temperatureRange === temperatureHistoryRange;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });

  if (temperatureHistoryMeta) {
    if (temperatureHistoryError) {
      temperatureHistoryMeta.textContent = temperatureHistoryError;
    } else if (temperatureHistoryLoading && !temperatureHistory) {
      temperatureHistoryMeta.textContent = "Loading";
    } else if (temperatureHistory) {
      const sampleCount = Number(temperatureHistory.sample_count || 0);
      const bucketMinutes = Math.max(1, Math.round(Number(temperatureHistory.bucket_seconds || 0) / 60));
      temperatureHistoryMeta.textContent = `${sampleCount} samples, ${bucketMinutes} min buckets`;
    } else {
      temperatureHistoryMeta.textContent = "Loading";
    }
  }

  renderTemperatureChart(temperatureHistory);
}

function setActiveView(view) {
  if (
    !dashboardView
    || !temperatureView
    || !settingsView
    || !["dashboard", "temperature", "settings"].includes(view)
  ) {
    return;
  }

  activeView = view;
  dashboardView.hidden = view !== "dashboard";
  temperatureView.hidden = view !== "temperature";
  settingsView.hidden = view !== "settings";

  navItems.forEach((button) => {
    const isActive = button.dataset.viewTarget === view;
    button.classList.toggle("active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });

  if (view === "settings") {
    renderSettings();
    if (!settingsData && !settingsRequested) {
      fetchSettings();
    }
  }

  if (view === "temperature") {
    renderTemperatureView();
    fetchTemperatureHistory();
  }
}

function updateTextIfChanged(element, newText) {
  if (!element) return;
  if (element.textContent !== newText) {
    element.textContent = newText;
    element.classList.remove("telemetry-flicker");
    void element.offsetWidth; // Force DOM reflow to restart animation
    element.classList.add("telemetry-flicker");
  }
}

function updateStyleIfChanged(element, property, newValue) {
  if (!element) return;
  if (element.style.getPropertyValue(property) !== newValue) {
    element.style.setProperty(property, newValue);
  }
}

function updateClock() {
  const now = new Date();
  clock.textContent = new Intl.DateTimeFormat([], {
    hour: "numeric",
    minute: "2-digit",
  }).format(now);
}

function setConnection(text, isError = false) {
  if (connectionStatus.textContent !== text) {
    connectionStatus.textContent = text;
  }
  connectionStatus.classList.toggle("is-error", isError);
}

function renderTanks(tanks) {
  if (tankGrid.children.length !== tanks.length) {
    tankGrid.innerHTML = tanks
      .map((tank) => {
        const reading = tankReading(tank);
        const accent = tank.accent || "#29d8ff";

        return `
          <article class="tank-module ${reading.isOffline ? "is-offline" : ""}" data-tank-id="${tank.id}" style="--accent: ${accent}; --level: ${reading.level}%">
            <div class="tank-icon">${icon(tank.icon)}</div>
            <div class="tank-tube" aria-hidden="true">
              <span class="tank-fill" style="opacity: ${reading.fillOpacity}"></span>
            </div>
            <p class="tank-percent">${reading.percentText}</p>
            <p class="tank-label">${tank.label}</p>
            <p class="tank-capacity">${reading.capacityText}</p>
          </article>
        `;
      })
      .join("");
    return;
  }

  tanks.forEach((tank) => {
    const article = tankGrid.querySelector(`[data-tank-id="${tank.id}"]`);
    if (!article) return;

    const reading = tankReading(tank);

    article.classList.toggle("is-offline", reading.isOffline);
    updateStyleIfChanged(article, "--level", `${reading.level}%`);

    const fillEl = article.querySelector(".tank-fill");
    if (fillEl) {
      updateStyleIfChanged(fillEl, "opacity", reading.fillOpacity);
    }

    const percentEl = article.querySelector(".tank-percent");
    updateTextIfChanged(percentEl, reading.percentText);

    const capacityEl = article.querySelector(".tank-capacity");
    updateTextIfChanged(capacityEl, reading.capacityText);

    const labelEl = article.querySelector(".tank-label");
    if (labelEl && labelEl.textContent !== tank.label) {
      labelEl.textContent = tank.label;
    }
  });
}

function controlClass(control) {
  const classes = ["control-pad"];
  if (control.is_on === true) {
    classes.push("is-on");
  } else {
    classes.push("is-off");
  }

  if (control.connected === false) {
    classes.push("is-offline");
  }

  if (pendingControl === control.id) {
    classes.push("is-pending");
  }

  return classes.join(" ");
}

function renderControls(controls) {
  if (controlGrid.children.length !== controls.length) {
    controlGrid.innerHTML = controls
      .map((control) => {
        const state = control.connected === false
          ? "OFFLINE"
          : control.is_on
            ? "ON"
            : "OFF";

        return `
          <button
            class="${controlClass(control)}"
            type="button"
            data-control-id="${control.id}"
            aria-label="${control.label} ${state}"
            ${pendingControl === control.id ? "disabled" : ""}
          >
            <span class="control-icon">${icon(control.icon)}</span>
            <span class="control-label">${control.label}</span>
            <span class="control-state">${state}</span>
          </button>
        `;
      })
      .join("");

    controlGrid.querySelectorAll(".control-pad").forEach((button) => {
      button.addEventListener("click", () => toggleControl(button.dataset.controlId));
    });
    return;
  }

  controls.forEach((control) => {
    const button = controlGrid.querySelector(`[data-control-id="${control.id}"]`);
    if (!button) return;

    const state = control.connected === false
      ? "OFFLINE"
      : control.is_on
        ? "ON"
        : "OFF";

    const newClass = controlClass(control);
    if (button.className !== newClass) {
      button.className = newClass;
    }

    const shouldBeDisabled = pendingControl === control.id;
    if (button.disabled !== shouldBeDisabled) {
      button.disabled = shouldBeDisabled;
    }

    const newAriaLabel = `${control.label} ${state}`;
    if (button.getAttribute("aria-label") !== newAriaLabel) {
      button.setAttribute("aria-label", newAriaLabel);
    }

    const stateEl = button.querySelector(".control-state");
    updateTextIfChanged(stateEl, state);

    const labelEl = button.querySelector(".control-label");
    if (labelEl && labelEl.textContent !== control.label) {
      labelEl.textContent = control.label;
    }
  });
}

function renderAferiy(device) {
  if (!aferiyCard) {
    return;
  }

  if (!device) {
    aferiyCard.hidden = true;
    return;
  }

  aferiyCard.hidden = false;
  aferiyCard.classList.toggle("is-offline", device.connected === false);

  const percent = Number.isFinite(Number(device.percent))
    ? capPercent(device.percent)
    : null;
  const percentText = percent === null ? "--%" : `${percent}%`;
  const state = device.connected === false
    ? "OFFLINE"
    : device.source === "ble"
      ? "BLE LIVE"
      : device.source === "mqtt"
        ? "MQTT LIVE"
      : "STATIC";
  const flowText = device.connected === false
    ? "Telemetry offline"
    : `In ${watt(device.input_w)} / Out ${watt(device.output_w)}`;

  updateTextIfChanged(aferiyLabel, device.label || "AFERIY P280");
  updateStyleIfChanged(aferiyFill, "--battery", `${percent ?? 0}%`);
  updateTextIfChanged(aferiyPercent, percentText);
  updateTextIfChanged(aferiyFlow, flowText);
  updateTextIfChanged(aferiyState, state);
}

function render(data) {
  lastData = data;

  const newTitle = data.title || "CAMPER VAN";
  if (title.textContent !== newTitle) {
    title.textContent = newTitle;
    document.title = `${newTitle} Dashboard`;
  }

  renderTanks(data.tanks || []);
  renderControls(data.controls || []);

  updateTextIfChanged(insideTemp, temp(data.environment?.inside_c));
  updateTextIfChanged(outsideTemp, temp(data.environment?.outside_c));

  const battery = capPercent(data.battery?.percent);
  updateStyleIfChanged(batteryFill, "--battery", `${battery}%`);
  updateTextIfChanged(batteryPercent, `${battery}%`);

  const aferiy = (data.power_devices || [])
    .find((device) => device.id === "aferiy_p280");
  renderAferiy(aferiy);

  if (data.tapo?.connected) {
    const alias = data.tapo.device?.alias || "Tapo";
    setConnection(`${alias} online`);
  } else if (data.tapo?.error) {
    setConnection("Tapo offline", true);
    connectionStatus.title = data.tapo.error;
  } else {
    setConnection("Local controls active");
  }

  if (activeView === "settings") {
    renderSettings();
  }

  if (activeView === "temperature") {
    renderTemperatureView();
  }
}

async function fetchStatus() {
  if (statusFetchInFlight) {
    return;
  }

  statusFetchInFlight = true;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);

  try {
    const response = await fetch("/api/status", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Status request failed: ${response.status}`);
    }

    const data = await response.json();
    render(data);
    if (activeView === "temperature") {
      fetchTemperatureHistory();
    }
  } catch (error) {
    const isTimeout = error.name === "AbortError";
    setConnection(isTimeout ? "Dashboard status timeout" : "Dashboard server offline", true);
    connectionStatus.title = error.message;
  } finally {
    window.clearTimeout(timeoutId);
    statusFetchInFlight = false;
  }
}

async function fetchSettings() {
  settingsRequested = true;
  settingsError = null;
  renderSettings();

  try {
    const response = await fetch("/api/settings", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Settings request failed: ${response.status}`);
    }

    settingsData = await response.json();
    renderSettings();
  } catch (error) {
    settingsError = error.message;
    settingsRequested = false;
    setConnection("Settings unavailable", true);
    connectionStatus.title = error.message;
    renderSettings();
  }
}

async function fetchTemperatureHistory() {
  if (temperatureHistoryLoading) {
    return;
  }

  temperatureHistoryLoading = true;
  temperatureHistoryError = null;
  renderTemperatureView();

  try {
    const response = await fetch(
      `/api/temperature-history?range=${encodeURIComponent(temperatureHistoryRange)}`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      throw new Error(`History request failed: ${response.status}`);
    }

    temperatureHistory = await response.json();
  } catch (error) {
    temperatureHistoryError = error.message;
    setConnection("Temperature history unavailable", true);
    connectionStatus.title = error.message;
  } finally {
    temperatureHistoryLoading = false;
    renderTemperatureView();
  }
}

async function toggleControl(controlId) {
  if (!controlId || pendingControl) {
    return;
  }

  pendingControl = controlId;
  if (lastData) {
    renderControls(lastData.controls || []);
  }

  try {
    const response = await fetch(`/api/controls/${encodeURIComponent(controlId)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action: "toggle" }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `Control request failed: ${response.status}`);
    }

    await fetchStatus();
  } catch (error) {
    setConnection(error.message, true);
  } finally {
    pendingControl = null;
    if (lastData) {
      renderControls(lastData.controls || []);
    }
  }
}

navItems.forEach((button) => {
  button.addEventListener("click", () => setActiveView(button.dataset.viewTarget));
});

temperatureRangeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const range = button.dataset.temperatureRange;
    if (!temperatureRangeEndpoints.has(range) || range === temperatureHistoryRange) {
      return;
    }

    temperatureHistoryRange = range;
    temperatureHistory = null;
    renderTemperatureView();
    fetchTemperatureHistory();
  });
});

settingsBackButton?.addEventListener("click", () => setActiveView("dashboard"));

// ==========================================================================
// SCREENSAVER FUNCTIONS & TRIGGERS
// ==========================================================================

const ssLogTemplates = {
  ok: [
    "Battery matrix telemetry: {battery}% stable.",
    "Fresh water capacity: {fresh}% remaining.",
    "Grey water expansion: {grey}% filled.",
    "Climate core operational. Cabin: {tempIn}.",
    "Auxiliary controllers pinged. All responsive.",
    "External sensors active. Outside: {tempOut}."
  ],
  sys: [
    "Monitoring BLE beacon broadcasts...",
    "Telemetry synchronizing with Tapo endpoint.",
    "Database state check: no integrity errors.",
    "Performing active cyclic diagnostic self-test.",
    "Security protocols armed and passive.",
    "Flushing terminal log buffer logs."
  ],
  info: [
    "Inverter power draw within nominal parameters.",
    "12V house bus voltage: 13.6V (Stable).",
    "API connection status: Connected to system.",
    "System network interface link: UP."
  ]
};

function generateSSLogLine() {
  if (!lastData) return { type: "sys", text: "Initializing diagnostic scan..." };

  const categories = ["ok", "sys", "info"];
  const cat = categories[Math.floor(Math.random() * categories.length)];
  const templates = ssLogTemplates[cat];
  let text = templates[Math.floor(Math.random() * templates.length)];

  const batteryVal = lastData.battery?.percent ?? "--";
  const fresh = (lastData.tanks || []).find(t => t.id === "fresh");
  const freshVal = fresh ? capPercent(fresh.percent) : "--";
  const grey = (lastData.tanks || []).find(t => t.id === "grey");
  const greyVal = grey ? capPercent(grey.percent) : "--";
  const tempInVal = temp(lastData.environment?.inside_c);
  const tempOutVal = temp(lastData.environment?.outside_c);

  text = text
    .replace("{battery}", batteryVal)
    .replace("{fresh}", freshVal)
    .replace("{grey}", greyVal)
    .replace("{tempIn}", tempInVal)
    .replace("{tempOut}", tempOutVal);

  return { type: cat, text };
}

function addSSTerminalLine(type, text) {
  if (!ssTerminalLog) return;
  const lineEl = document.createElement("div");
  lineEl.className = `term-line ${type}`;

  const timestamp = new Date().toLocaleTimeString([], { hour12: false });
  lineEl.textContent = `[${timestamp}] [${type.toUpperCase()}] ${text}`;

  ssTerminalLog.appendChild(lineEl);

  while (ssTerminalLog.children.length > 8) {
    ssTerminalLog.removeChild(ssTerminalLog.firstChild);
  }
}

function startScreensaverLogs() {
  if (!ssTerminalLog) return;
  ssTerminalLog.innerHTML = "";

  addSSTerminalLine("sys", "AI mainframe online.");
  addSSTerminalLine("ok", "Diagnostic sequence initialized.");
  addSSTerminalLine("sys", "Telemetry core link active.");

  clearInterval(terminalInterval);
  terminalInterval = setInterval(() => {
    const log = generateSSLogLine();
    addSSTerminalLine(log.type, log.text);
  }, 4000);
}

function updateScreensaverTelemetry() {
  if (!screensaverActive) return;

  // Update clocks & dates
  const now = new Date();
  if (ssClock) {
    ssClock.textContent = new Intl.DateTimeFormat([], {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: false
    }).format(now);
  }

  if (ssDate) {
    ssDate.textContent = new Intl.DateTimeFormat([], {
      weekday: "short",
      month: "short",
      day: "numeric"
    }).format(now);
  }

  if (!lastData) return;

  // Battery
  const batteryVal = capPercent(lastData.battery?.percent);
  if (ssBattery) ssBattery.textContent = `${batteryVal}%`;
  if (ssBatteryRing) ssBatteryRing.style.setProperty("--val", `${batteryVal}%`);

  // Tanks
  const fresh = (lastData.tanks || []).find(t => t.id === "fresh");
  if (fresh) {
    const fPercent = capPercent(fresh.percent);
    if (ssFresh) ssFresh.textContent = `${fPercent}%`;
    if (ssFreshRing) ssFreshRing.style.setProperty("--val", `${fPercent}%`);
  }

  const grey = (lastData.tanks || []).find(t => t.id === "grey");
  if (grey) {
    const gPercent = capPercent(grey.percent);
    if (ssGrey) ssGrey.textContent = `${gPercent}%`;
    if (ssGreyRing) ssGreyRing.style.setProperty("--val", `${gPercent}%`);
  }

  // Temperatures
  if (ssTempIn) ssTempIn.textContent = temp(lastData.environment?.inside_c);
  if (ssTempOut) ssTempOut.textContent = temp(lastData.environment?.outside_c);

  // Power Inverter
  if (ssPowerFlow) {
    const aferiy = (lastData.power_devices || []).find(d => d.id === "aferiy_p280");
    if (aferiy && aferiy.connected !== false) {
      ssPowerFlow.textContent = `IN ${watt(aferiy.input_w)} / OUT ${watt(aferiy.output_w)}`;
    } else {
      ssPowerFlow.textContent = "-- W";
    }
  }
}

function initCanvas() {
  if (!screensaverCanvas) return;
  canvasCtx = screensaverCanvas.getContext("2d");
  resizeCanvas();
  window.addEventListener("resize", resizeCanvas);
}

function resizeCanvas() {
  if (!screensaverCanvas) return;
  const rect = screensaverCanvas.getBoundingClientRect();
  screensaverCanvas.width = rect.width || 480;
  screensaverCanvas.height = rect.height || 480;
  canvasWidth = screensaverCanvas.width;
  canvasHeight = screensaverCanvas.height;
}

let lastClockSec = -1;

function drawScreensaverFrame() {
  if (!screensaverActive || !canvasCtx) return;

  animTime += 0.03;

  // Responds to time seconds change
  const now = new Date();
  const currentSec = now.getSeconds();
  if (currentSec !== lastClockSec) {
    lastClockSec = currentSec;
    updateScreensaverTelemetry();
  }

  const w = canvasWidth;
  const h = canvasHeight;
  const cx = w / 2;
  const cy = h / 2;

  canvasCtx.clearRect(0, 0, w, h);

  const maxRadius = Math.min(w, h) * 0.45;

  // Outer tick indices ring
  canvasCtx.strokeStyle = "rgba(41, 216, 255, 0.15)";
  canvasCtx.lineWidth = 1;
  const ticksCount = 120;
  for (let i = 0; i < ticksCount; i += 2) {
    const angle = (i / ticksCount) * Math.PI * 2 - animTime * 0.015;
    const tickLen = (i % 10 === 0) ? 6 : 3;
    const startX = cx + Math.cos(angle) * maxRadius;
    const startY = cy + Math.sin(angle) * maxRadius;
    const endX = cx + Math.cos(angle) * (maxRadius - tickLen);
    const endY = cy + Math.sin(angle) * (maxRadius - tickLen);

    canvasCtx.beginPath();
    canvasCtx.moveTo(startX, startY);
    canvasCtx.lineTo(endX, endY);
    canvasCtx.stroke();
  }

  // concentric rotating coordinates rings
  canvasCtx.save();
  canvasCtx.translate(cx, cy);
  canvasCtx.rotate(animTime * 0.12);
  canvasCtx.strokeStyle = "rgba(41, 216, 255, 0.22)";
  canvasCtx.setLineDash([6, 14, 20, 14]);
  canvasCtx.beginPath();
  canvasCtx.arc(0, 0, maxRadius * 0.88, 0, Math.PI * 2);
  canvasCtx.stroke();
  canvasCtx.restore();

  canvasCtx.save();
  canvasCtx.translate(cx, cy);
  canvasCtx.rotate(-animTime * 0.18);
  canvasCtx.strokeStyle = "rgba(57, 245, 214, 0.18)";
  canvasCtx.setLineDash([22, 10, 4, 10]);
  canvasCtx.beginPath();
  canvasCtx.arc(0, 0, maxRadius * 0.78, 0, Math.PI * 2);
  canvasCtx.stroke();
  canvasCtx.restore();

  // Morphing circular waveforms
  const layers = [
    { color: "rgba(41, 216, 255, 0.38)", waveCount: 5, amp: 16, phase: animTime },
    { color: "rgba(57, 245, 214, 0.28)", waveCount: 7, amp: 10, phase: -animTime * 1.2 },
    { color: "rgba(41, 216, 255, 0.15)", waveCount: 4, amp: 6, phase: animTime * 0.8 }
  ];

  layers.forEach((layer) => {
    canvasCtx.beginPath();
    canvasCtx.strokeStyle = layer.color;
    canvasCtx.lineWidth = 1.5;

    const points = 120;
    const radius = maxRadius * 0.65;

    for (let i = 0; i <= points; i++) {
      const angle = (i / points) * Math.PI * 2;
      const waveShift = Math.sin(angle * layer.waveCount + layer.phase) * layer.amp;
      const currentRadius = radius + waveShift;

      const px = cx + Math.cos(angle) * currentRadius;
      const py = cy + Math.sin(angle) * currentRadius;

      if (i === 0) {
        canvasCtx.moveTo(px, py);
      } else {
        canvasCtx.lineTo(px, py);
      }
    }
    canvasCtx.closePath();
    canvasCtx.stroke();
  });

  // Breathing core orb
  const pulseRadius = maxRadius * 0.46 + Math.sin(animTime * 1.3) * 6;
  const gradient = canvasCtx.createRadialGradient(cx, cy, 0, cx, cy, pulseRadius);
  gradient.addColorStop(0, "rgba(41, 216, 255, 0.2)");
  gradient.addColorStop(0.5, "rgba(57, 245, 214, 0.05)");
  gradient.addColorStop(1, "rgba(3, 14, 24, 0)");

  canvasCtx.fillStyle = gradient;
  canvasCtx.beginPath();
  canvasCtx.arc(cx, cy, pulseRadius, 0, Math.PI * 2);
  canvasCtx.fill();

  // Orbiting dynamic diagnostic bars
  const barCount = 60;
  canvasCtx.strokeStyle = "rgba(41, 216, 255, 0.3)";
  canvasCtx.lineWidth = 1.5;
  const innerR = maxRadius * 0.52;
  for (let i = 0; i < barCount; i++) {
    const angle = (i / barCount) * Math.PI * 2 + animTime * 0.04;
    const freq = Math.sin(i * 0.35 + animTime * 1.8) * Math.cos(i * 0.15 + animTime * 0.6);
    const height = Math.max(2, (freq + 1.2) * 12);

    const startX = cx + Math.cos(angle) * innerR;
    const startY = cy + Math.sin(angle) * innerR;
    const endX = cx + Math.cos(angle) * (innerR + height);
    const endY = cy + Math.sin(angle) * (innerR + height);

    canvasCtx.beginPath();
    canvasCtx.moveTo(startX, startY);
    canvasCtx.lineTo(endX, endY);
    canvasCtx.stroke();
  }

  animationFrameId = requestAnimationFrame(drawScreensaverFrame);
}

function startScreensaverAnimation() {
  if (!canvasCtx) {
    initCanvas();
  }
  resizeCanvas();
  animationFrameId = requestAnimationFrame(drawScreensaverFrame);
}

function activateScreensaver() {
  if (screensaverActive) return;
  screensaverActive = true;
  ssActivationTime = Date.now();

  updateScreensaverTelemetry();

  if (screensaverOverlay) {
    screensaverOverlay.hidden = false;
    void screensaverOverlay.offsetWidth;
    screensaverOverlay.classList.add("is-active");
  }

  startScreensaverAnimation();
  startScreensaverLogs();
}

function wakeUpScreensaver() {
  if (!screensaverActive) return;

  addSSTerminalLine("sys", "Interaction detected. Restoring session...");

  if (screensaverOverlay) {
    screensaverOverlay.classList.remove("is-active");
  }

  setTimeout(() => {
    if (screensaverOverlay) {
      screensaverOverlay.hidden = true;
    }
    screensaverActive = false;
    cancelAnimationFrame(animationFrameId);
    clearInterval(terminalInterval);
  }, 500);
}

function resetIdleTimer(e) {
  if (e && e.type === "mousemove") {
    if (e.clientX === lastMouseX && e.clientY === lastMouseY) {
      return;
    }
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  }

  if (screensaverActive) {
    if (Date.now() - ssActivationTime > 1200) {
      wakeUpScreensaver();
    }
    return;
  }
  clearTimeout(idleTimer);
  if (ssTimeoutMs > 0) {
    idleTimer = setTimeout(activateScreensaver, ssTimeoutMs);
  }
}

// Bind idle tracking listeners on user interaction
["mousemove", "mousedown", "keydown", "touchstart", "click"].forEach((event) => {
  document.addEventListener(event, resetIdleTimer, { passive: true });
});

// Bind manual sleep trigger
screensaverTrigger?.addEventListener("click", (e) => {
  e.stopPropagation();
  activateScreensaver();
});

// ==========================================================================
// SYSTEM BOOT DIAGNOSTICS & LOGIC
// ==========================================================================

let bootActive = true;
let bootProgress = 0;
let bootInterval = null;
let bootSubsystemsState = {
  core: "connecting",
  tapo: "connecting",
  climate: "connecting",
  tanks: "connecting",
  power: "connecting"
};
let bootLoggedStates = {
  core: null,
  tapo: null,
  climate: null,
  tanks: null,
  power: null
};

function addBootTerminalLine(type, text) {
  const terminal = document.querySelector("#boot-terminal-log");
  if (!terminal) return;
  const lineEl = document.createElement("div");
  lineEl.className = `term-line ${type}`;

  const now = new Date();
  const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}.${Math.floor(now.getMilliseconds() / 10).toString().padStart(2, '0')}`;

  lineEl.textContent = `[${timeStr}] [${type.toUpperCase()}] ${text}`;

  terminal.appendChild(lineEl);

  while (terminal.children.length > 9) {
    terminal.removeChild(terminal.firstChild);
  }
}

function updateBootSubsystemUI(id, state, text) {
  const el = document.querySelector(`#boot-item-${id}`);
  if (!el) return;

  el.classList.remove("connecting", "online", "offline");

  if (state === "connecting") el.classList.add("connecting");
  if (state === "online") el.classList.add("online");
  if (state === "offline") el.classList.add("offline");

  const valEl = el.querySelector(".status-value");
  if (valEl) valEl.textContent = text;
}

function updateBootProgressUI() {
  const percentText = document.querySelector("#boot-percent-text");
  const fill = document.querySelector("#boot-progress-fill");
  if (percentText) percentText.textContent = `${bootProgress}%`;
  if (fill) fill.style.width = `${bootProgress}%`;
}

function finishBootLoader() {
  if (!bootActive) return;
  bootActive = false;
  clearInterval(bootInterval);

  addBootTerminalLine("ok", "SYSTEM DIAGNOSTICS SUITE COMPLETED SUCCESSFULLY.");
  addBootTerminalLine("sys", "LOADING GRAPHICAL SHELL USER INTERFACE...");

  const bootOverlay = document.querySelector("#boot-overlay");
  if (bootOverlay) {
    setTimeout(() => {
      bootOverlay.classList.add("is-fading");
      setTimeout(() => {
        bootOverlay.style.display = "none";
        bootOverlay.hidden = true;
      }, 500);
    }, 1000);
  }

  // Start regular fetching loops
  fetchStatus();
  setInterval(fetchStatus, STATUS_REFRESH_MS);
}

function skipBootLoader() {
  if (!bootActive) return;
  bootActive = false;
  clearInterval(bootInterval);

  bootProgress = 100;
  updateBootProgressUI();

  addBootTerminalLine("info", "DIAGNOSTICS SYSTEM CHECK BYPASSED BY USER.");
  addBootTerminalLine("sys", "ENTERING DASHBOARD ENVIRONMENT DIRECTLY...");

  const bootOverlay = document.querySelector("#boot-overlay");
  if (bootOverlay) {
    setTimeout(() => {
      bootOverlay.classList.add("is-fading");
      setTimeout(() => {
        bootOverlay.style.display = "none";
        bootOverlay.hidden = true;
      }, 300);
    }, 400);
  }

  // Start regular fetching loops
  fetchStatus();
  setInterval(fetchStatus, STATUS_REFRESH_MS);
}

function processBootDiagnostics(data) {
  // 1. Core System
  bootSubsystemsState.core = "online";
  updateBootSubsystemUI("core", "online", "ACTIVE");
  if (bootLoggedStates.core !== "online") {
    bootLoggedStates.core = "online";
    addBootTerminalLine("ok", "CORE SYS MAIN DIAGNOSTIC CORE INITIALIZED.");
  }

  // 2. Tapo Relay
  const tapo = data.tapo || {};
  let tapoState = "connecting";
  let tapoText = "CONNECTING...";

  if (tapo.connected === true) {
    tapoState = "online";
    tapoText = "ONLINE";
  } else if (tapo.error) {
    if (tapo.error.includes("Connecting...") || tapo.error.includes("Initializing...")) {
      tapoState = "connecting";
      tapoText = "CONNECTING...";
    } else {
      tapoState = "offline";
      tapoText = "OFFLINE";
    }
  }

  bootSubsystemsState.tapo = tapoState;
  updateBootSubsystemUI("tapo", tapoState, tapoText);
  if (bootLoggedStates.tapo !== tapoState) {
    bootLoggedStates.tapo = tapoState;
    if (tapoState === "online") {
      const alias = tapo.device?.alias || "Tapo Plug";
      addBootTerminalLine("ok", `TAPO RELAY BOUND SUCCESSFULLY: [${alias}]`);
    } else if (tapoState === "offline") {
      addBootTerminalLine("warn", `TAPO RELAY OFFLINE: ${tapo.error || "Connection failed"}`);
    } else {
      addBootTerminalLine("sys", "TAPO RELAY: ESTABLISHING NETWORK HANDSHAKE...");
    }
  }

  // 3. Climate Core
  const env = data.environment || {};
  let climateState = "connecting";
  let climateText = "CONNECTING...";

  if (env.outside_connected === true) {
    climateState = "online";
    climateText = "ONLINE";
  } else if (env.outside_error) {
    if (env.outside_error.includes("Connecting...") || env.outside_error.includes("Waiting for sensor data...")) {
      climateState = "connecting";
      climateText = "CONNECTING...";
    } else {
      climateState = "offline";
      climateText = "OFFLINE";
    }
  }

  bootSubsystemsState.climate = climateState;
  updateBootSubsystemUI("climate", climateState, climateText);
  if (bootLoggedStates.climate !== climateState) {
    bootLoggedStates.climate = climateState;
    if (climateState === "online") {
      addBootTerminalLine("ok", `CLIMATE CORE ESTABLISHED. OUTSIDE TEMP: ${env.outside_c}°C`);
    } else if (climateState === "offline") {
      addBootTerminalLine("warn", `CLIMATE CORE OFFLINE: ${env.outside_error}`);
    } else {
      addBootTerminalLine("sys", "CLIMATE CORE: DISCOVERING BLE TEMP METERS...");
    }
  }

  // 4. Tank Channels
  const tanks = data.tanks || [];
  let tanksState = "online";
  let tanksText = "ONLINE";
  let offlineTankName = "";

  tanks.forEach(tank => {
    if (tank.connected === false && tank.sensor_error) {
      tanksState = "offline";
      offlineTankName = tank.label;
    }
  });

  bootSubsystemsState.tanks = tanksState;
  updateBootSubsystemUI("tanks", tanksState, tanksText);
  if (bootLoggedStates.tanks !== tanksState) {
    bootLoggedStates.tanks = tanksState;
    if (tanksState === "online") {
      const tankDetails = tanks.map(t => `${t.label}: ${t.percent}%`).join(", ");
      addBootTerminalLine("ok", `TANK CHANNELS CALIBRATED. ${tankDetails}`);
    } else {
      addBootTerminalLine("warn", `TANK ADC READ FAIL: ${offlineTankName} sensor error`);
    }
  }

  // 5. Power Inverter
  const power = (data.power_devices || []).find(d => d.id === "aferiy_p280");
  let powerState = "online";
  let powerText = "ONLINE";

  if (power) {
    if (power.connected === false) {
      if (power.error && (
        power.error.includes("Connecting")
        || power.error.includes("Scanning for AFERIY")
        || power.error.includes("Starting AFERIY")
        || power.error.includes("Waiting for AFERIY")
      )) {
        powerState = "connecting";
        powerText = "CONNECTING...";
      } else {
        powerState = "offline";
        powerText = "OFFLINE";
      }
    }
  } else {
    powerState = "online";
    powerText = "BYPASSED";
  }

  bootSubsystemsState.power = powerState;
  updateBootSubsystemUI("power", powerState, powerText);
  if (bootLoggedStates.power !== powerState) {
    bootLoggedStates.power = powerState;
    if (powerState === "online") {
      if (power) {
        addBootTerminalLine("ok", `POWER INVERTER ACTIVE: [${power.label}] Charge: ${power.percent}%`);
      } else {
        addBootTerminalLine("info", "POWER INVERTER: NO DEVICE CONFIGURED. BYPASSED.");
      }
    } else if (powerState === "offline") {
      addBootTerminalLine("warn", `POWER INVERTER OFFLINE: ${power?.error || "Telemetry error"}`);
    } else {
      const telemetrySource = sourceLabel(power?.source || "local").toUpperCase();
      addBootTerminalLine("sys", `POWER INVERTER: CONNECTING TO ${telemetrySource} TELEMETRY...`);
    }
  }
}

async function fetchBootStatus() {
  if (!bootActive) return;

  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    render(data);
    processBootDiagnostics(data);
  } catch (error) {
    bootSubsystemsState.core = "offline";
    updateBootSubsystemUI("core", "offline", "ERROR");
    addBootTerminalLine("warn", `CORE SYSTEM ENCOUNTERED DIAGNOSTIC ERROR: ${error.message}`);
  }

  if (bootActive) {
    setTimeout(fetchBootStatus, 1500);
  }
}

function initBootLoader() {
  addBootTerminalLine("sys", "INITIALIZING CAMPER VAN DIAGNOSTIC CORE...");
  addBootTerminalLine("sys", "RUNNING BOOT SEQUENCE v4.2...");
  addBootTerminalLine("info", "MEM CHECK: 512MB RAM OK. FLASH ROM SECURE.");
  addBootTerminalLine("info", "SYS CLOCK INITIALIZED. SYNCHRONIZING TELEMETRY...");

  // Gradually increment bootProgress visually
  bootInterval = setInterval(() => {
    if (!bootActive) return;

    let isFullyChecked = true;
    for (const key in bootSubsystemsState) {
      if (bootSubsystemsState[key] === "connecting") {
        isFullyChecked = false;
      }
    }

    const cap = isFullyChecked ? 100 : 85;
    if (bootProgress < cap) {
      bootProgress += Math.floor(Math.random() * 4) + 1;
      if (bootProgress > cap) bootProgress = cap;
      updateBootProgressUI();
    }

    if (bootProgress >= 100) {
      finishBootLoader();
    }
  }, 120);

  // Bind skip button
  document.querySelector("#boot-skip-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    skipBootLoader();
  });

  // Fast fetch during boot
  fetchBootStatus();
}

// Initialize Idle Timer
resetIdleTimer();

updateClock();
setInterval(updateClock, 1000);

// Start Boot Loader Sequence
initBootLoader();
