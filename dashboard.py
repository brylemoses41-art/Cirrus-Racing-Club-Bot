from __future__ import annotations

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from storage import load_json

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

RANKS = (
    (0, "AMATEUR", "🟢"),
    (1000, "NOVICE", "🔵"),
    (1500, "COMPETITOR", "🟣"),
    (2100, "EXPERT", "🟠"),
    (2800, "MASTER", "🔴"),
    (3600, "ELITE", "🟡"),
)


def rank_for_rating(rating: int) -> tuple[str, str, int]:
    current = RANKS[0]
    for rank in RANKS:
        if rating >= rank[0]:
            current = rank
    index = RANKS.index(current)
    next_rating = RANKS[index + 1][0] if index + 1 < len(RANKS) else None
    return current[1], current[2], next_rating or 0


def read_data() -> dict:
    drivers = load_json("drivers.json", {"drivers": {}}).get("drivers", {})
    races = load_json("races.json", {"races": []}).get("races", [])
    championship = load_json("championship.json", {}).get("standings", {})

    profiles = []
    for entry in drivers.values():
        name = entry.get("name", "Unnamed")
        results = [
            result
            for race in races
            for result in race.get("results", [])
            if str(result.get("driver", "")).strip().lower() == name.strip().lower()
        ]
        penalties = [
            penalty
            for race in races
            for penalty in race.get("penalties", [])
            if str(penalty.get("driver", "")).strip().lower() == name.strip().lower()
        ]
        points = sum(int(result.get("points", 0)) for result in results) - sum(
            int(penalty.get("points", 0)) for penalty in penalties
        )
        rating = int(entry.get("rating", 0) or 0)
        rank, badge, next_rating = rank_for_rating(rating)
        profiles.append(
            {
                "name": name,
                "rating": rating,
                "rank": rank,
                "badge": badge,
                "next_rating": next_rating,
                "starts": len(results),
                "wins": sum(1 for result in results if int(result.get("position", 999)) == 1),
                "podiums": sum(1 for result in results if int(result.get("position", 999)) <= 3),
                "points": points,
                "penalties": len(penalties),
            }
        )

    profiles.sort(key=lambda driver: (-driver["rating"], -driver["points"], driver["name"].lower()))
    standings = []
    if isinstance(championship, dict):
        for name, value in championship.items():
            if isinstance(value, dict):
                standings.append({"name": name, "points": int(value.get("points", 0)), **value})
            else:
                standings.append({"name": name, "points": int(value or 0)})
    standings.sort(key=lambda item: (-item.get("points", 0), str(item.get("name", "")).lower()))

    now = datetime.now().astimezone()
    upcoming = []
    for race in races:
        date_value = str(race.get("date", ""))
        try:
            parsed = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            if parsed >= now:
                upcoming.append(race)
        except ValueError:
            continue
    upcoming.sort(key=lambda race: str(race.get("date", "")))

    return {
        "season": now.year,
        "drivers": profiles,
        "races": races,
        "upcoming": upcoming[:5],
        "standings": standings[:10],
        "stats": {
            "drivers": len(profiles),
            "races": len(races),
            "completed": sum(1 for race in races if race.get("status") == "locked"),
            "open": sum(1 for race in races if race.get("status") != "locked"),
        },
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CRC • Control Panel</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f4f6f8;background:#0b0d10;--panel:#12161b;--panel2:#171c22;--line:#252c34;--muted:#8e99a5;--accent:#e9edf1}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 75% -10%,#252b33 0,transparent 35%),#0b0d10;min-height:100vh}
.wrap{max-width:1380px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}.eyebrow{font-size:12px;letter-spacing:.16em;color:var(--muted);font-weight:700}.title{font-size:34px;font-weight:800;letter-spacing:-.04em;margin-top:5px}.sub{color:var(--muted);margin-top:5px}.status{border:1px solid var(--line);background:#11151a;padding:10px 14px;border-radius:12px;color:#b9c3cc;font-size:13px}.dot{display:inline-block;width:8px;height:8px;background:#8bd18b;border-radius:50%;margin-right:7px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 10px 30px #0004}.metric{font-size:30px;font-weight:800;margin-top:7px}.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:700}
.main{display:grid;grid-template-columns:1.4fr .8fr;gap:14px;margin-top:14px}.section{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.section h2{font-size:15px;margin:0;padding:16px 18px;border-bottom:1px solid var(--line);letter-spacing:.02em}.section .body{padding:0}.row{display:grid;grid-template-columns:44px 1fr 100px 100px;gap:10px;align-items:center;padding:13px 18px;border-bottom:1px solid #20262d}.row:last-child{border-bottom:0}.pos{color:#68747f;font-weight:800}.driver{font-weight:750}.small{color:var(--muted);font-size:12px;margin-top:2px}.pill{justify-self:start;padding:5px 9px;border:1px solid var(--line);border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.05em}.rating{text-align:right;font-variant-numeric:tabular-nums}.race{padding:16px 18px;border-bottom:1px solid #20262d}.race:last-child{border-bottom:0}.race-title{font-weight:800}.race-meta{display:flex;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:6px}.empty{padding:24px 18px;color:var(--muted)}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.main{grid-template-columns:1fr}.row{grid-template-columns:34px 1fr 80px}.row .smallcol{display:none}}@media(max-width:560px){.wrap{padding:16px}.top{align-items:start;flex-direction:column}.grid{grid-template-columns:1fr 1fr}.title{font-size:27px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top"><div><div class="eyebrow">CIRRUS RACING CLUB</div><div class="title">Control Panel</div><div class="sub">Season <span id="season">—</span> · live bot records</div></div><div class="status"><span class="dot"></span>Dashboard online</div></div>
  <div class="grid">
    <div class="card"><div class="label">Registered drivers</div><div class="metric" id="drivers">—</div></div>
    <div class="card"><div class="label">Race records</div><div class="metric" id="races">—</div></div>
    <div class="card"><div class="label">Completed</div><div class="metric" id="completed">—</div></div>
    <div class="card"><div class="label">Open events</div><div class="metric" id="open">—</div></div>
  </div>
  <div class="main">
    <section class="section"><h2>Driver Rankings</h2><div class="body" id="driversList"></div></section>
    <section class="section"><h2>Upcoming Events</h2><div class="body" id="racesList"></div></section>
  </div>
</div>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){
 const r=await fetch('/api/data',{cache:'no-store'}); if(!r.ok) throw new Error('API error'); const d=await r.json();
 document.getElementById('season').textContent=d.season;
 document.getElementById('drivers').textContent=d.stats.drivers;
 document.getElementById('races').textContent=d.stats.races;
 document.getElementById('completed').textContent=d.stats.completed;
 document.getElementById('open').textContent=d.stats.open;
 const dl=document.getElementById('driversList');
 dl.innerHTML=d.drivers.length?d.drivers.slice(0,10).map((x,i)=>`<div class="row"><div class="pos">${String(i+1).padStart(2,'0')}</div><div><div class="driver">${esc(x.name)}</div><div class="small">${x.wins} wins · ${x.podiums} podiums · ${x.points} pts</div></div><div class="pill">${x.badge} ${esc(x.rank)}</div><div class="rating">${x.rating}</div></div>`).join(''):'<div class="empty">No drivers registered yet.</div>';
 const rl=document.getElementById('racesList');
 rl.innerHTML=d.upcoming.length?d.upcoming.map(x=>`<div class="race"><div class="race-title">${esc(x.name||'Unnamed Race')}</div><div class="race-meta"><span>${esc(x.id||'—')}</span><span>${esc(x.track||'—')}</span><span>${esc(x.laps||'—')} laps</span><span>${esc(x.date||'—')}</span></div></div>`).join(''):'<div class="empty">No upcoming events on the calendar.</div>';
}
refresh().catch(()=>{document.querySelector('.status').innerHTML='<span class="dot"></span>Dashboard waiting for bot'}); setInterval(()=>refresh().catch(()=>{}),10000);
</script>
</body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def send_text(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_text(HTML)
            return
        if path == "/api/data":
            self.send_text(json.dumps(read_data()), "application/json; charset=utf-8")
            return
        self.send_text("Not found", "text/plain; charset=utf-8", 404)


def start_dashboard(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    thread = Thread(target=server.serve_forever, name="crc-dashboard", daemon=True)
    thread.start()
    print(f"CRC dashboard listening on port {port}")
    return server


if __name__ == "__main__":
    start_dashboard()
    ThreadingHTTPServer(("0.0.0.0", DEFAULT_PORT), DashboardHandler).serve_forever()
