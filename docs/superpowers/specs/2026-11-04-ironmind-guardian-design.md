# IronMind Guardian — Design Specification

**Date:** 2026-11-04
**Status:** Approved design, pre-implementation
**Event context:** 24h hackathon — theme "Resilient Mind in Emergency Times"
**Derived from:** Blueprint v2 (multi-user command-center revision) + brainstorming session corrections

---

## 1. What We Are Building

IronMind Guardian is a real-time, multi-user operational telemetry and closed-loop
neurofeedback system:

1. Reads field personnel's brain activity via consumer EEG headset (Muse 2) streaming
   into a laptop via Bluetooth LE.
2. Aggregates telemetry from **multiple operators** (one real headset + N synthetic
   squadmates) into a live **Command Center** dashboard.
3. Detects rising anxiety before peak using a rolling alpha/high-beta ratio, scored
   against each operator's own baseline.
4. Executes a tiered escalation ladder: nominal → edge warning → backend-forced
   fullscreen neurofeedback exercise on the operator's device.
5. The operator controls the exercise with their own brainwaves; it closes itself on
   normalization.

Demo shape: one presenter wearing the real headset (operator slot `operator_alpha_01`),
plus synthetic squadmates, on the teammate's laptop, projected Command Center,
presenter's phone showing the operator PWA. **Default roster: 5 operators total
(1 real slot + 4 synthetic), configurable 1–8** via `config.yaml`.

## 2. Problem & Framing

In the first 30–90 seconds of rising distress, a person stays functional or collapses.
Commanders have zero visibility into team cognitive load until explicit breakdown.
Existing tools are reactive (already-overwhelmed → then calm down).

IronMind Guardian is proactive: early detection + command awareness + closed-loop
intervention extends the window of functional resilience.

**Honest-science framing (pitch requirement):** the stress score is a *cortical-arousal
indicator* derived from the alpha/high-beta power ratio — a stress *indicator*, not a
diagnosis. PITCH.md carries a science-questions cheat sheet; no over-claims.

## 3. Architecture

Single demo laptop, one Python process, browser tabs for both frontends:

