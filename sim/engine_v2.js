<script id="sim-engine">
/* ===========================================================================
 * 시뮬레이터 v2 엔진 — 피처(실효 공정값)가 GPC·균일도를 만든다. (설계: sim_v2/model.py)
 *
 *   실효 피처 = 노브 설정값 + 숨은 교란 d(t)
 *   GPC      = 1.10 + Σ 피처별 GPC 항 + 잡음
 *   균일도    = 0.90 + Σ 피처별 균일도 항 + 잡음
 *
 * 이상 = 피처 하나에 교란을 넣는 것. 노브를 누르면 실효 피처가 바뀌어 같은 식으로 지표가 움직인다.
 * 화면(app 블록)은 v1 과 같은 API(Sim·tick·view·gt·apply·hitTest)만 쓴다.
 * =========================================================================== */
(function (root) {
"use strict";

const DT = 0.5, WINDOW_TICKS = 1200, PREROLL_TICKS = 1200, EPISODE_TICKS = PREROLL_TICKS + 1200;
const CHART_POINTS = 120, ACTION_DWELL_S = 30;
const GPC_BASE = 1.10, GPC_BAND = [1.05, 1.15], U_BASE = 0.90, U_BAND = [0.50, 1.30];
const GPC_NOISE = 0.006, U_NOISE = 0.02, OSC_PERIOD_S = 40;

const KNOBS = {
  temp:  { base: 255,  step: 5,    min: 230,  max: 280,  dp: 0, unit: "°C",   label: "온도" },
  press: { base: 1.4,  step: 0.1,  min: 0.8,  max: 2.2,  dp: 1, unit: "Torr", label: "압력" },
  pulse: { base: 0.10, step: 0.01, min: 0.04, max: 0.20, dp: 2, unit: "s",    label: "펄스" },
  purge: { base: 4.5,  step: 0.5,  min: 2.0,  max: 9.0,  dp: 1, unit: "s",    label: "퍼지" },
  flow:  { base: 225,  step: 25,   min: 100,  max: 400,  dp: 0, unit: "sccm", label: "유량" }
};
const KNOB_ORDER = ["temp", "press", "pulse", "purge", "flow"];
// 정상 범위(공정 창). 창 안에서는 지표가 조금만 움직이고, 하한·상한을 넘으면 가파르게 나빠진다.
const WINDOW = { temp: [245, 265], press: [1.2, 1.6], pulse: [0.08, 0.14], purge: [3.5, 6.0], flow: [175, 300] };
const CORRECTION_LIMIT = { temp: 265, press: 1.6, pulse: 0.14, purge: 6.0, flow: 300 };   // 화면의 '상한' = 창 위쪽 끝
function limitOf(k) { return WINDOW[k][1]; }

// 이상 = 교란이 들어가는 피처. normal 은 교란 없음
const FAULT_TYPES = ["normal", "temp", "purge", "pulse", "press", "flow"];
const MECHANISM = {
  normal: "정상 — 교란 없음",
  temp:   "온도 — 벽 증착 누적으로 실효 온도가 서서히 떨어짐",
  purge:  "퍼지 — 배기 밸브 이상으로 퍼지 효율이 갑자기 떨어짐",
  pulse:  "펄스 — 버블러 고갈로 30초 뒤부터 전구체 공급이 꺾이며 줄어듦",
  press:  "압력 — 배기 제어 불안정으로 압력이 40초 주기로 흔들리며 커짐",
  flow:   "유량 — MFC 드리프트로 운반 유량이 줄어듦"
};
// 맞는 조치: 교란 피처를 되돌리는 방향
const FIX = { temp: "temp_up", purge: "purge_up", pulse: "pulse_up", press: "press_down", flow: "flow_up" };

function smooth(x) { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); }
/** 숨은 교란 d(s). s = 주입 후 초 */
/** 숨은 교란 d(s). s = 주입 후 초. 실제값을 하한(압력은 양쪽 한계) 쪽으로 끌고 가서 넘긴다 */
function disturb(fault, s) {
  if (s < 0) return 0;
  switch (fault) {
    case "temp":  return -Math.min(30, 20 * s / 200);                 // 255 → 245(하한) 100초 → 235(150초)
    case "purge": return -2.0 * (1 - Math.exp(-s / 5));               // 4.5 → 2.5 (하한 3.5 아래로 급락)
    case "pulse": return -0.04 * smooth((s - 30) / 120);              // 0.10 → 0.06 (하한 0.08 아래로 꺾여 내려감)
    case "press": return 0.24 * (1 - Math.exp(-s / 60));              // 1.4 ± 0.24 → 1.16~1.64 (양쪽 한계를 오감)
    case "flow":  return -100 * (1 - Math.exp(-s / 40));              // 225 → 125 (하한 175 아래로)
    default:      return 0;
  }
}
const lo = function (k, v) { return Math.max(0, WINDOW[k][0] - v); };   // 하한을 넘은 만큼
const hi = function (k, v) { return Math.max(0, v - WINDOW[k][1]); };   // 상한을 넘은 만큼
/** 피처 → 지표 항. 창 안 = 완만한 기울기(버튼을 누르면 보이는 정도), 창 밖 = 가파른 기울기 */
function gpcTerms(e, amp, tS) {
  return {
    temp:  -0.002 * (e.temp - 255) + 0.008 * lo("temp", e.temp) - 0.006 * hi("temp", e.temp),   // 하한 아래: 응축 → GPC↑, 상한 위: 탈착 → GPC↓
    purge:  0.02 * Math.max(0, 4.5 - e.purge) + 0.10 * lo("purge", e.purge),                      // 퍼지 부족 → 잔류 가스 CVD → GPC↑ (넉넉하면 포화)
    pulse: -1.0 * Math.max(0, 0.10 - e.pulse) - 5.0 * lo("pulse", e.pulse),                       // 전구체 부족 → 미포화 → GPC↓ (넉넉하면 포화)
    press:  0.10 * (e.press - 1.4) + 0.25 * amp * Math.sin(2 * Math.PI * tS / OSC_PERIOD_S),      // 압력↑ → 체류↑ → GPC↑, 진동은 그대로 GPC 진동
    flow:   (e.flow >= 225 ? 0.0004 : 0.0003) * (e.flow - 225)
  };
}
function uTerms(e, amp) {
  return {
    temp:  0.002 * Math.abs(e.temp - 255) + 0.004 * lo("temp", e.temp) + 0.03 * hi("temp", e.temp),
    purge: 0.05 * Math.max(0, 4.5 - e.purge) + 0.40 * lo("purge", e.purge) - 0.02 * Math.max(0, e.purge - 4.5),
    pulse: 0.5 * Math.max(0, 0.10 - e.pulse) + 3.0 * lo("pulse", e.pulse) + 2.0 * Math.max(0, e.pulse - 0.10) + 4.0 * hi("pulse", e.pulse),
    press: 1.0 * amp + 0.3 * Math.abs(e.press - 1.4) + 1.0 * (lo("press", e.press) + hi("press", e.press)),
    flow:  0.002 * Math.max(0, 225 - e.flow) + 0.007 * lo("flow", e.flow) + 0.0012 * Math.max(0, e.flow - 225) + 0.005 * hi("flow", e.flow)
  };
}
const sum = function (o) { let s = 0; for (const k in o) s += o[k]; return s; };

function mulberry32(a) {
  return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

function Sim(opts) {
  opts = opts || {};
  this.seed = opts.seed || 1; this.faultType = FAULT_TYPES.indexOf(opts.faultType) >= 0 ? opts.faultType : "normal";
  this.injectTick = opts.injectTick != null ? opts.injectTick : PREROLL_TICKS;
  this.rand = mulberry32(this.seed);
  const r = this.rand; let spare = null;
  this.gauss = function () { if (spare !== null) { const s = spare; spare = null; return s; }
    let u = 0, v = 0; while (u === 0) u = r(); v = r(); const m = Math.sqrt(-2 * Math.log(u));
    spare = m * Math.sin(2 * Math.PI * v); return m * Math.cos(2 * Math.PI * v); };
  this.t = 0; this.clockS = 9 * 3600 + Math.floor(this.rand() * 3600);
  this.knobs = {}; this.knobSeries = {}; this.effSeries = {};
  for (const k of KNOB_ORDER) { this.knobs[k] = KNOBS[k].base; this.knobSeries[k] = []; this.effSeries[k] = []; }
  this.gpcSeries = []; this.uSeries = []; this.actionLog = []; this.pending = null;
  this.wobG = 0; this.wobU = 0; this.cleanRequested = false;
  this.state();
}

/** 지금 노브·교란으로 실효 피처와 지표(잡음 없는 값)를 계산한다. */
Sim.prototype.state = function () {
  const s = (this.t - this.injectTick) * DT, d = disturb(this.faultType, s);
  const e = Object.assign({}, this.knobs);
  if (this.faultType !== "press" && this.faultType !== "normal") e[this.faultType] += d;
  const amp = this.faultType === "press" ? d * Math.min(1, Math.max(0, (this.knobs.press - 1.2) / 0.2)) : 0;
  const tg = gpcTerms(e, amp, this.t * DT), tu = uTerms(e, amp);
  this.dist = d; this.eff = e; this.amp = amp; this.termsG = tg; this.termsU = tu;
  this.gpcTrue = GPC_BASE + sum(tg); this.uTrue = U_BASE + sum(tu);
};

/** 화면에 보여 줄 실효 피처 — 압력은 진동 진폭만큼 실제로 흔들린다 */
Sim.prototype.effView = function () {
  const e = Object.assign({}, this.eff);
  e.press = this.knobs.press + this.amp * Math.sin(2 * Math.PI * this.t * DT / OSC_PERIOD_S);
  return e;
};

Sim.prototype.tick = function () {
  this.t++; this.clockS += DT;
  this.state();
  this.wobG = 0.985 * this.wobG + this.gauss() * 0.0018;
  this.wobU = 0.985 * this.wobU + this.gauss() * 0.0057;
  this.gpcDisplay = this.gpcTrue + this.wobG + this.gauss() * GPC_NOISE;
  this.uDisplay = this.uTrue + this.wobU + this.gauss() * U_NOISE;
  this.gpcSeries.push(this.gpcDisplay); this.uSeries.push(this.uDisplay);
  const ev = this.effView();
  for (const k of KNOB_ORDER) { this.knobSeries[k].push(this.knobs[k]); this.effSeries[k].push(ev[k]); }
  if (this.pending) {
    this.pending.remainingS -= DT;
    if (this.pending.remainingS <= 0) this.settle();
  }
};

/** 대기 끝: 대역까지의 거리가 줄었는지로 결과를 적는다. */
Sim.prototype.settle = function () {
  const p = this.pending, e = this.actionLog[p.logIndex];
  // 목표값(1.10 / 0.90)까지의 거리 — 대역 안에서 움직여도 나아졌는지 보인다 (균일도는 GPC 의 약 3배로 움직여 1/3 로 맞춘다)
  const dist = function (g, u) { return Math.abs(g - GPC_BASE) + Math.max(0, u - U_BASE) / 3; };
  const before = dist(p.gpcAtPress, p.uAtPress), after = dist(this.gpcTrue, this.uTrue);
  const ampGain = p.ampAtPress - this.amp;
  e.status = "완료";
  e.outcome = (before - after > 0.008 || ampGain > 0.02) ? "개선" : (after - before > 0.008 ? "악화" : "변화 없음");
  this.pending = null;
};

Sim.prototype.clockStr = function () {
  const s = Math.floor(this.clockS % 86400), two = function (n) { return String(n).padStart(2, "0"); };
  return two(Math.floor(s / 3600)) + ":" + two(Math.floor((s % 3600) / 60)) + ":" + two(s % 60);
};

Sim.prototype.apply = function (actionId) {
  if (!actionId || actionId === "noop") return { ok: true, applied: "noop" };
  const base = { tick: this.t, time: this.clockStr(), id: actionId, outcome: "" };
  const pend = (idx) => { this.pending = { id: actionId, remainingS: ACTION_DWELL_S, gpcAtPress: this.gpcTrue,
                                          uAtPress: this.uTrue, ampAtPress: this.amp, logIndex: idx }; };
  if (actionId === "request_clean") {
    this.cleanRequested = true;
    pend(this.actionLog.push(Object.assign(base, { text: "클리닝 요청", mark: "클리닝", status: "접수" })) - 1);
    return { ok: true, applied: actionId };
  }
  const btn = COORDS.buttons[actionId];
  if (!btn || !btn.knob) return { ok: false, reason: "unknown action: " + actionId };
  const spec = KNOBS[btn.knob], rawV = this.knobs[btn.knob] + btn.dir * spec.step;
  const next = Math.min(spec.max, Math.max(spec.min, rawV));
  this.knobs[btn.knob] = +(Math.round(next / spec.step) * spec.step).toFixed(4);
  const hitLimit = Math.abs(next - rawV) > 1e-9, sign = btn.dir > 0 ? "+" : "−";
  pend(this.actionLog.push(Object.assign(base, { text: spec.label + " " + sign + spec.step.toFixed(spec.dp),
    mark: spec.label + sign, status: hitLimit ? "한계" : "대기" })) - 1);
  this.state();
  return { ok: true, applied: actionId, hitLimit: hitLimit };
};

Sim.prototype.hitTest = function (x, y) {
  for (const id in COORDS.buttons) {
    const b = COORDS.buttons[id];
    if (x >= b.x - b.w / 2 && x <= b.x + b.w / 2 && y >= b.y - b.h / 2 && y <= b.y + b.h / 2) return id;
  }
  return null;
};

const TOL_G = 0.03, TOL_U = 0.15;   // 잡음(σ GPC 0.006 · 균일도 0.02)의 5배 이상이어야 '화면에 보인다'
/** 정답 조치. 교란 피처의 영향이 화면에 보일 만큼이면 그 피처를 되돌린다. 아니면 엉뚱하게 바꿔 둔 노브를 되돌린다. */
Sim.prototype.correctAction = function () {
  if (this.pending) return "noop";
  const f = this.faultType;
  if (f !== "normal" && this.t >= this.injectTick) {
    const g = this.termsG[f], u = this.termsU[f];
    const vis = f === "press" ? this.amp * 0.25 > 0.02 : (Math.abs(g) > TOL_G || u > TOL_U);
    if (vis) {
      if (f === "temp" && g < -TOL_G) return "temp_down";        // 온도를 너무 올려 반대로 넘어감
      return FIX[f];
    }
  }
  for (const k of KNOB_ORDER) {                                 // 교란 피처가 아닌데 바꿔 둔 노브
    if (k === f || this.knobs[k] === KNOBS[k].base) continue;
    if (Math.abs(this.termsG[k]) > TOL_G / 2 || this.termsU[k] > TOL_U / 2) return k + (this.knobs[k] > KNOBS[k].base ? "_down" : "_up");
  }
  return "noop";
};

Sim.prototype.rationale = function () {
  if (this.pending) return "직전 조치가 반영되는 중이다. 결과를 기다린다.";
  const a = this.correctAction();
  return MECHANISM[this.faultType] + (a === "noop" ? " — 조치 불필요." : " — " + a + " 필요.");
};

function downsample(series, points, windowTicks) {
  const start = Math.max(0, series.length - windowTicks), win = series.slice(start), out = [], n = win.length;
  if (n === 0) return out;
  const bucket = Math.max(1, Math.ceil(windowTicks / points));
  for (let i = 0; i < n; i += bucket) {
    const end = Math.min(i + bucket, n); let s = 0, lo = Infinity, hi = -Infinity;
    for (let j = i; j < end; j++) { const v = win[j]; s += v; if (v < lo) lo = v; if (v > hi) hi = v; }
    out.push({ v: s / (end - i), lo: lo, hi: hi, tick: start + i });
  }
  return out;
}
function downsampleStep(series, points, windowTicks) {
  const start = Math.max(0, series.length - windowTicks), win = series.slice(start), out = [], n = win.length;
  const bucket = Math.max(1, Math.ceil(windowTicks / points));
  for (let i = 0; i < n; i += bucket) out.push({ v: win[Math.min(i + bucket, n) - 1], tick: start + i });
  return out;
}

Sim.prototype.view = function (windowTicks, points) {
  const W = windowTicks || WINDOW_TICKS, NP = points || CHART_POINTS;
  const winStart = Math.max(0, this.gpcSeries.length - W), knobPoints = {};
  const effPoints = {};
  for (const k of KNOB_ORDER) { knobPoints[k] = downsampleStep(this.knobSeries[k], NP, W); effPoints[k] = downsample(this.effSeries[k], NP, W); }
  return {
    t: this.t, clock: this.clockStr(), gpc: this.gpcDisplay, uniformity: this.uDisplay,
    gpcPoints: downsample(this.gpcSeries, NP, W), uPoints: downsample(this.uSeries, NP, W),
    knobPoints: knobPoints, knobs: Object.assign({}, this.knobs), effPoints: effPoints, eff: this.effView(), oscAmp: this.amp,
    markers: this.actionLog.filter(function (e) { return e.tick >= winStart; })
                           .map(function (e) { return { frac: (e.tick - winStart) / W, mark: e.mark }; }),
    pending: this.pending ? { id: this.pending.id, remainingS: Math.max(0, this.pending.remainingS) } : null,
    log: this.actionLog.slice(-8).reverse(), windowTicks: W, seriesLen: this.gpcSeries.length
  };
};

const r4 = function (o) { const out = {}; for (const k in o) out[k] = +(+o[k]).toFixed(4); return out; };
Sim.prototype.gt = function () {
  return {
    t: this.t, seed: this.seed, fault_type: this.faultType, inject_tick: this.injectTick,
    gpc_true: +this.gpcTrue.toFixed(4), gpc_display: +(this.gpcDisplay ?? this.gpcTrue).toFixed(4),
    uniformity_true: +this.uTrue.toFixed(4), uniformity: +(this.uDisplay ?? this.uTrue).toFixed(4),
    knobs: Object.assign({}, this.knobs), disturbance: +this.dist.toFixed(4), effective: r4(this.eff),
    osc_amp: +this.amp.toFixed(4), terms_gpc: r4(this.termsG), terms_u: r4(this.termsU),
    correct_action: this.correctAction(), rationale: this.rationale(),
    pending_action: this.pending ? { id: this.pending.id, remaining_s: +this.pending.remainingS.toFixed(1) } : null
  };
};

root.SIM = {
  Sim: Sim, downsample: downsample, limitOf: limitOf, disturb: disturb, gpcTerms: gpcTerms, uTerms: uTerms,
  DT: DT, WINDOW_TICKS: WINDOW_TICKS, PREROLL_TICKS: PREROLL_TICKS, EPISODE_TICKS: EPISODE_TICKS,
  CHART_POINTS: CHART_POINTS, ACTION_DWELL_S: ACTION_DWELL_S,
  GPC_BASE: GPC_BASE, GPC_BAND: GPC_BAND, U_BASE: U_BASE, U_BAND: U_BAND,
  KNOBS: KNOBS, KNOB_ORDER: KNOB_ORDER, CORRECTION_LIMIT: CORRECTION_LIMIT, WINDOW: WINDOW,
  FAULT_TYPES: FAULT_TYPES, MECHANISM: MECHANISM, FIX: FIX
};
if (typeof module !== "undefined") module.exports = root.SIM;
})(typeof window !== "undefined" ? window : globalThis);
</script>
