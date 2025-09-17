const $ = (sel) => document.querySelector(sel);
const chat = $("#chat");
const promptEl = $("#prompt");
const sendBtn = $("#send");

const listBtn = $("#btn-list");
const sensorSel = $("#sensor");
const windowSel = $("#window");
const queryBtn = $("#btn-query");
const sensorOut = $("#sensor-out");

function addBubble(text, who="bot") {
  const row = document.createElement("div");
  row.className = who === "me" ? "me" : "bot";
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = text;
  row.appendChild(b);
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
}

async function api(path, opts={}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) return r.json();
  return r.text();
}

// --- Chat ---
async function doSend() {
  const msg = (promptEl.value || "").trim();
  if (!msg) return;
  addBubble(msg, "me");
  promptEl.value = "";
  sendBtn.disabled = true;
  try {
    const text = await api("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: msg })
    });
    addBubble(typeof text === "string" ? text : JSON.stringify(text, null, 2), "bot");
  } catch (e) {
    addBubble("[chat error] " + e.message, "bot");
  } finally {
    sendBtn.disabled = false;
  }
}

sendBtn.addEventListener("click", doSend);
promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSend();
});

// --- Sensors ---
function fillSensors(list) {
  sensorSel.innerHTML = "";
  if (!Array.isArray(list)) return;
  for (const s of list) {
    const opt = document.createElement("option");
    opt.value = s.sensor_id;
    opt.textContent = s.name || s.sensor_id;
    sensorSel.appendChild(opt);
  }
}

listBtn.addEventListener("click", async () => {
  listBtn.disabled = true;
  sensorOut.textContent = "Loading sensors…";
  try {
    const data = await api("/api/sensors");
    fillSensors(data);
    sensorOut.textContent = `Loaded ${data.length} sensors.`;
  } catch (e) {
    sensorOut.textContent = "[list error] " + e.message;
  } finally {
    listBtn.disabled = false;
  }
});

queryBtn.addEventListener("click", async () => {
  const sid = sensorSel.value;
  const win = windowSel.value;
  if (!sid) { sensorOut.textContent = "Pick a sensor first."; return; }

  queryBtn.disabled = true;
  sensorOut.textContent = `Querying ${sid} (window=${win})…`;
  try {
    const url = `/api/sensor?sensor_id=${encodeURIComponent(sid)}&window=${encodeURIComponent(win)}`;
    const data = await api(url);
    const pretty = JSON.stringify(data, null, 2);
    sensorOut.textContent = pretty;
  } catch (e) {
    sensorOut.textContent = "[query error] " + e.message;
  } finally {
    queryBtn.disabled = false;
  }
});

// Optional: auto-load sensors on first paint
window.addEventListener("DOMContentLoaded", () => {
  listBtn.click();
});
