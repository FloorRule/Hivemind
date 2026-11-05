import { connectWS } from "/static/shared/ws.js";
import { startGame, finishGame, setScore } from "./game.js";

const opId = new URLSearchParams(location.search).get("id")
  || "operator_alpha_01";
document.getElementById("callsign").textContent = opId.toUpperCase();
let gameRunning = false;

const sock = connectWS(`ws://${location.host}/ws/operator/${opId}`, {
  onMsg: m => {
    if (m.type === "telemetry_update") {
      document.getElementById("state").textContent = m.state;
      document.getElementById("score").textContent = m.stress_score ?? "CAL";
      setScore(m.stress_score);
    } else if (m.type === "warning_notice") {
      document.getElementById("toast").style.display = "block";
    } else if (m.type === "state_override") {
      if (m.command === "TRIGGER_INTERVENTION" && !gameRunning) {
        gameRunning = true;
        document.documentElement.requestFullscreen?.().catch(() => {});
        document.getElementById("game").style.display = "block";
        startGame("game", () => sock.send({ type: "client_ready" }));
      } else if (m.command === "END_INTERVENTION" && gameRunning) {
        gameRunning = false;
        finishGame(() => {   // overlay done -> restore UI
          document.exitFullscreen?.().catch(() => {});
          document.getElementById("game").style.display = "none";
          document.getElementById("toast").style.display = "none";
        });
      }
    }
  } });
