#!/usr/bin/env python3
"""kiosk 화면 조립: 화면 틀(hmi_template.html, 원래 ald-vlm-agent/hmi/index.html) 의 화면(app) + v2 엔진(engine_v2.js) → sim/index.html"""
from pathlib import Path
HERE = Path(__file__).parent
src = (HERE / "hmi_template.html").read_text(encoding="utf-8")   # 화면 틀 (ald-vlm-agent/hmi/index.html 에서 복사)
eng = (HERE / "engine_v2.js").read_text(encoding="utf-8")
a = src.index('<script id="sim-engine">'); b = src.index("</script>", a) + len("</script>")
s = src[:a] + eng.strip() + src[b:]
a = s.index("    gtbox.textContent =\n"); b = s.index("\n  }\n}", a)
s = s[:a] + '''    gtbox.textContent =
      "t=" + g.t + "  clock=" + view.clock + "  fault=" + g.fault_type + "  inject=" + g.inject_tick +
      "  주입 후 " + ((g.t - g.inject_tick) * SIM.DT).toFixed(0) + "초\\n" +
      "gpc_true=" + g.gpc_true.toFixed(3) + "  gpc_display=" + g.gpc_display.toFixed(3) +
      "  uniformity_true=" + g.uniformity_true.toFixed(3) + "  uniformity=" + g.uniformity.toFixed(3) + "\\n" +
      "교란=" + g.disturbance + "  진동진폭=" + g.osc_amp + "  실효 피처=" + JSON.stringify(g.effective) + "\\n" +
      "GPC 항=" + JSON.stringify(g.terms_gpc) + "\\n균일도 항=" + JSON.stringify(g.terms_u) + "\\n" +
      "correct_action=" + g.correct_action + "   pending=" +
      (g.pending_action ? g.pending_action.id + "(" + g.pending_action.remaining_s + "s)" : "none") + "\\n" +
      "rationale=" + g.rationale;''' + s[b:]
s = s.replace('const BUILD = "v10-clean";', 'const BUILD = "v2-feature";')
a0 = """  // 상한 실선 + 라벨
  const ly = sy(lim);
  add("line", { x1: x0, x2: x1, y1: ly, y2: ly, stroke: "#b42318", "stroke-width": 2 });"""
b0 = """  // 정상 범위(공정 창): 초록 띠 + 하한·상한 실선
  const win = SIM.WINDOW[r.key], wy0 = sy(win[0]), wy1 = sy(win[1]);
  add("rect", { x: x0, y: wy1, width: x1 - x0, height: wy0 - wy1, fill: "#1baf7a", "fill-opacity": .13 });
  add("line", { x1: x0, x2: x1, y1: wy0, y2: wy0, stroke: "#b42318", "stroke-width": 1.5 });
  add("text", { x: x1 - 6, y: wy0 + 15, "text-anchor": "end", "font-size": 13, "font-weight": 800, fill: "#9c1c15" }, "하한 " + win[0].toFixed(spec.dp));
  const ly = sy(lim);
  add("line", { x1: x0, x2: x1, y1: ly, y2: ly, stroke: "#b42318", "stroke-width": 1.5 });"""
assert s.count(a0) == 1, "spark limit"; s = s.replace(a0, b0)
s = s.replace('const BUILD = "v2-feature";', 'const BUILD = "v2-window";')
# 노브 칸 축을 정상 범위 중심으로 확대 (범위 폭의 70% 만큼 위아래 여유, 노브 최소·최대로 자름). 라벨: 왼쪽 = 하한·기준·상한 값, 오른쪽 = '상한'/'하한'
i0 = s.index("  const lim = SIM.limitOf(r.key || spec.label);", s.index("function drawSpark"))
i1 = s.index("  add(\"text\", { x: x0, y: y1 + 18,", i0)
s = s[:i0] + """  const win = SIM.WINDOW[r.key], span = win[1] - win[0];
  const amin = Math.max(spec.min, win[0] - span * 0.7), amax = Math.min(spec.max, win[1] + span * 0.7);
  const sy = function (v) { const c = Math.min(amax, Math.max(amin, v)); return y1 - (y1 - y0) * (c - amin) / (amax - amin); };
  const sx = timeAxis(pts, x0, x1);
  const N = [];
  const add = function (t, a, txt) {
    const e = document.createElementNS(NS, t);
    for (const k in a) e.setAttribute(k, a[k]);
    if (txt !== undefined) e.textContent = txt;
    N.push(e); return e;
  };
  add("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, fill: "#fbfcfd", stroke: "#d4dbe3" });
  // 정상 범위(공정 창): 초록 띠 + 하한·상한 실선
  const wy0 = sy(win[0]), wy1 = sy(win[1]);
  add("rect", { x: x0, y: wy1, width: x1 - x0, height: wy0 - wy1, fill: "#1baf7a", "fill-opacity": .14 });
  add("line", { x1: x0, x2: x1, y1: wy0, y2: wy0, stroke: "#b42318", "stroke-width": 1.5 });
  add("line", { x1: x0, x2: x1, y1: wy1, y2: wy1, stroke: "#b42318", "stroke-width": 1.5 });
  add("text", { x: x1 - 4, y: wy1 - 3, "text-anchor": "end", "font-size": 12, "font-weight": 800, fill: "#9c1c15" }, "상한");
  add("text", { x: x1 - 4, y: wy0 + 12, "text-anchor": "end", "font-size": 12, "font-weight": 800, fill: "#9c1c15" }, "하한");
  // 기준값 점선
  add("line", { x1: x0, x2: x1, y1: sy(spec.base), y2: sy(spec.base), stroke: "#0c6b2e", "stroke-width": 1.5, "stroke-dasharray": "6 5", "stroke-opacity": .7 });
  [win[0], spec.base, win[1]].forEach(function (tv, i) {
    add("text", { x: x0 - 6, y: sy(tv) + (i === 0 ? 10 : i === 2 ? 2 : 5), "text-anchor": "end", "font-size": 13, "font-weight": 700,
                  fill: i === 1 ? "#55626f" : "#9c1c15" }, tv.toFixed(spec.dp));
  });
""" + s[i1:]
# 실제값 선의 clamp 는 새 sy 가 한다
s = s.replace("const ex = timeAxis(effPts, x0, x1), cl = function (v) { return Math.min(spec.max, Math.max(spec.min, v)); };",
              "const ex = timeAxis(effPts, x0, x1), cl = function (v) { return v; };")
