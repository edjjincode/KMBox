#!/usr/bin/env python3
"""시뮬레이터 v2 를 브라우저에서 바로 돌려 보는 한 파일짜리 보기용 페이지로 만든다.

kiosk 화면(sim/index.html)은 그대로 두고, 보기용에만 덧붙인다:
  - coords.js 인라인, 화면을 창 너비에 맞춰 축소
  - 기본값: clean 화면, 정상(이상 없음). 이상은 패널의 '지금 주입' 으로만 들어간다
  - 개발 패널에 '감지 함수' 실시간 결과(reader/detect_v2.py 를 JS 로 옮긴 것)와 시뮬레이터 정답을 나란히

  python sim/build_artifact.py   → sim/view.html
"""
from pathlib import Path

HERE = Path(__file__).parent
s = (HERE / "index.html").read_text(encoding="utf-8")
coords = (HERE / "coords.js").read_text(encoding="utf-8")
s = s.replace('<script src="coords.js"></script>', "<script>\n" + coords + "\n</script>")
s = s.replace("<title>ALD 공정 감시 HMI</title>", "<title>ALD 시뮬레이터 v2</title>")
s = s.replace("const P = new URLSearchParams(location.search);",
              'const P = new URLSearchParams(location.search || "ui=clean&labels=both&fault=normal&seed=7&inject=1500&adv=0");')

EXTRA = "<script>\n" + (HERE / "agent_v2.js").read_text(encoding="utf-8") + "\n</script>\n" + r"""
<style>
  #fit { overflow: hidden; }
  #stage { transform-origin: 0 0; }
  #det { margin-top: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
  #det .box { background: #333d4b; color: #e6eef6; border-radius: 6px; padding: 10px 12px; font: 14px/1.5 "Noto Sans KR", system-ui, sans-serif; }
  #det .k { color: #9fb2c6; font-size: 12px; }
  #det .v { font-size: 20px; font-weight: 700; }
  #inj { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; background: #26303c; border-radius: 6px; padding: 10px 12px; }
  #inj .now { font-size: 20px; font-weight: 800; margin-right: 12px; }
  #inj .now.on { color: #ffb86b; } #inj .now.off { color: #6ee7a0; }
  #det .dok { color: #6ee7a0; } #det .dbad { color: #ff9b9b; }
  #dev { width: auto !important; max-width: 100%; box-sizing: border-box; }
  #gtbox { overflow-x: auto; }
</style>
<script>
/* 화면을 창 너비에 맞춘다 (1920×1080 캔버스는 그대로, 보기만 축소) */
(function () {
  const st = document.getElementById("stage"), fit = document.createElement("div");
  fit.id = "fit"; st.parentNode.insertBefore(fit, st); fit.appendChild(st);
  function size() { const k = Math.min(1, document.documentElement.clientWidth / 1920);
    st.style.transform = "scale(" + k + ")"; fit.style.width = 1920 * k + "px"; fit.style.height = 1080 * k + "px"; }
  addEventListener("resize", size); size();
})();

/* 감지 함수는 sim/agent_v2.js (reader/detect_v2.py 와 parity 시험 통과). 입력은 화면 그래프에 그려진 선(5초 간격)뿐 */
const ACT = AGENT.ACTION;
const KO = { normal: "정상", temp: "온도", purge: "퍼지", pulse: "펄스", press: "압력", flow: "유량",
  noop: "대기", temp_up: "온도 +", temp_down: "온도 −", purge_up: "퍼지 +", purge_down: "퍼지 −", pulse_up: "펄스 +",
  pulse_down: "펄스 −", press_up: "압력 +", press_down: "압력 −", flow_up: "유량 +", flow_down: "유량 −", request_clean: "클리닝 요청" };
const detectJS = (g, u, dt) => AGENT.detect(g, u, dt);   // sim/agent_v2.js 의 감지 함수 그대로
(function () {
  /* 이상 주입 패널: 지금 그래프·노브를 그대로 둔 채, 고른 피처에 교란을 넣는다 */
  const inj = document.createElement("div"); inj.id = "inj";
  inj.innerHTML = '<span class="now" id="inj-now"></span><label>이상</label><select id="inj-f">' +
    SIM.FAULT_TYPES.filter(f => f !== "normal").map(f => '<option value="' + f + '">' + SIM.MECHANISM[f] + '</option>').join("") +
    '</select><button id="inj-go">지금 주입</button><button id="inj-off">정상으로</button>';
  const dev = document.getElementById("dev"); dev.insertBefore(inj, dev.children[1]);
  document.getElementById("inj-go").onclick = function () { sim.faultType = document.getElementById("inj-f").value; sim.injectTick = sim.t; sim.state(); render(); };
  document.getElementById("inj-off").onclick = function () { sim.faultType = "normal"; sim.state(); render(); };
  setInterval(function () {
    const n = document.getElementById("inj-now"), on = sim.faultType !== "normal";
    n.className = "now " + (on ? "on" : "off");
    n.textContent = on ? "지금 이상: " + KO[sim.faultType] + " (주입 후 +" + Math.max(0, (sim.t - sim.injectTick) * SIM.DT).toFixed(0) + "초)" : "지금 이상: 없음 (정상)";
  }, 300);
})();
(function () {
  const box = document.createElement("div"); box.id = "det";
  document.getElementById("dev").insertBefore(box, document.getElementById("gtbox"));
  setInterval(function () {
    const v = sim.view(), g = sim.gt(), d = detectJS(v.gpcPoints.map(p => p.v), v.uPoints.map(p => p.v), 5);
    const act = ACT[d.cause], ok = act === g.correct_action, since = (g.t - g.inject_tick) * SIM.DT;
    box.innerHTML =
      '<div class="box"><div class="k">감지 함수 — 화면 그래프만 보고</div><div class="v">원인 ' + KO[d.cause] + ' → ' + KO[act] + '</div><div>' + d.why + '</div></div>' +
      '<div class="box"><div class="k">시뮬레이터 정답 (' + (since < 0 ? "주입 " + (-since).toFixed(0) + "초 전" : "주입 후 +" + since.toFixed(0) + "초") + ')</div>' +
      '<div class="v">교란 ' + KO[g.fault_type] + ' → ' + KO[g.correct_action] + '</div><div class="' + (ok ? "dok" : "dbad") + '">' +
      (ok ? "감지 함수와 일치" : (g.correct_action === "noop" ? "아직 화면에 보일 만큼 크지 않음 (정답 대기)" : "감지 함수와 다름")) + '</div></div>';
  }, 500);
})();
</script>
"""
s = s.replace("</body>", EXTRA + "\n</body>") if "</body>" in s else s + EXTRA
(HERE / "view.html").write_text(s, encoding="utf-8")
print(HERE / "view.html", len(s))