```
                    DEMO LAPTOP (single machine, one Python process + browser tabs)
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Sim #1: N synthetic operator EEG streams]──┐                               │
│                                              ├──LSL──► ┌──────────────────┐  │
│  [Real Muse 2]──BLE──► [muselsl/bleak]───────┘         │  PYTHON HUB      │  │
│   (presenter wears this)                               │  (FastAPI)       │  │
│                                                        │  • DSP pipeline  │  │
│   Projector ──► /command  Command Center (plain JS) ◄──┤  • Escalation    │  │
│   Phone ──────► /operator Operator PWA (p5.js)    ◄────┤    ladder engine │  │
│   Any browser ─► manual override controls         ────►│  • WS fan-out +  │  │
│                                                        │    command router│  │
│                                                        │  • SQLite/CSV log│  │
│                                                        └──────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

- EEG acquisition (BLE) happens on the laptop — `muselsl`/`bleak` cannot run on
  phones. The phone is a **browser PWA** served by the hub over LAN (venue wifi
  client-isolation risk handled per §9).
- All processing is centralized in the hub (one place to debug in 24h).
- Both frontends are static files served by the hub: plain JS + p5.js + Tailwind CDN.
  Zero build step. The demo laptop runs **one process**.

### Target machine (confirmed 2026-11-04)

Lenovo `LENOVO-R90R8880`: i7-8550U (4C/8T), 8 GB RAM, Intel UHD 620 integrated GPU,
238 GB SSD, Windows x64. **Performance budget derived from it:** hub + DSP is
negligible load (<5% CPU expected); the binding constraint is the integrated GPU —
the bio-game runs **p5.js 2D canvas mode only** (no WebGL/shaders), particle budget
≤300, tuned for 1080p projection. All Python deps pinned to win_amd64 wheels
(Python 3.12 x64); bleak handles the laptop's built-in Bluetooth on Windows.

## 4. Components

Each unit has one purpose, is independently testable, and communicates through
defined interfaces:

| Unit | File(s) | Does | Depends on |
|---|---|---|---|
| Source adapter | `backend/sources/sim_source.py`, `backend/sources/muse_source.py` | Produces EEG at the LSL boundary: synthetic N-operator generator, or real Muse inlet. Identical stream metadata either way (`name="EEG"`, Muse channel labels, 256 Hz) | pylsl; muselsl (real only) |
| DSP | `backend/dsp.py` | Notch (50/60Hz) → bandpass (1–40Hz) → artifact rejection (amplitude thresholds; median across channels) → Welch PSD → alpha/high-beta powers → score 0–100 with per-user baseline calibration | numpy, scipy |
| Escalation engine | `backend/engine.py` | Per-operator state machine NOMINAL→WARNING→INTERVENTION→RECOVERY with sustained-window hysteresis; emits `state_override` commands; handles SIGNAL_LOST failover | dsp output |
| Hub | `backend/hub.py`, `backend/main.py` | WebSocket manager, telemetry fan-out @10Hz, command routing, serves both frontends as static files, `/health` endpoint, SQLite/CSV logging | fastapi, uvicorn |
| Command Center | `static/command/` | Operator card grid (score, sparkline, state badge, alert log), manual trigger/end/reset buttons per operator, hidden `S` global-sim-mode toggle | Tailwind CDN, p5.js |
| Operator client | `static/operator/` | Status view → warning toast → forced fullscreen p5.js bio-game on `TRIGGER_INTERVENTION`; sends `client_ready`; self-closes on normalization; WS auto-reconnect; screen wake-lock. Game is 2D canvas mode, ≤300 particles (UHD 620 budget) | p5.js |
| Scenarios | `backend/scenarios/*.yaml` | Per-operator stress timelines; the demo script written as data | — |
| Config | `backend/config.yaml` | All thresholds, windows, operator roster, port — nothing hardcoded | — |

### Repo layout

```
ironmind-guardian/
├── main.py             # thin root entrypoint: python main.py --source sim|muse --scenario X
├── backend/            # hub, engine, dsp, sources/, scenarios/, logging, config.yaml
├── static/
│   ├── command/        # plain JS — teammate's editing zone, save+refresh
│   ├── operator/
│   └── shared/         # WS reconnect helper, theme
├── scripts/            # bootstrap.sh, selftest.sh, doctor.sh, packet_replay.py
├── tests/              # pytest: dsp, engine, protocol
├── docs/               # RUNBOOK.md (venue checklist), PITCH.md, HANDOFF.md
└── README.md
```

## 5. Protocol

All JSON over WebSocket, tagged by `type`. v2 message shapes preserved verbatim
(`telemetry_update`, `state_override` fields unchanged); dashboard traffic batched.

| Channel | Direction | Messages |
|---|---|---|
| LSL (in-process) | source → hub | raw EEG samples via pylsl inlet — WS starts after DSP |
| `/ws/command` | hub → Command Center | `telemetry_batch` @10Hz: all operators' `{user_id, stress_score, alpha_power, beta_power, status, state, history[]}` |
| `/ws/command` | Command Center → hub | `manual_override {user_id, command: TRIGGER_INTERVENTION \| END_INTERVENTION \| RESET}` |
| `/ws/command` | Command Center → hub | `sim_mode {enabled}` (the `S` toggle) |
| `/ws/operator/{id}` | hub → client | `warning_notice`, `state_override {user_id, command: TRIGGER_INTERVENTION \| END_INTERVENTION, target_score}`. Operator identity via URL: `/operator/?id=operator_alpha_01` |
| `/ws/operator/{id}` | client → hub | `client_ready`, `game_state {playing, recovered}`, `heartbeat` |

Schema rules: unknown `type` → rejected with error frame; malformed JSON → connection
kept, error logged; every frame carries `proto_v` version field.

## 6. Escalation Ladder & Stress Score

**Stress score (0–100):** per-operator. Bands: **α = 8–12 Hz, high-β = 18–30 Hz**
(scored); the wire field keeps v2's name `beta_power` for blueprint compatibility.
First 60s of stream = personal baseline. Score = scaled z-score of current β/α ratio
vs baseline, clamped 0–100. Rationale:
absolute band power varies by head, headset, and contact quality; a fixed threshold
calibrated at home misfires on-stage. Same code path for real and synthetic operators
(every scenario includes a baseline phase).

**State machine (per operator), defaults in config.yaml:**

```
NOMINAL ──(score ≥ 65 sustained 8s)──────────────► WARNING      (card yellow, phone toast)
WARNING ──(score ≥ 80 sustained 10s)─────────────► INTERVENTION (card red, game forced fullscreen)
WARNING ──(score < 55 sustained 15s)─────────────► NOMINAL      (hysteresis, no flapping)
INTERVENTION ──(score ≤ 45 sustained 6s)─────────► RECOVERY     (game self-closes, card cyan)
RECOVERY ──(15s grace)───────────────────────────► NOMINAL
ANY ──(commander override)───────────────────────► forced transition
ANY ──(signal silent > 5s)───────────────────────► SIGNAL_LOST  (grey badge → auto-failover to scenario)
```

Every number lives in `config.yaml`; tuned at rehearsal, never edited in code.

**Intervention contract:** hub never assumes the game opened. Client acks
`client_ready` after entering fullscreen; no ack within 5s → one retry → amber card
border (commander sees delivery status at all times).

**Data flow lap:** LSL samples → 4s ring buffer → DSP @2Hz per operator → engine
evaluates transitions → hub broadcasts batch + targeted operator messages → game
response feeds back into the user's actual physiology (the loop closes biologically)
→ SQLite appends every transition + 1Hz score snapshots.

## 7. Simulation Strategy (no hardware required)

**Sim #1 — synthetic EEG at the LSL boundary** (`sources/sim_source.py`): N virtual
operators, 5 channels @256Hz (4 EEG positions TP9/AF7/AF8/TP10 + AUX, matching
muse-lsl's stream shape), real-Muse stream metadata. Signal = 10Hz alpha carrier
(amplitude follows scenario) + 22Hz beta carrier (inverse-coupled) + pink noise floor
+ artifact library (blink spikes frontal-only, jaw-clench broadband bursts, motion
spikes). Seeded RNG per scenario → deterministic runs; tests assert intervention fires
within scripted windows.

**Scenarios = the demo script as data.** Example pitch scenario: baseline 60s →
stress ramp to 0.85 over 30s → hold until intervention → recovery ramp on game-ack.
Squadmates loop calm/drift/spike/recover patterns.

**Sim #2 — packet replay at the WS boundary** (`scripts/packet_replay.py`): recorded
telemetry JSON re-streamed into the frontends; frontend iteration at full speed with
no backend; same mechanism powers the last-resort fallback demo.

**Real-headset swap:** `python main.py --source muse` vs `--source sim`. One flag,
identical downstream code. If the borrowed headset arrives late, nothing is blocked.

## 8. Testing

| Layer | Tool | Asserts |
|---|---|---|
| DSP unit | pytest | pure 10Hz sine in → alpha power dominant; blink burst → rejected, not scored; ratio→score math exact |
| Engine | pytest + scenario fixtures | every transition fires at scripted time; no flapping (score parked at 64.9/65.1 never oscillates states) |
| Protocol | pytest | schema round-trip; unknown `type` rejected; malformed JSON can't crash hub |
| E2E smoke | `scripts/selftest.sh` | boots hub in sim mode headless, WS client asserts: scores stream, WARNING/INTERVENTION at scripted t, game-ack path, `S`-mode source swap without WS drop |
| Human rehearsal | video call | same script watched on the teammate's actual laptop |

`selftest.sh` is the teammate's go/no-go gate: all-green on venue laptop ⇒ demo cannot
fail for software reasons.

## 9. Demo Safety Nets

1. **`S`-key global sim mode** — swaps live source → scripted scenario mid-demo,
   instantly, without dropping any WebSocket.
2. **Commander override buttons** — trigger/end/reset any operator manually; real
   feature, demo steering wheel, and accessibility path.
3. **SIGNAL_LOST auto-failover** — BLE dies → 5s silence detects it (§6) → grey badge
   (honest telemetry) → 2s later the hub failovers that operator to its scenario
   automatically. Demo cannot deadlock.
4. **WS auto-reconnect** — exponential backoff, silent, both frontends.
5. **Last resort** — recorded full-demo packet replay via Sim #2, still
   interactive-looking.
6. **Phone optional** — entire demo runs on the laptop alone; phone is garnish.

## 10. Team Workflow

- People: **user** (remote, prompts the AI builder), **AI** (builds backend/tests/
  scripts, reviews frontend), **teammate** (on-site, presenter/face, may edit frontend).
- Single repo; `main` always demo-capable; AI merges only after `selftest.sh` green.
- Ownership boundary = file layout: `static/` teammate, `backend/`+`tests/`+`scripts/`
  AI. Neither blocks the other.
- AI polls teammate's pushes via `gh` CLI; keeps `docs/HANDOFF.md` describing what
  changed and what to pull — teammate never reads raw diffs.
- Remote diagnosis: teammate pastes `scripts/doctor.sh` output (hub health, WS client
  states, LSL status, last 50 log lines, browser hints). One command, full picture.
- GitHub repo to be created before P4 handover (name: `ironmind-guardian`).

## 11. Build-Out Timeline (pre-event)

| Phase | Deliverable | Exit gate |
|---|---|---|
| P0 — vertical slice | Hub + sim source + minimal command grid + operator page, end-to-end | scores flow to both frontends in one `python main.py` |
| P1 — real math | DSP + calibration + escalation engine | pytest DSP/engine suites green incl. no-flap |
| P2 — demo polish | Full game visuals, sparklines/alert log, pitch scenario files | full scripted run watched on video, twice |
| P3 — real-Muse path | `muse_source.py` + pairing guide + calibration workflow | if headset available: one home session proves the swap |
| P4 — handover pack | `bootstrap.sh`, `doctor.sh`, `RUNBOOK.md`, rehearsal call | teammate completes full dress rehearsal solo, unassisted |
| Event day | bootstrap + rehearsal; AI on standby (GitHub + call) | — |

## 12. Corrections Applied to Blueprint v2

1. **Phone-BLE edge → laptop BLE + phone browser PWA.** muselsl/bleak cannot run on
   phones; Muse→phone requires a native SDK (weeks + approvals). Visually identical
   on stage.
2. **React×2 + Tailwind-via-npm → plain JS + Tailwind CDN + p5.js**, served by the
   hub. Zero build step; the demo laptop has one moving part.
3. **`mne` dropped** — scipy Welch PSD covers the need; fewer heavyweight deps.
4. **scikit-learn → threshold rules + per-user baseline calibration** — the
   blueprint's own alternative; an untrainable-in-24h model is a liability, and
   "learns your personal baseline" is the stronger pitch line.
5. **Processing centralized in the hub**, not edge-on-phones — one debug surface.
6. **Smartwatch HRV / typing cadence biometrics → out of scope** (post-MVP slide
   material only).
7. **Multi-user kept**: demo = 1 real + 4–5 synthetic operators (configurable).

## 13. Risk Register & Context Still Needed

| # | Risk | Mitigation | Needed from |
|---|---|---|---|
| 1 | Venue wifi client isolation — phone can't reach laptop | Windows hotspot or travel router; hub binds 0.0.0.0 | teammate confirms venue wifi policy before event |
| 2 | BLE congestion at a crowded venue | pre-pair at venue, record MAC, direct-address connect (skip scan); Muse phone app fully closed on all nearby phones | teammate, on arrival |
| 3 | Presenter physiology — talking/jaw/adrenaline pollute signal; eyes-open alpha weaker | breathing-pace game IS the calm protocol (eyes open); artifact rejection tuned for speech; rehearse while talking; silent failover to scenario if signal too noisy | rehearsal sessions |
| 4 | ~~Demo laptop unknowns~~ **RESOLVED 2026-11-04** — Lenovo i7-8550U / 8GB / UHD 620 / Win x64 | adequate for all layers; only constraint: 2D-canvas game budget (§3). Remaining unknown: BT adapter quality + HDMI, verified at first on-site pairing | — |
| 5 | Judging-criteria mismatch | align dashboard story to official rubric | teammate sends rubric during P2 |
| 6 | Neurofeedback lag — real alpha shifts take 10–30s | demo choreographed to physiology (narrative during ramp, payoff during drop); scenario file mirrors pacing | pitch script from teammate |
| 7 | Science over-claim under judge questioning | "cortical-arousal stress indicator" framing; PITCH.md cheat sheet | — |
| 8 | Borrowed headset never materializes | system is sim-complete; demo runs 100% on sim without it; real headset is an enhancement | — |

Items marked "needed from" do **not** block P0–P1; they gate P4 rehearsal quality.

## 14. Decisions Log (brainstorming session)

| Question | Decision |
|---|---|
| Hardware status | Will get/borrow a Muse ⇒ simulation-first, real headset is drop-in |
| Demo machine | Teammate's separate laptop ⇒ reproducible bootstrap + doctor script |
| Team shape | User remote + AI builds; teammate on-site presents; GitHub = coordination channel |
| Pre-event time | Yes ⇒ build & verify everything at home; on-site = pairing + calibration + rehearsal |
| Frontend stack | Plain JS + p5.js + Tailwind CDN, zero build (decided twice: single- and dual-frontend) |
| Edge device | Phone = browser PWA; BLE acquisition on laptop |
| Stress engine | Threshold rules + per-user calibration (no ML in scope) |
| Logging | SQLite + CSV export (v2 kept) |
