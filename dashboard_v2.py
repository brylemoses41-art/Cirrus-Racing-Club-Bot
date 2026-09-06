from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import urlparse

from constants import points_for_position
from storage import load_json, save_json

DEFAULT_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
SESSION_TTL = 60 * 60 * 12
DATA_LOCK = Lock()
SESSIONS: dict[str, dict] = {}
LOGIN_ATTEMPTS: dict[str, list[float]] = {}

RANKS = (
    (0, "AMATEUR", "🟢"),
    (1000, "NOVICE", "🔵"),
    (1500, "COMPETITOR", "🟣"),
    (2100, "EXPERT", "🟠"),
    (2800, "MASTER", "🔴"),
    (3600, "ELITE", "🟡"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 220_000)
    return f"pbkdf2_sha256$220000${salt.hex()}${digest.hex()}"


def password_ok(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def staff() -> dict:
    with DATA_LOCK:
        data = load_json("staff.json", {"users": []})
        data.setdefault("users", [])
        return data


def users() -> list[dict]:
    return staff().get("users", [])


def find_user(username: str) -> dict | None:
    target = username.strip().lower()
    return next((u for u in users() if str(u.get("username", "")).lower() == target), None)


def has_admin() -> bool:
    return any(str(u.get("role")) == "admin" and u.get("active", True) for u in users())


def audit(actor: str, action: str, detail: str, success: bool = True) -> None:
    with DATA_LOCK:
        data = load_json("audit_log.json", {"entries": []})
        entries = data.setdefault("entries", [])
        entries.insert(
            0,
            {
                "timestamp": now(),
                "actor": actor,
                "action": action,
                "detail": detail,
                "success": success,
            },
        )
        data["entries"] = entries[:500]
        save_json("audit_log.json", data)


def rank_for_rating(rating: int):
    current = RANKS[0]
    for rank in RANKS:
        if rating >= rank[0]:
            current = rank
    return current


def read_data() -> dict:
    drivers = load_json("drivers.json", {"drivers": {}}).get("drivers", {})
    races = load_json("races.json", {"races": []}).get("races", [])
    profiles = []
    for entry in drivers.values():
        name = entry.get("name", "Unnamed")
        results = [
            x for r in races for x in r.get("results", [])
            if str(x.get("driver", "")).lower() == name.lower()
        ]
        penalties = [
            x for r in races for x in r.get("penalties", [])
            if str(x.get("driver", "")).lower() == name.lower()
        ]
        points = sum(int(x.get("points", 0)) for x in results) - sum(
            int(x.get("points", 0)) for x in penalties
        )
        rating = int(entry.get("rating", 0) or 0)
        rank, badge = rank_for_rating(rating)[1:]
        profiles.append(
            {
                "name": name,
                "rating": rating,
                "rank": rank,
                "badge": badge,
                "wins": sum(int(x.get("position", 999)) == 1 for x in results),
                "podiums": sum(int(x.get("position", 999)) <= 3 for x in results),
                "points": points,
                "starts": len(results),
            }
        )
    profiles.sort(key=lambda x: (-x["rating"], -x["points"], x["name"].lower()))
    return {
        "drivers": profiles,
        "races": races,
        "stats": {
            "drivers": len(profiles),
            "races": len(races),
            "completed": sum(r.get("status") == "locked" for r in races),
            "open": sum(r.get("status") != "locked" for r in races),
        },
    }


def next_race_id(races: list[dict]) -> str:
    year = datetime.now(timezone.utc).year % 100
    prefix = f"CRC-{year:02d}-"
    seq = max(
        [
            int(str(r.get("id", ""))[len(prefix):])
            for r in races
            if str(r.get("id", "")).startswith(prefix)
            and str(r.get("id", ""))[len(prefix):].isdigit()
        ]
        or [0]
    )
    return f"{prefix}{seq + 1:03d}"


def do_action(action: str, p: dict, actor: str) -> str:
    data = load_json("races.json", {"races": []})
    races = data.setdefault("races", [])

    if action == "create_race":
        name = str(p.get("name", "")).strip()
        track = str(p.get("track", "")).strip()
        date = str(p.get("date", "")).strip()
        laps = int(p.get("laps", 0))
        if not name or not track or not date or laps < 1:
            raise ValueError("Complete race details are required")
        race = {
            "id": next_race_id(races),
            "name": name,
            "track": track,
            "laps": laps,
            "date": date,
            "status": "open",
            "created_by": actor,
            "created_at": now(),
            "qualifying": [],
            "results": [],
            "penalties": [],
            "reports": [],
            "reminders_sent": [],
            "channel_id": None,
        }
        races.append(race)
        save_json("races.json", data)
        return f"Created {race['id']} — {name}"

    rid = str(p.get("race_id", "")).upper().strip()
    race = next((r for r in races if str(r.get("id", "")).upper() == rid), None)
    if not race:
        raise ValueError("Race not found")

    if action in ("open_race", "lock_race"):
        race["status"] = "open" if action == "open_race" else "locked"
        save_json("races.json", data)
        return f"{rid} is now {race['status']}"

    if action == "result":
        driver = str(p.get("driver", "")).strip()
        pos = int(p.get("position", 0))
        if not driver or pos < 1:
            raise ValueError("Driver and position are required")
        race.setdefault("results", []).append(
            {"driver": driver, "position": pos, "points": points_for_position(pos), "recorded_by": actor}
        )
        race["results"].sort(key=lambda x: x.get("position", 999))
        save_json("races.json", data)
        return f"Recorded P{pos} — {driver}"

    if action == "qualifying":
        driver = str(p.get("driver", "")).strip()
        lap = str(p.get("lap_time", "")).strip()
        pos = int(p.get("position", 0))
        if not driver or not lap or pos < 1:
            raise ValueError("Driver, lap time and position are required")
        race["qualifying"] = [
            x for x in race.get("qualifying", []) if x.get("position") != pos
        ] + [{"driver": driver, "lap_time": lap, "position": pos, "recorded_by": actor}]
        race["qualifying"].sort(key=lambda x: x.get("position", 999))
        save_json("races.json", data)
        return f"Recorded qualifying P{pos} — {driver}"

    if action == "penalty":
        driver = str(p.get("driver", "")).strip()
        pts = int(p.get("points", 0))
        reason = str(p.get("reason", "")).strip()
        if not driver or pts < 1 or not reason:
            raise ValueError("Driver, penalty and reason are required")
        race.setdefault("penalties", []).append(
            {
                "driver": driver,
                "points": pts,
                "reason": reason,
                "issued_by": actor,
                "created_at": now(),
            }
        )
        save_json("races.json", data)
        return f"Issued {pts} point penalty to {driver}"

    raise ValueError("Unknown action")


HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CRC Control Center</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,-apple-system,sans-serif;background:#07090c;color:#eef2f6}button,input{font:inherit}.hidden{display:none!important}
.login{min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(circle at 70% 0,#252c35,transparent 35%),#07090c}.loginbox{width:min(430px,94vw);background:#10151b;border:1px solid #29323c;border-radius:20px;padding:30px;box-shadow:0 30px 100px #0009}.ey{color:#7d8996;font-size:11px;letter-spacing:.16em;font-weight:900}.loginbox h1{margin:8px 0 6px;font-size:30px;letter-spacing:-.05em}.loginbox p{color:#7e8995;margin:0 0 25px}.field{margin-top:12px}.field label{display:block;color:#7e8995;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}input{width:100%;background:#0a0e12;border:1px solid #2a333e;color:#fff;border-radius:9px;padding:11px;outline:none}input:focus{border-color:#8995a2}.btn{border:0;border-radius:9px;padding:10px 14px;background:#eef2f6;color:#0b0d10;font-weight:900;cursor:pointer}.btn.dark{background:#161c23;color:#eef2f6;border:1px solid #2a333e}.btn.red{background:#2a171b;color:#ffb2b2}.err{color:#ff9898;font-size:12px;margin-top:10px}.hint{font-size:11px;color:#697580;margin-top:12px;line-height:1.5}
.app{display:flex;min-height:100vh}.side{width:240px;background:#0d1014;border-right:1px solid #222a33;padding:22px 14px;position:fixed;height:100vh}.brand{padding:8px 10px 25px}.brand b{font-size:19px;letter-spacing:-.04em}.brand small{display:block;color:#75808c;margin-top:4px}.nav button{width:100%;text-align:left;border:0;background:transparent;color:#929ca7;padding:12px;border-radius:10px;margin:2px 0;cursor:pointer;font-weight:700}.nav button.active,.nav button:hover{background:#191f27;color:#fff}.main{margin-left:240px;width:calc(100% - 240px);padding:28px;max-width:1500px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}.title{font-size:34px;font-weight:900;letter-spacing:-.05em;margin-top:3px}.user{display:flex;gap:10px;align-items:center;background:#11161c;border:1px solid #252e38;border-radius:12px;padding:8px 12px}.avatar{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#fff,#737d88);color:#111;display:grid;place-items:center;font-weight:900}.dot{width:7px;height:7px;background:#72d68b;border-radius:50%;display:inline-block;margin-right:6px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:15px}.card,.panel{background:linear-gradient(145deg,#151a21,#0f1318);border:1px solid #252e38;border-radius:16px;box-shadow:0 18px 50px #0005}.card{padding:18px}.label{font-size:10px;color:#7e8995;text-transform:uppercase;letter-spacing:.12em;font-weight:800}.big{font-size:30px;font-weight:900;margin-top:7px}.page{display:none}.page.active{display:block}.grid{display:grid;grid-template-columns:1.4fr .8fr;gap:12px}.panel h2{font-size:14px;margin:0;padding:16px 18px;border-bottom:1px solid #252e38}.body{padding:17px}.row{display:grid;grid-template-columns:35px 1fr 115px 70px;gap:10px;align-items:center;padding:13px 0;border-bottom:1px solid #20262d}.muted{font-size:12px;color:#78838f}.pill{font-size:10px;font-weight:900;border:1px solid #303a45;border-radius:99px;padding:5px 8px}.form{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.notice{margin-top:10px;padding:10px;border:1px solid #2a333e;border-radius:9px;color:#aeb8c1}.staff{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid #20262d}.badge{font-size:10px;font-weight:900;border-radius:99px;padding:5px 8px;background:#1b222b;color:#cbd3da}.on{color:#79d58d}.off{color:#d97d7d}.search{max-width:360px;margin-bottom:12px}
@media(max-width:900px){.side{width:72px}.brand b,.brand small,.nav span{display:none}.main{margin-left:72px;width:calc(100% - 72px)}.cards{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}}@media(max-width:550px){.main{padding:16px}.cards{grid-template-columns:1fr 1fr}.form{grid-template-columns:1fr}.title{font-size:26px}.top{align-items:flex-start;gap:10px}.user{font-size:11px}}
</style></head><body><div id="root"></div>
<script>
let me=null, data=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opt={}){let r=await fetch(path,{...opt,headers:{'Content-Type':'application/json',...(opt.headers||{})}});let d=await r.json();if(r.status===401){me=null;renderLogin();throw Error(d.error||'Session expired')}if(!r.ok)throw Error(d.error||'Request failed');return d}
function renderSetup(msg=''){root.innerHTML=`<div class="login"><div class="loginbox"><div class="ey">CIRRUS RACING CLUB</div><h1>Initialize Control Center</h1><p>Create the first CRC admin account. This setup closes permanently after the first admin is created.</p><form onsubmit="setup(event)"><div class="field"><label>Admin username</label><input id="su" autocomplete="username" required></div><div class="field"><label>Admin password</label><input id="sp" type="password" autocomplete="new-password" minlength="12" required></div><div class="field"><label>Confirm password</label><input id="sc" type="password" autocomplete="new-password" minlength="12" required></div><div class="field"><label>Setup key <span class="muted">(only if configured)</span></label><input id="sk" type="password" autocomplete="off"></div><button class="btn" style="width:100%;margin-top:16px">Create admin account</button>${msg?`<div class="err">${esc(msg)}</div>`:''}</form><div class="hint">Use a private password of at least 12 characters. If DASHBOARD_SETUP_KEY is configured on the host, it is required here and is never stored in GitHub.</div></div></div>`}
function renderLogin(msg=''){root.innerHTML=`<div class="login"><div class="loginbox"><div class="ey">CIRRUS RACING CLUB</div><h1>Control Center</h1><p>Race Control administration portal</p><form onsubmit="login(event)"><div class="field"><label>Username</label><input id="u" autocomplete="username" required></div><div class="field"><label>Password</label><input id="pw" type="password" autocomplete="current-password" required></div><button class="btn" style="width:100%;margin-top:16px">Sign in</button>${msg?`<div class="err">${esc(msg)}</div>`:''}</form></div></div>`}
async function setup(e){e.preventDefault();if(sp.value!==sc.value){renderSetup('Passwords do not match');return}try{me=await api('/api/setup',{method:'POST',body:JSON.stringify({username:su.value,password:sp.value,setup_key:sk.value})});renderApp()}catch(x){renderSetup(x.message)}}
async function login(e){e.preventDefault();try{me=await api('/api/login',{method:'POST',body:JSON.stringify({username:u.value,password:pw.value})});renderApp()}catch(x){renderLogin(x.message)}}
async function logout(){try{await api('/api/logout',{method:'POST'})}catch(_){}me=null;renderLogin()}
function nav(page){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));let el=document.getElementById(page);if(el)el.classList.add('active');document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===page));if(page==='staff')loadStaff();if(page==='audit')loadAudit();}
function renderApp(){let admin=me.role==='admin';root.innerHTML=`<aside class="side"><div class="brand"><b>CRC</b><small>CONTROL CENTER</small></div><div class="nav"><button data-page="overview" onclick="nav('overview')">▦ <span>Overview</span></button><button data-page="races" onclick="nav('races')">◈ <span>Races</span></button><button data-page="control" onclick="nav('control')">◆ <span>Race Control</span></button>${admin?`<button data-page="staff" onclick="nav('staff')">◎ <span>Staff</span></button><button data-page="audit" onclick="nav('audit')">≡ <span>Audit Log</span></button>`:''}</div></aside><main class="main"><div class="top"><div><div class="ey">CIRRUS RACING CLUB</div><div class="title">Control Center</div></div><div class="user"><div class="avatar">${esc(me.username.slice(0,1).toUpperCase())}</div><div><b>${esc(me.username)}</b><div class="muted"><span class="dot"></span>${esc(me.role)}</div></div><button class="btn dark" onclick="logout()">Log out</button></div></div><section id="overview" class="page active"></section><section id="races" class="page"></section><section id="control" class="page"></section>${admin?`<section id="staff" class="page"></section><section id="audit" class="page"></section>`:''}</main>`;renderOverview();renderRaces();renderControl();nav('overview')}
function renderOverview(){let s=data?.stats||{};document.getElementById('overview').innerHTML=`<div class="cards"><div class="card"><div class="label">Drivers</div><div class="big">${s.drivers||0}</div></div><div class="card"><div class="label">Races</div><div class="big">${s.races||0}</div></div><div class="card"><div class="label">Open</div><div class="big">${s.open||0}</div></div><div class="card"><div class="label">Completed</div><div class="big">${s.completed||0}</div></div></div><div class="grid"><div class="panel"><h2>Driver standings</h2><div class="body">${(data.drivers||[]).slice(0,10).map((d,i)=>`<div class="row"><b>#${i+1}</b><div><b>${esc(d.badge)} ${esc(d.name)}</b><div class="muted">${esc(d.rank)} · ${d.points} pts · ${d.starts} starts</div></div><span class="pill">${d.rating} rating</span><b>${d.wins}W</b></div>`).join('')||'<div class="muted">No drivers registered yet.</div>'}</div></div><div class="panel"><h2>Recent races</h2><div class="body">${(data.races||[]).slice(-6).reverse().map(r=>`<div class="staff"><div><b>${esc(r.id)}</b><div class="muted">${esc(r.name)} · ${esc(r.track)}</div></div><span class="badge">${esc(r.status||'open')}</span></div>`).join('')||'<div class="muted">No races yet.</div>'}</div></div></div>`}
function renderRaces(){document.getElementById('races').innerHTML=`<div class="grid"><div class="panel"><h2>Create race</h2><div class="body"><div class="form"><div class="field"><label>Race name</label><input id="rn"></div><div class="field"><label>Track</label><input id="rt"></div><div class="field"><label>Date / time</label><input id="rd" placeholder="2026-09-20 20:00"></div><div class="field"><label>Laps</label><input id="rl" type="number" min="1"></div></div><div class="actions"><button class="btn" onclick="act('create_race',{name:rn.value,track:rt.value,date:rd.value,laps:rl.value})">Create race</button></div><div id="raceMsg"></div></div></div><div class="panel"><h2>Race list</h2><div class="body" id="raceList"></div></div></div>`;refreshRaceList()}
function refreshRaceList(){let el=document.getElementById('raceList');if(!el)return;el.innerHTML=(data.races||[]).slice().reverse().map(r=>`<div class="staff"><div><b>${esc(r.id)} — ${esc(r.name)}</b><div class="muted">${esc(r.track)} · ${esc(r.date)} · ${r.laps} laps</div></div><span class="badge">${esc(r.status||'open')}</span></div>`).join('')||'<div class="muted">No races yet.</div>'}
function renderControl(){document.getElementById('control').innerHTML=`<div class="grid"><div class="panel"><h2>Race actions</h2><div class="body"><div class="field"><label>Race ID</label><input id="rid" placeholder="CRC-26-001"></div><div class="actions"><button class="btn" onclick="act('open_race',{race_id:rid.value})">Open</button><button class="btn dark" onclick="act('lock_race',{race_id:rid.value})">Lock</button></div><hr style="border:0;border-top:1px solid #252e38;margin:18px 0"><div class="form"><div class="field"><label>Driver</label><input id="driver"></div><div class="field"><label>Position</label><input id="pos" type="number" min="1"></div><div class="field"><label>Qualifying lap</label><input id="lap" placeholder="1:52.345"></div><div class="field"><label>Penalty points</label><input id="pp" type="number" min="1"></div><div class="field" style="grid-column:1/-1"><label>Penalty reason</label><input id="reason"></div></div><div class="actions"><button class="btn" onclick="act('result',{race_id:rid.value,driver:driver.value,position:pos.value})">Record result</button><button class="btn dark" onclick="act('qualifying',{race_id:rid.value,driver:driver.value,lap_time:lap.value,position:pos.value})">Record qualifying</button><button class="btn red" onclick="act('penalty',{race_id:rid.value,driver:driver.value,points:pp.value,reason:reason.value})">Issue penalty</button></div><div id="controlMsg"></div></div></div><div class="panel"><h2>Quick status</h2><div class="body"><div class="notice">Logged in as <b>${esc(me.username)}</b> · <b>${esc(me.role)}</b><br><span class="muted">All dashboard actions are written to the audit log.</span></div></div></div></div>`}
async function act(action,p){try{let d=await api('/api/action',{method:'POST',body:JSON.stringify({action,...p})});data=await api('/api/data');renderOverview();refreshRaceList();let m=document.getElementById('controlMsg')||document.getElementById('raceMsg');if(m)m.innerHTML=`<div class="notice">${esc(d.message)}</div>`}catch(x){let m=document.getElementById('controlMsg')||document.getElementById('raceMsg');if(m)m.innerHTML=`<div class="err">${esc(x.message)}</div>`}}
async function loadStaff(){let el=document.getElementById('staff');if(!el)return;try{let d=await api('/api/staff');el.innerHTML=`<div class="panel"><h2>Staff & access</h2><div class="body"><div class="notice">Only admins can create or disable staff accounts. Race Hosters cannot create admins or other hosters.</div><div class="form" style="margin-top:15px"><div class="field"><label>Hoster username</label><input id="hu"></div><div class="field"><label>Temporary password</label><input id="hp" type="password" minlength="12"></div></div><div class="actions"><button class="btn" onclick="createHoster()">Create Race Hoster</button></div><div id="staffMsg"></div><div style="margin-top:18px">${d.users.map(u=>`<div class="staff"><div><b>${esc(u.username)}</b><div class="muted">${esc(u.role)} · created ${esc(u.created_at||'')}</div></div><span class="badge ${u.active?'on':'off'}">${u.active?'ACTIVE':'DISABLED'}</span><button class="btn dark" onclick="toggleStaff('${encodeURIComponent(u.username)}')">${u.active?'Disable':'Enable'}</button></div>`).join('')}</div></div></div>`}catch(x){el.innerHTML=`<div class="panel"><div class="body err">${esc(x.message)}</div></div>`}}
async function createHoster(){try{let d=await api('/api/staff/create',{method:'POST',body:JSON.stringify({username:hu.value,password:hp.value})});document.getElementById('staffMsg').innerHTML=`<div class="notice">${esc(d.message)}</div>`;loadStaff()}catch(x){document.getElementById('staffMsg').innerHTML=`<div class="err">${esc(x.message)}</div>`}}
async function toggleStaff(u){try{await api('/api/staff/toggle',{method:'POST',body:JSON.stringify({username:decodeURIComponent(u)})});loadStaff()}catch(x){alert(x.message)}}
async function loadAudit(){let el=document.getElementById('audit');if(!el)return;try{let d=await api('/api/audit');el.innerHTML=`<div class="panel"><h2>Audit history</h2><div class="body"><input class="search" id="auditSearch" placeholder="Search actor, action or detail" oninput="filterAudit()"><div id="auditRows">${d.entries.map(e=>`<div class="staff auditrow" data-search="${esc((e.actor+' '+e.action+' '+e.detail).toLowerCase())}"><div><b>${esc(e.action)}</b><div class="muted">${esc(e.actor)} · ${esc(e.detail)}</div></div><span class="badge">${esc(e.timestamp)}</span><span class="${e.success?'on':'off'}">${e.success?'OK':'FAIL'}</span></div>`).join('')||'<div class="muted">No audit entries yet.</div>'}</div></div></div>`}catch(x){el.innerHTML=`<div class="panel"><div class="body err">${esc(x.message)}</div></div>`}}
function filterAudit(){let q=(auditSearch.value||'').toLowerCase();document.querySelectorAll('.auditrow').forEach(x=>x.style.display=x.dataset.search.includes(q)?'grid':'none')}
async function boot(){try{let s=await api('/api/status');if(s.setup_required){renderSetup();return}let m=await api('/api/me');me=m;data=await api('/api/data');renderApp()}catch(x){renderLogin()}}
boot();
</script></body></html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "CRC-Control-Center/2.1"

    def log_message(self, format, *args):
        return

    def send_json(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self):
        raw = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON")

    def cookie(self, name: str) -> str | None:
        header = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(header)
            return jar[name].value if name in jar else None
        except Exception:
            return None

    def current_user(self) -> dict | None:
        token = self.cookie("crc_session")
        if not token:
            return None
        session = SESSIONS.get(token)
        if not session or session.get("expires", 0) < time.time():
            SESSIONS.pop(token, None)
            return None
        user = find_user(str(session.get("username", "")))
        if not user or not user.get("active", True):
            SESSIONS.pop(token, None)
            return None
        session["expires"] = time.time() + SESSION_TTL
        return user

    def require_user(self, admin: bool = False) -> dict | None:
        user = self.current_user()
        if not user:
            self.send_json(401, {"error": "Authentication required"})
            return None
        if admin and user.get("role") != "admin":
            self.send_json(403, {"error": "Admin access required"})
            return None
        return user

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/":
                self.send_html()
                return
            if path == "/api/status":
                self.send_json(200, {"setup_required": not has_admin()})
                return
            if path == "/api/me":
                user = self.current_user()
                if not user:
                    self.send_json(401, {"error": "Authentication required"})
                    return
                self.send_json(200, {"username": user["username"], "role": user["role"], "active": True})
                return
            if path == "/api/data":
                if not self.require_user():
                    return
                self.send_json(200, read_data())
                return
            if path == "/api/staff":
                if not self.require_user(admin=True):
                    return
                safe = [
                    {k: u.get(k) for k in ("username", "role", "active", "created_at", "created_by")}
                    for u in users()
                ]
                self.send_json(200, {"users": safe})
                return
            if path == "/api/audit":
                if not self.require_user(admin=True):
                    return
                self.send_json(200, load_json("audit_log.json", {"entries": []}))
                return
            self.send_json(404, {"error": "Not found"})
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            p = self.body()

            if path == "/api/setup":
                if has_admin():
                    self.send_json(409, {"error": "Initial setup is already complete"})
                    return
                username = str(p.get("username", "")).strip()
                password = str(p.get("password", ""))
                setup_key = str(p.get("setup_key", ""))
                configured_key = os.getenv("DASHBOARD_SETUP_KEY", "").strip()
                if configured_key and not hmac.compare_digest(setup_key, configured_key):
                    self.send_json(403, {"error": "Invalid setup key"})
                    return
                if not username or len(username) < 3 or len(username) > 32:
                    self.send_json(400, {"error": "Username must be 3–32 characters"})
                    return
                if not username.replace("_", "").replace("-", "").isalnum():
                    self.send_json(400, {"error": "Username may only use letters, numbers, _ and -"})
                    return
                if len(password) < 12:
                    self.send_json(400, {"error": "Password must be at least 12 characters"})
                    return
                data = staff()
                if data.get("users"):
                    self.send_json(409, {"error": "An account already exists"})
                    return
                user = {
                    "username": username,
                    "role": "admin",
                    "active": True,
                    "password_hash": password_hash(password),
                    "created_at": now(),
                    "created_by": "initial_setup",
                }
                data["users"] = [user]
                save_json("staff.json", data)
                audit(username, "INITIAL_SETUP", "Created the first CRC admin account")
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = {"username": username, "expires": time.time() + SESSION_TTL}
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Set-Cookie", f"crc_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}")
                raw = json.dumps({"username": username, "role": "admin", "active": True}).encode()
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/login":
                username = str(p.get("username", "")).strip()
                password = str(p.get("password", ""))
                ip = self.client_address[0]
                attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if t > time.time() - 300]
                if len(attempts) >= 8:
                    self.send_json(429, {"error": "Too many login attempts. Try again in a few minutes."})
                    return
                user = find_user(username)
                if not user or not user.get("active", True) or not password_ok(password, str(user.get("password_hash", ""))):
                    attempts.append(time.time())
                    LOGIN_ATTEMPTS[ip] = attempts
                    audit(username or "unknown", "LOGIN_FAILED", "Invalid credentials", False)
                    self.send_json(401, {"error": "Invalid username or password"})
                    return
                LOGIN_ATTEMPTS.pop(ip, None)
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = {"username": user["username"], "expires": time.time() + SESSION_TTL}
                audit(user["username"], "LOGIN", "Dashboard sign-in")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Set-Cookie", f"crc_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}")
                raw = json.dumps({"username": user["username"], "role": user["role"], "active": True}).encode()
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/logout":
                token = self.cookie("crc_session")
                user = self.current_user()
                if token:
                    SESSIONS.pop(token, None)
                if user:
                    audit(user["username"], "LOGOUT", "Dashboard sign-out")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "crc_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                raw = b'{"ok":true}'
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/action":
                user = self.require_user()
                if not user:
                    return
                action = str(p.pop("action", ""))
                message = do_action(action, p, user["username"])
                audit(user["username"], action.upper(), message)
                self.send_json(200, {"message": message})
                return

            if path == "/api/staff/create":
                admin = self.require_user(admin=True)
                if not admin:
                    return
                username = str(p.get("username", "")).strip()
                password = str(p.get("password", ""))
                if not username or len(username) < 3 or len(username) > 32:
                    raise ValueError("Username must be 3–32 characters")
                if not username.replace("_", "").replace("-", "").isalnum():
                    raise ValueError("Username may only use letters, numbers, _ and -")
                if len(password) < 12:
                    raise ValueError("Password must be at least 12 characters")
                if find_user(username):
                    raise ValueError("That username already exists")
                data = staff()
                data.setdefault("users", []).append(
                    {
                        "username": username,
                        "role": "race_hoster",
                        "active": True,
                        "password_hash": password_hash(password),
                        "created_at": now(),
                        "created_by": admin["username"],
                    }
                )
                save_json("staff.json", data)
                audit(admin["username"], "CREATE_HOSTER", f"Created race hoster {username}")
                self.send_json(200, {"message": f"Race Hoster account {username} created"})
                return

            if path == "/api/staff/toggle":
                admin = self.require_user(admin=True)
                if not admin:
                    return
                username = str(p.get("username", "")).strip()
                target = find_user(username)
                if not target:
                    raise ValueError("Staff account not found")
                if target.get("role") == "admin":
                    raise ValueError("The admin account cannot be disabled from this panel")
                target["active"] = not bool(target.get("active", True))
                data = staff()
                save_json("staff.json", data)
                audit(admin["username"], "TOGGLE_HOSTER", f"{username} active={target['active']}")
                self.send_json(200, {"ok": True})
                return

            self.send_json(404, {"error": "Not found"})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})


def start_dashboard(port: int = DEFAULT_PORT):
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"CRC Control Center running on port {port}")
    return server