# 노브 칸: 큰 숫자·파란 선 = 실제 공정값(설정 + 교란), 작은 글씨·회색 계단 = 설정값.
# 이상이 들어가면 파란 선이 기준에서 벗어나고, 버튼을 누르면 다시 기준으로 돌아온다.
for x, y in [
 ("""    p.appendChild(el("div", "sp-label", {}, spec.label + " 설정"));""",
  """    const lab = el("div", "sp-label", {}, spec.label); p.appendChild(lab);"""),
 ("""    refs["sp_" + c.key] = { v: v, svg: svg, cfg: c, spec: spec };""",
  """    refs["sp_" + c.key] = { v: v, svg: svg, cfg: c, spec: spec, lab: lab };"""),
 ("""    r.v.firstChild.nodeValue = view.knobs[k].toFixed(r.spec.dp);
    r.v.style.color = view.knobs[k] > SIM.limitOf(k) + 1e-9 ? "#9c1c15" : "";
    drawSpark(r, view.knobPoints[k]);""",
  """    const ef = view.eff[k], set = view.knobs[k], w = SIM.WINDOW[k], amp = k === "press" ? view.oscAmp : 0;
    // 상태: 창 밖 = 빨강, 창 끝 15% 안쪽으로 다가감 = 주황, 그 밖 = 보통
    const vlo = k === "press" ? set - amp : ef, vhi = k === "press" ? set + amp : ef, edge = (w[1] - w[0]) * 0.15;
    const out = vlo < w[0] - 1e-9 || vhi > w[1] + 1e-9, near = !out && (vlo < w[0] + edge || vhi > w[1] - edge);
    const off = out || near, col = out ? "#d92d20" : "#c27c0e";
    r.v.firstChild.nodeValue = (k === "press" && view.oscAmp > 0.02 ? "±" + view.oscAmp.toFixed(2) + " " : "") + (k === "press" ? set : ef).toFixed(r.spec.dp);
    r.v.style.color = off ? col : "";
    r.lab.textContent = r.spec.label + " 실제 · 설정 " + set.toFixed(r.spec.dp);
    r.lab.style.color = off ? col : "";
    drawSpark(r, view.knobPoints[k], view.effPoints[k], off ? col : null);"""),
 ("""function drawSpark(r, pts) {""", """function drawSpark(r, pts, effPts, off) {"""),
 ("""    add("path", { d: d, fill: "none", stroke: "#1552b8", "stroke-width": 2.5, "stroke-linejoin": "miter" });
    const last = pts[pts.length - 1];
    add("circle", { cx: sx(pts.length - 1), cy: sy(last.v), r: 4, fill: "#1552b8", stroke: "#fff", "stroke-width": 2 });""",
  """    add("path", { d: d, fill: "none", stroke: "#8a96a3", "stroke-width": 1.8, "stroke-dasharray": "5 4", "stroke-linejoin": "miter" });   // 설정값"""),
 ("""  r.svg.replaceChildren.apply(r.svg, N);
}""", """  if (effPts && effPts.length) {            // 실제 공정값 — 파란 실선, 기준에서 벗어나면 빨강
    const ex = timeAxis(effPts, x0, x1), cl = function (v) { return Math.min(spec.max, Math.max(spec.min, v)); };
    const col = off || "#1552b8";
    add("path", { d: effPts.map(function (p, i) { return (i ? "L" : "M") + ex(i).toFixed(1) + " " + sy(cl(p.v)).toFixed(1); }).join(""),
                  fill: "none", stroke: col, "stroke-width": 2.5 });
    const lv = effPts[effPts.length - 1].v;
    add("circle", { cx: ex(effPts.length - 1), cy: sy(cl(lv)), r: 4, fill: col, stroke: "#fff", "stroke-width": 2 });
  }
  r.svg.replaceChildren.apply(r.svg, N);
}"""),
]:
    assert s.count(x) == 1, x[:60]; s = s.replace(x, y)

(HERE / "index.html").write_text(s, encoding="utf-8")
print(HERE / "index.html", len(s))
