/* 이상 감지 함수 + 폐루프 에이전트 (시뮬레이터 v2). reader/detect_v2.py 와 같은 규칙 — parity 시험으로 확인한다.
 *
 * detect(g, u, dt): 화면 그래프 선(최근 10분, dt 초 간격)만 보고 원인 피처와 조치를 낸다.
 * Agent:            매 초 detect → 조치가 있으면 버튼을 누르고 30초 기다린다(결과 확인).
 *                   노브가 이미 끝까지 가 있으면 더 누르지 않고 클리닝을 요청한다.
 */
(function (root) {
"use strict";
const TH = { osc: 0.006, acf: 0.3, mag: 0.05 };
const TARGET = { gpc: 1.100, u: 0.900 };   // 화면 카드의 '목표'
const U_SCALE = 3.0, SIG_DEG = { temp: 6.3, purge: 51.3, flow: 98.3, pulse: 166.0 };
const KO = { temp: "온도", purge: "퍼지", flow: "유량", pulse: "펄스", press: "압력", normal: "정상" };
const REVERSE = { temp_up: "temp_down", temp_down: "temp_up", press_up: "press_down", press_down: "press_up", pulse_up: "pulse_down",
                  pulse_down: "pulse_up", purge_up: "purge_down", purge_down: "purge_up", flow_up: "flow_down", flow_down: "flow_up" };
const ACTION = { normal: "noop", temp: "temp_up", purge: "purge_up", pulse: "pulse_up", press: "press_down", flow: "flow_up" };
const mean = a => a.reduce((x, y) => x + y, 0) / a.length;

function detect(g, u, dt, ignore) {   // ignore: 내가 누른 시각들(지금 기준 초, 음수) — 진동 판정에서 ±10초를 뺀다
  const n = g.length, tAt = i => (i - (n - 1)) * dt;           // 지금 = 0초
  const seg = (a, lo, hi) => a.filter((_, i) => tAt(i) > lo && tAt(i) <= hi);
  const ng = seg(g, -20, 0), nu = seg(u, -20, 0);
  if (ng.length < 2) return { cause: "normal", action: "noop", why: "그래프가 비었다", feat: {} };
  const dg = mean(ng) - TARGET.gpc, du = mean(nu) - TARGET.u;      // 화면 카드에 적힌 목표값과 비교 (창 앞쪽은 이상 기간이 섞일 수 있다)
  const w = g.map((v, i) => [tAt(i), v]).filter(p => p[0] > -90), m = w.length;
  let sd = 0, best = 0, per = null;
  if (m >= 12) {
    const step = (w[m - 1][0] - w[0][0]) / (m - 1), h = Math.max(1, Math.round(10 / step));
    const r = w.map((p, i) => { const sl = w.slice(Math.max(0, i - h), Math.min(m, i + h + 1)); return p[1] - mean(sl.map(q => q[1])); });
    if (ignore) r.forEach((x, i) => { if (ignore.some(t => Math.abs(w[i][0] - t) <= 10)) r[i] = 0; });
    const s0 = r.reduce((x, y) => x + y * y, 0) || 1e-12;
    sd = Math.sqrt(s0 / m);
    for (let lag = Math.max(1, Math.round(25 / step)); lag <= Math.min(m - 2, Math.round(60 / step)); lag++) {
      let c = 0; for (let i = 0; i + lag < m; i++) c += r[i] * r[i + lag]; c /= s0;
      if (c > best) { best = c; per = lag * step; }
    }
  }
  const mag = Math.hypot(dg, du / U_SCALE), ang = Math.atan2(du / U_SCALE, dg) * 180 / Math.PI;
  const feat = { dgpc: dg, du: du, osc_sd: sd, osc_acf: best, period_s: per, mag: mag, angle: ang };
  const out = (c, why) => ({ cause: c, action: ACTION[c], why: why, feat: feat });
  const sg = v => (v >= 0 ? "+" : "") + v.toFixed(3);
  if (sd > TH.osc && best > TH.acf) return out("press", "GPC 가 " + Math.round(per) + "초 주기로 흔들림 (폭 " + sd.toFixed(3) + ")");
  if (mag < TH.mag) return out("normal", "GPC " + sg(dg) + ", 균일도 " + sg(du) + " — 변화가 작다");
  let c = null, cd = 1e9;
  for (const k in SIG_DEG) { const dd = Math.abs(((ang - SIG_DEG[k] + 540) % 360) - 180); if (dd < cd) { cd = dd; c = k; } }
  return out(c, "GPC " + sg(dg) + ", 균일도 " + sg(du) + " → 방향 " + Math.round(ang) + "° 가 " + KO[c] + " 지문(" + Math.round(SIG_DEG[c]) + "°)에 가장 가깝다");
}

/** 폐루프 에이전트. step(sim, 초, press) 를 시뮬레이터 1초마다 부른다. press(id) 가 버튼을 누른다(화면 경로).
 *  - 같은 판정이 15초 이어져야 누른다 (진동처럼 판정이 출렁이는 동안은 기다린다)
 *  - 누른 뒤 효과가 그래프에 드러날 때까지 기다린다 (압력 90초 = 진동 판정 창, 나머지 30초)
 *  - 기다림이 끝나면 '누른 직후 그래프가 이상 방향의 반대로 움직였나' 를 본다 (압력은 흔들림이 줄었나).
 *    같은 버튼이 두 번 연속 듣지 않으면 그동안 누른 것을 전부 되돌리고 5분 동안 그 버튼을 쓰지 않는다. */
const WAIT_S = { press_down: 90 }, HOLD_S = 15;
function unit(deg) { const r = deg * Math.PI / 180; return [Math.cos(r), Math.sin(r)]; }
function Agent(opts) { this.undo = !(opts && opts.undo === false); this.waitUntil = -Infinity; this.banned = {}; this.presses = [];
  this.streak = null; this.pending = null; this.last = null; this.lastAct = null; this.hist = []; this.log = []; }
Agent.prototype.step = function (sim, nowS, press) {
  const mine = this.presses.filter(p => nowS - p.t < 90).map(p => p.t - nowS);
  const v = sim.view(), d = detect(v.gpcPoints.map(p => p.v), v.uPoints.map(p => p.v), 5, mine);
  const note = (act, why) => (this.last = { d: d, act: act, why: why });
  const doPress = (act, cause) => { press(act); this.presses.push({ t: nowS, act: act, cause: cause }); this.lastAct = act; };
  if (nowS < this.waitUntil) return note("noop", "대기 " + Math.ceil(this.waitUntil - nowS) + "초 (" + this.lastAct + " 효과 확인 중)");
  if (this.pending) {                                         // 직전 조치의 효과 판정
    const p = this.pending; this.pending = null;
    let good, how;
    if (p.cause === "press") { const g = p.osc - d.feat.osc_sd; good = g > 0.002; how = "흔들림 " + p.osc.toFixed(3) + "→" + d.feat.osc_sd.toFixed(3); }
    else { const n = unit(SIG_DEG[p.cause]), dx = d.feat.dgpc - p.x, dy = d.feat.du / U_SCALE - p.y;
           const proj = -(dx * n[0] + dy * n[1]); good = proj > 0.005; how = KO[p.cause] + " 반대 방향으로 " + proj.toFixed(3); }
    const sk = this.streak;
    if (sk && sk.act === p.act) sk.bad = good ? 0 : sk.bad + 1;
    this.log.push({ t: nowS, act: p.act, good: good, how: how });
    if (this.undo && sk && sk.bad >= 2) {
      for (let i = 0; i < sk.n; i++) doPress(REVERSE[sk.act], "되돌림");
      this.banned[sk.act] = nowS + 300; this.streak = null; this.waitUntil = nowS + 30; this.hist = [];
      return note(REVERSE[sk.act], sk.act + " 가 두 번 연속 듣지 않았다 (" + how + ") → " + sk.n + "번 되돌리고 5분 금지");
    }
  }
  let act = d.action, why = d.why;
  this.hist.push([nowS, d.cause]); this.hist = this.hist.filter(h => nowS - h[0] < HOLD_S);
  if (act === "noop") { if (d.cause === "normal") this.streak = null; return note("noop", why); }
  if (!(this.hist.length >= HOLD_S && this.hist.every(h => h[1] === d.cause))) return note("noop", why + " — 판정이 " + HOLD_S + "초 이어지면 누른다");
  if (this.banned[act] > nowS) return note("noop", why + " — 그런데 " + act + " 는 방금 듣지 않아 보류");
  const b = COORDS.buttons[act], k = b && b.knob ? SIM.KNOBS[b.knob] : null;
  if (k && (b.dir > 0 ? sim.knobs[b.knob] >= k.max - 1e-9 : sim.knobs[b.knob] <= k.min + 1e-9)) {
    act = "request_clean"; why = k.label + " 노브가 끝(" + sim.knobs[b.knob] + ")인데 " + d.why + " → 클리닝 요청";
  }
  if (REVERSE[act]) {
    this.streak = this.streak && this.streak.act === act ? Object.assign(this.streak, { n: this.streak.n + 1 }) : { act: act, n: 1, bad: 0 };
    this.pending = { act: act, cause: d.cause, x: d.feat.dgpc, y: d.feat.du / U_SCALE, osc: d.feat.osc_sd };
  }
  doPress(act, d.cause); this.hist = [];
  this.waitUntil = nowS + (WAIT_S[act] || 30);
  return note(act, why);
};

root.AGENT = { detect: detect, Agent: Agent, TH: TH, ACTION: ACTION, SIG_DEG: SIG_DEG };
if (typeof module !== "undefined") module.exports = root.AGENT;
})(typeof window !== "undefined" ? window : globalThis);
