import { connectWS } from "/static/shared/ws.js";

const grid = document.getElementById("grid");
const conn = document.getElementById("conn");
const simbadge = document.getElementById("simbadge");
const alertlog = document.getElementById("alertlog");
const cards = {};
const lastState = {};
let simOn = false;      // S-toggle polarity; reconciled from m.sim each batch

const STATE_COLOR = {
  baseline: "#94a3b8", nominal: "#22c55e", warning: "#f59e0b",
  intervention: "#ef4444", recovery: "#22d3ee", signal_lost: "#a1a1aa",
};

function logAlert(callsign, from, to) {
  const d = document.createElement("div");
  const color = STATE_COLOR[to] || "#e6edf7";
  d.innerHTML = `<span class="dim">${new Date().toLocaleTimeString()}</span>
    <b>${callsign}</b> <span style="color:${color}">${from} → ${to}</span>`;
  alertlog.prepend(d);
  while (alertlog.children.length > 60) alertlog.lastChild.remove();
}

function card(op) {
  const d = document.createElement("div");
  d.className = "panel"; d.dataset.op = op.user_id;
  d.innerHTML = `
    <div class="flex items-center justify-between">
      <b>${op.callsign}</b>
      <span class="badge baseline" data-b>baseline</span>
    </div>
    <div class="score" data-score style="margin:8px 0">—</div>
    <canvas width="220" height="44" data-spark style="width:100%"></canvas>
    <div class="dim" data-bands style="margin:6px 0">α — · β —</div>
    <div class="flex gap-2">
      <button data-cmd="TRIGGER_INTERVENTION">Trigger</button>
      <button data-cmd="END_INTERVENTION">End</button>
      <button data-cmd="RESET">Reset</button>
    </div>`;
  d.querySelectorAll("button").forEach(b =>
    b.onclick = () => sock.send({ type: "manual_override",
      user_id: op.user_id, command: b.dataset.cmd }));
  grid.appendChild(d);
  return d;
}

function drawSpark(canvas, points, state) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "rgba(96,165,250,0.25)";
  [20, 45, 65, 80].forEach(v => {
    const y = canvas.height - (v / 100) * canvas.height;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  });
  if (!points.length) return;
  ctx.strokeStyle = STATE_COLOR[state] || "#60a5fa";
  ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((v, i) => {
    const x = (i / 119) * canvas.width;
    const y = canvas.height - (v / 100) * canvas.height;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

fetch("/api/operators").then(r => r.json())
  .then(ops => ops.forEach(op => {
    cards[op.user_id] = card(op);
    lastState[op.user_id] = null;   // seeded from the first telemetry frame
  }));

const sock = connectWS(`ws://${location.host}/ws/command`, {
  onStatus: s => { conn.textContent = s; },
  onMsg: m => {
    if (m.type !== "telemetry_batch") return;
    simbadge.style.display = m.sim ? "inline-block" : "none";
    simOn = !!m.sim;
    for (const op of m.operators) {
      const d = cards[op.user_id]; if (!d) continue;
      if (lastState[op.user_id] !== op.state) {
        if (lastState[op.user_id] !== null)    // first frame seeds silently
          logAlert(op.callsign, lastState[op.user_id], op.state);
        lastState[op.user_id] = op.state;
      }
      d.querySelector("[data-score]").textContent =
        op.stress_score ?? "CAL";
      d.querySelector("[data-score]").style.color =
        STATE_COLOR[op.state] || "#e6edf7";
      const b = d.querySelector("[data-b]");
      b.textContent = op.state; b.className = `badge ${op.state}`;
      d.classList.toggle("amber", !!op.amber);
      d.querySelector("[data-bands]").textContent =
        `α ${op.alpha_power.toPrecision(3)} · β ${op.beta_power.toPrecision(3)}`
        + (op.valid ? "" : " · ARTIFACT");
      drawSpark(d.querySelector("[data-spark]"), op.spark, op.state);
    }
  } });

addEventListener("keydown", e => {
  if (e.key.toLowerCase() === "s") {
    simOn = !simOn;   // flip immediately: rapid taps alternate, no dead press
    sock.send({ type: "sim_mode", enabled: simOn });
  }
});
