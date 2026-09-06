from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import discord

from constants import points_for_position
from storage import load_json, save_json

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN") or secrets.token_urlsafe(24)
BOT = None
BOT_LOOP = None

RANKS = (
    (0, "AMATEUR", "🟢"),
    (1000, "NOVICE", "🔵"),
    (1500, "COMPETITOR", "🟣"),
    (2100, "EXPERT", "🟠"),
    (2800, "MASTER", "🔴"),
    (3600, "ELITE", "🟡"),
)


def set_bot(bot):
    global BOT, BOT_LOOP
    BOT = bot
    BOT_LOOP = bot.loop


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
        results = [result for race in races for result in race.get("results", []) if str(result.get("driver", "")).strip().lower() == name.strip().lower()]
        penalties = [penalty for race in races for penalty in race.get("penalties", []) if str(penalty.get("driver", "")).strip().lower() == name.strip().lower()]
        points = sum(int(result.get("points", 0)) for result in results) - sum(int(penalty.get("points", 0)) for penalty in penalties)
        rating = int(entry.get("rating", 0) or 0)
        rank, badge, next_rating = rank_for_rating(rating)
        profiles.append({"name": name, "rating": rating, "rank": rank, "badge": badge, "next_rating": next_rating, "starts": len(results), "wins": sum(1 for r in results if int(r.get("position", 999)) == 1), "podiums": sum(1 for r in results if int(r.get("position", 999)) <= 3), "points": points, "penalties": len(penalties)})
    profiles.sort(key=lambda d: (-d["rating"], -d["points"], d["name"].lower()))
    standings = []
    if isinstance(championship, dict):
        for name, value in championship.items():
            if isinstance(value, dict):
                standings.append({"name": name, "points": int(value.get("points", 0)), **value})
            else:
                standings.append({"name": name, "points": int(value or 0)})
    standings.sort(key=lambda x: (-x.get("points", 0), str(x.get("name", "")).lower()))
    now = datetime.now().astimezone()
    upcoming = []
    for race in races:
        try:
            parsed = datetime.fromisoformat(str(race.get("date", "")).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            if parsed >= now:
                upcoming.append(race)
        except ValueError:
            pass
    upcoming.sort(key=lambda r: str(r.get("date", "")))
    return {"season": now.year, "drivers": profiles, "races": races, "upcoming": upcoming[:5], "standings": standings[:10], "stats": {"drivers": len(profiles), "races": len(races), "completed": sum(1 for r in races if r.get("status") == "locked"), "open": sum(1 for r in races if r.get("status") != "locked")}}


def find_race(races, race_id):
    target = str(race_id).strip().upper()
    return next((r for r in races if str(r.get("id", "")).strip().upper() == target), None)


def next_race_id(races):
    year = datetime.now(timezone.utc).year % 100
    prefix = f"CRC-{year:02d}-"
    sequence = 0
    for race in races:
        rid = str(race.get("id", "")).strip().upper()
        if rid.startswith(prefix):
            try:
                sequence = max(sequence, int(rid[len(prefix):]))
            except ValueError:
                pass
    return f"{prefix}{sequence + 1:03d}"


def run_async(coro, timeout=20):
    if BOT_LOOP is None:
        raise RuntimeError("Discord bot is not ready yet")
    future = asyncio.run_coroutine_threadsafe(coro, BOT_LOOP)
    return future.result(timeout=timeout)


async def discord_action(action, payload):
    if BOT is None:
        raise RuntimeError("Discord bot is not ready yet")
    if action == "announce":
        channel = BOT.get_channel(int(payload["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Channel not found")
        await channel.send(str(payload["message"]).strip())
        return {"message": "Announcement sent."}
    if action == "purge":
        channel = BOT.get_channel(int(payload["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Channel not found")
        amount = max(1, min(int(payload["amount"]), 100))
        deleted = await channel.purge(limit=amount)
        return {"message": f"Deleted {len(deleted)} message(s)."}
    raise ValueError("Unknown Discord action")


def perform_action(action, payload):
    if action in {"announce", "purge"}:
        return run_async(discord_action(action, payload))

    if action == "create_race":
        name, track, date = str(payload.get("name", "")).strip(), str(payload.get("track", "")).strip(), str(payload.get("date", "")).strip()
        laps = int(payload.get("laps", 0))
        if not name or not track or not date or laps < 1:
            raise ValueError("Race name, track, date, and a valid lap count are required")
        data = load_json("races.json", {"races": []})
        races = data.setdefault("races", [])
        race = {"id": next_race_id(races), "name": name, "track": track, "laps": laps, "date": date, "status": "open", "created_by": "dashboard", "created_at": datetime.now(timezone.utc).isoformat(), "qualifying": [], "results": [], "penalties": [], "reports": [], "reminders_sent": [], "channel_id": None}
        races.append(race)
        save_json("races.json", data)
        return {"message": f"Created {race['id']} — {name}.", "race_id": race["id"]}

    data = load_json("races.json", {"races": []})
    races = data.setdefault("races", [])
    race = find_race(races, payload.get("race_id", ""))
    if not race:
        raise ValueError("Race record not found")

    if action in {"open_race", "lock_race"}:
        race["status"] = "open" if action == "open_race" else "locked"
        save_json("races.json", data)
        return {"message": f"{race['id']} is now {race['status']}."}

    if action == "result":
        driver, position = str(payload.get("driver", "")).strip(), int(payload.get("position", 0))
        if not driver or position < 1:
            raise ValueError("Driver and valid finishing position are required")
        points = points_for_position(position)
        race.setdefault("results", []).append({"driver": driver, "position": position, "points": points})
        race["results"].sort(key=lambda x: x.get("position", 999))
        save_json("races.json", data)
        return {"message": f"Recorded P{position} — {driver} ({points} pts)."}

    if action == "penalty":
        driver, points, reason = str(payload.get("driver", "")).strip(), int(payload.get("points", 0)), str(payload.get("reason", "")).strip()
        if not driver or points < 1 or not reason:
            raise ValueError("Driver, penalty points, and ruling are required")
        race.setdefault("penalties", []).append({"driver": driver, "points": points, "reason": reason, "issued_by": "dashboard", "created_at": datetime.now(timezone.utc).isoformat()})
        save_json("races.json", data)
        return {"message": f"Issued {points} point penalty to {driver}."}

    if action == "qualifying":
        driver, lap_time, position = str(payload.get("driver", "")).strip(), str(payload.get("lap_time", "")).strip(), int(payload.get("position", 0))
        if not driver or not lap_time or position < 1:
            raise ValueError("Driver, lap time, and valid grid position are required")
        race.setdefault("qualifying", [])
        race["qualifying"] = [x for x in race["qualifying"] if x.get("position") != position]
        race["qualifying"].append({"driver": driver, "lap_time": lap_time, "position": position})
        race["qualifying"].sort(key=lambda x: x.get("position", 999))
        save_json("races.json", data)
        return {"message": f"Recorded qualifying P{position} — {driver} — {lap_time}."}

    if action == "rating":
        name, delta = str(payload.get("driver", "")).strip(), int(payload.get("delta", 0))
        drivers = load_json("drivers.json", {"drivers": {}})
        found = None
        for key, entry in drivers.setdefault("drivers", {}).items():
            if str(entry.get("name", "")).strip().lower() == name.lower():
                found = entry
                break
        if found is None:
            raise ValueError("Driver not found")
        old = int(found.get("rating", 0) or 0)
        found["rating"] = max(0, old + delta)
        save_json("drivers.json", drivers)
        return {"message": f"{name}: rating {old} → {found['rating']}."}

    if action == "rename":
        old_name, new_name = str(payload.get("old_name", "")).strip(), str(payload.get("new_name", "")).strip()
        if not old_name or not new_name:
            raise ValueError("Both current and new driver names are required")
        drivers = load_json("drivers.json", {"drivers": {}})
        found = next((entry for entry in drivers.setdefault("drivers", {}).values() if str(entry.get("name", "")).strip().lower() == old_name.lower()), None)
        if found is None:
            raise ValueError("Driver not found")
        found["name"] = new_name
        save_json("drivers.json", drivers)
        return {"message": f"Renamed {old_name} → {new_name}."}

    raise ValueError("Unknown dashboard action")


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CRC • Control Center</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:#eef1f4;background:#080a0d;--p:#11151a;--p2:#171c22;--l:#27303a;--m:#8995a1;--a:#e9edf1;--good:#9bdd9b;--bad:#ff8e8e}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 75% -10%,#252c34 0,transparent 34%),#080a0d;min-height:100vh}.wrap{max-width:1450px;margin:auto;padding:26px}.top{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px;gap:18px}.ey{font-size:11px;letter-spacing:.18em;color:var(--m);font-weight:800}.title{font-size:35px;font-weight:850;letter-spacing:-.045em;margin-top:4px}.sub{color:var(--m);margin-top:4px}.status{border:1px solid var(--l);background:#101419;padding:9px 13px;border-radius:11px;font-size:12px}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--good);margin-right:7px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,.panel{background:linear-gradient(145deg,var(--p2),var(--p));border:1px solid var(--l);border-radius:15px;box-shadow:0 12px 35px #0005}.card{padding:17px}.lab{font-size:11px;color:var(--m);text-transform:uppercase;letter-spacing:.11em;font-weight:800}.num{font-size:29px;font-weight:850;margin-top:7px}.tabs{display:flex;gap:8px;margin:15px 0}.tab{background:#11151a;border:1px solid var(--l);color:#b9c2ca;padding:9px 13px;border-radius:10px;font-weight:750;cursor:pointer}.tab.active{background:#e9edf1;color:#0b0d10}.page{display:none}.page.active{display:block}.layout{display:grid;grid-template-columns:1.35fr .85fr;gap:12px}.panel h2{font-size:14px;margin:0;padding:15px 17px;border-bottom:1px solid var(--l)}.body{padding:15px 17px}.row{display:grid;grid-template-columns:42px 1fr 105px 90px;gap:10px;align-items:center;padding:12px 0;border-bottom:1px solid #20262d}.row:last-child{border:0}.muted{color:var(--m);font-size:12px}.pill{border:1px solid var(--l);border-radius:999px;padding:5px 8px;font-size:10px;font-weight:850;justify-self:start}.right{text-align:right}.race{padding:11px 0;border-bottom:1px solid #20262d}.race:last-child{border:0}.form{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.form.one{grid-template-columns:1fr}.form.three{grid-template-columns:repeat(3,1fr)}input,select,textarea{width:100%;background:#0c1014;border:1px solid var(--l);color:#eef1f4;border-radius:9px;padding:10px;font:inherit}textarea{min-height:90px;resize:vertical}.field label{display:block;color:var(--m);font-size:11px;font-weight:750;margin:0 0 5px}.btn{border:1px solid var(--l);background:#e9edf1;color:#0b0d10;padding:10px 13px;border-radius:9px;font-weight:850;cursor:pointer}.btn.dark{background:#11151a;color:#eef1f4}.btn.danger{background:#281619;color:#ffb5b5}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.notice{display:none;margin-top:10px;padding:10px;border-radius:9px;background:#10161b;border:1px solid var(--l);font-size:12px}.notice.show{display:block}.lock{font-size:12px;color:#c9d0d6;margin-bottom:12px}.empty{padding:15px 0;color:var(--m)}@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}}@media(max-width:560px){.wrap{padding:15px}.top{align-items:start;flex-direction:column}.stats{grid-template-columns:1fr 1fr}.form,.form.three{grid-template-columns:1fr}.row{grid-template-columns:30px 1fr 70px}.row .hide{display:none}}
</style></head><body><div class="wrap">
<div class="top"><div><div class="ey">CIRRUS RACING CLUB</div><div class="title">Control Center</div><div class="sub">Season <span id="season">—</span> · bot administration</div></div><div class="status"><span class="dot"></span>Authenticated</div></div>
<div class="stats"><div class="card"><div class="lab">Drivers</div><div class="num" id="drivers">—</div></div><div class="card"><div class="lab">Races</div><div class="num" id="races">—</div></div><div class="card"><div class="lab">Completed</div><div class="num" id="completed">—</div></div><div class="card"><div class="lab">Open events</div><div class="num" id="open">—</div></div></div>
<div class="tabs"><button class="tab active" onclick="show('overview',this)">Overview</button><button class="tab" onclick="show('racesPage',this)">Race Control</button><button class="tab" onclick="show('driversPage',this)">Drivers</button><button class="tab" onclick="show('discordPage',this)">Discord</button></div>
<section id="overview" class="page active"><div class="layout"><div class="panel"><h2>Driver Rankings</h2><div class="body" id="driversList"></div></div><div class="panel"><h2>Upcoming Events</h2><div class="body" id="racesList"></div></div></div></section>
<section id="racesPage" class="page"><div class="layout"><div class="panel"><h2>Create Race</h2><div class="body"><div class="form"><div class="field"><label>Race name</label><input id="rn"></div><div class="field"><label>Track</label><input id="rt"></div><div class="field"><label>Laps</label><input id="rl" type="number" min="1"></div><div class="field"><label>Date / time</label><input id="rd" placeholder="2026-09-10 20:00"></div></div><div class="actions"><button class="btn" onclick="act('create_race',{name:rn.value,track:rt.value,laps:rl.value,date:rd.value})">Create race</button></div><div id="raceNotice" class="notice"></div></div></div><div class="panel"><h2>Race Actions</h2><div class="body"><div class="field"><label>Race ID</label><input id="rid" placeholder="CRC-26-001"></div><div class="actions"><button class="btn" onclick="act('open_race',{race_id:rid.value})">Open</button><button class="btn dark" onclick="act('lock_race',{race_id:rid.value})">Lock</button></div><hr style="border:0;border-top:1px solid var(--l);margin:16px 0"><div class="form"><div class="field"><label>Driver</label><input id="resDriver"></div><div class="field"><label>Finishing position</label><input id="resPos" type="number" min="1"></div></div><div class="actions"><button class="btn" onclick="act('result',{race_id:rid.value,driver:resDriver.value,position:resPos.value})">Record result</button></div><div class="form" style="margin-top:10px"><div class="field"><label>Qualifying driver</label><input id="qDriver"></div><div class="field"><label>Lap time</label><input id="qTime" placeholder="1:45.000"></div><div class="field"><label>Grid position</label><input id="qPos" type="number" min="1"></div></div><div class="actions"><button class="btn dark" onclick="act('qualifying',{race_id:rid.value,driver:qDriver.value,lap_time:qTime.value,position:qPos.value})">Record qualifying</button></div><div id="raceActionNotice" class="notice"></div></div></div></div></section>
<section id="driversPage" class="page"><div class="layout"><div class="panel"><h2>Driver Administration</h2><div class="body"><div class="form"><div class="field"><label>Current name</label><input id="oldName"></div><div class="field"><label>New name</label><input id="newName"></div></div><div class="actions"><button class="btn" onclick="act('rename',{old_name:oldName.value,new_name:newName.value})">Rename driver</button></div><hr style="border:0;border-top:1px solid var(--l);margin:16px 0"><div class="form"><div class="field"><label>Driver</label><input id="ratingDriver"></div><div class="field"><label>Rating change</label><input id="ratingDelta" type="number" placeholder="+25 / -10"></div></div><div class="actions"><button class="btn dark" onclick="act('rating',{driver:ratingDriver.value,delta:ratingDelta.value})">Adjust rating</button></div><div id="driverNotice" class="notice"></div></div></div><div class="panel"><h2>Current Drivers</h2><div class="body" id="driverAdminList"></div></div></div></section>
<section id="discordPage" class="page"><div class="layout"><div class="panel"><h2>Announcement</h2><div class="body"><div class="field"><label>Channel ID</label><input id="annChannel"></div><div class="field" style="margin-top:10px"><label>Message</label><textarea id="annMessage" placeholder="Race Control announcement..."></textarea></div><div class="actions"><button class="btn" onclick="act('announce',{channel_id:annChannel.value,message:annMessage.value})">Send announcement</button></div><div id="discordNotice" class="notice"></div></div></div><div class="panel"><h2>Moderation</h2><div class="body"><div class="field"><label>Channel ID</label><input id="purgeChannel"></div><div class="field" style="margin-top:10px"><label>Messages to delete (1–100)</label><input id="purgeAmount" type="number" min="1" max="100" value="10"></div><div class="actions"><button class="btn danger" onclick="act('purge',{channel_id:purgeChannel.value,amount:purgeAmount.value})">Purge messages</button></div><div id="purgeNotice" class="notice"></div><p class="muted" style="margin-top:14px">The bot must have permission to manage messages in the selected channel.</p></div></div></div></section>
</div><script>
let token=localStorage.getItem('crc_dashboard_token')||prompt('CRC Control Center token:'); if(token)localStorage.setItem('crc_dashboard_token',token);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function show(id,btn){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');btn.classList.add('active')}
async function act(action,payload){let box=action==='announce'||action==='purge'?document.getElementById(action==='announce'?'discordNotice':'purgeNotice'):action==='rename'||action==='rating'?document.getElementById('driverNotice'):action==='create_race'?document.getElementById('raceNotice'):document.getElementById('raceActionNotice');try{let r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({action,...payload})});let d=await r.json();if(!r.ok)throw new Error(d.error||'Action failed');box.textContent='✓ '+d.message;box.classList.add('show');refresh();}catch(e){box.textContent='✕ '+e.message;box.classList.add('show');}}
async function refresh(){try{let r=await fetch('/api/data',{cache:'no-store',headers:{Authorization:'Bearer '+token}});if(r.status===401){localStorage.removeItem('crc_dashboard_token');location.reload();return}let d=await r.json();season.textContent=d.season;drivers.textContent=d.stats.drivers;races.textContent=d.stats.races;completed.textContent=d.stats.completed;open.textContent=d.stats.open;driversList.innerHTML=d.drivers.length?d.drivers.slice(0,10).map((x,i)=>`<div class="row"><b>${String(i+1).padStart(2,'0')}</b><div><b>${esc(x.name)}</b><div class="muted">${x.wins} wins · ${x.podiums} podiums · ${x.points} pts</div></div><span class="pill">${x.badge} ${esc(x.rank)}</span><b class="right">${x.rating}</b></div>`).join(''):'<div class="empty">No drivers registered.</div>';driverAdminList.innerHTML=d.drivers.length?d.drivers.map(x=>`<div class="race"><b>${esc(x.name)}</b><div class="muted">${x.badge} ${esc(x.rank)} · ${x.rating} rating · ${x.points} pts</div></div>`).join(''):'<div class="empty">No drivers registered.</div>';racesList.innerHTML=d.upcoming.length?d.upcoming.map(x=>`<div class="race"><b>${esc(x.name||'Unnamed Race')}</b><div class="muted">${esc(x.id||'—')} · ${esc(x.track||'—')} · ${esc(x.laps||'—')} laps<br>${esc(x.date||'—')}</div></div>`).join(''):'<div class="empty">No upcoming events.</div>';}catch(e){}}
refresh();setInterval(refresh,10000);
</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, body, status=200):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def send_text(self, body, content_type="text/html; charset=utf-8", status=200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def authorized(self):
        return self.headers.get("Authorization", "") == f"Bearer {DASHBOARD_TOKEN}"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send_text(HTML)
            return
        if path == "/api/data":
            if not self.authorized():
                self.send_json({"error": "Unauthorized"}, 401)
                return
            self.send_json(read_data())
            return
        self.send_text("Not found", "text/plain; charset=utf-8", 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/action":
            self.send_json({"error": "Not found"}, 404)
            return
        if not self.authorized():
            self.send_json({"error": "Unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100_000:
                raise ValueError("Request too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            action = str(payload.pop("action", ""))
            result = perform_action(action, payload)
            self.send_json(result)
        except Exception as error:
            self.send_json({"error": str(error)}, 400)


def start_dashboard(port: int = DEFAULT_PORT):
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    thread = Thread(target=server.serve_forever, name="crc-dashboard", daemon=True)
    thread.start()
    print(f"CRC dashboard listening on port {port}")
    if not os.getenv("DASHBOARD_TOKEN"):
        print(f"CRC DASHBOARD TOKEN: {DASHBOARD_TOKEN}")
    return server


if __name__ == "__main__":
    start_dashboard()
    try:
        ThreadingHTTPServer(("0.0.0.0", DEFAULT_PORT), DashboardHandler).serve_forever()
    except KeyboardInterrupt:
        pass
