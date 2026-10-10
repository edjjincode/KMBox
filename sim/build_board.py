#!/usr/bin/env python3
"""폐루프 보드 한 파일로: board_src.html + coords.js + engine_v2.js + agent_v2.js → sim/board.html"""
import re
from pathlib import Path
H = Path(__file__).parent
eng = re.sub(r"^\s*<script[^>]*>|</script>\s*$", "", (H / "engine_v2.js").read_text(encoding="utf-8").strip())
s = (H / "board_src.html").read_text(encoding="utf-8")
s = s.replace("/*__COORDS__*/", (H / "coords.js").read_text(encoding="utf-8")).replace("/*__ENGINE__*/", eng)
s = s.replace("/*__AGENT__*/", (H / "agent_v2.js").read_text(encoding="utf-8"))
(H / "board.html").write_text(s, encoding="utf-8"); print(H / "board.html", len(s))
