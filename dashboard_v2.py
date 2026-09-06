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
from urllib.parse import parse_qs, urlparse

from constants import points_for_position
from storage import load_json, save_json

DEFAULT_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
SESSION_TTL = 60 * 60 * 12
DATA_LOCK = Lock()
SESSIONS: dict[str, dict] = {}

RANKS = ((0, "AMATEUR", "🟢"), (1000, "NOVICE", "🔵"), (1500, "COMPETITOR", "🟣"), (2100, "EXPERT", "🟠"), (2800, "MASTER", "🔴"), (3600, "ELITE", "🟡"))


def now():
    return datetime.now(timezone.utc).isoformat()


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return f"pbkdf2_sha256$180000${salt.hex()}${digest.hex()}"


def password_ok(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def staff():
    with DATA_LOCK:
        data = load_json("staff.json", {"users": []})
        users = data.setdefault("users", [])
        if not users:
            username = os.getenv("DASHBOARD_ADMIN_USERNAME", "admin").strip() or "admin"
            password = os.getenv("DASHBOARD_ADMIN_PASSWORD", "").strip()
            if password:
                users.append({"username": username, "role": "admin", "active": True, "password_hash": password_hash(password), "created_at": now(), "created_by": "system"})
                save_json("staff.json", data)
        return data


def audit(actor: str, action: str, detail: str, success: bool = True):
    with DATA_LOCK:
        data = load_json("audit_log.json", {"entries": []})
        entries = data.setdefault("entries", [])
        entries.insert(0, {"timestamp": now(), "actor": actor, "action": action, "detail": detail, "success": success})
        data["entries"] = entries[:500]
        save_json("audit_log.json", data)


def rank_for_rating(rating: int):
    current = RANKS[0]
    for rank in RANKS:
        if rating >= rank[0]:
            current = rank
    return current


def read_data():
    drivers = load_json("drivers.json", {"drivers": {}}).get("drivers", {})
    races = load_json("races.json", {"races": []}).get("races", [])
    profiles = []
    for entry in drivers.values():
        name = entry.get("name", "Unnamed")
        results = [x for r in races for x in r.get("results", []) if str(x.get("driver", "")).lower() == name.lower()]
        penalties = [x for r in races for x in r.get("penalties", []) if str(x.get("driver", "")).lower() == name.lower()]
        points = sum(int(x.get("points", 0)) for x in results) - sum(int(x.get("points", 0)) for x in penalties)
        rating = int(entry.get("rating", 0) or 0)
        rank, badge = rank_for_rating(rating)[1:]
        profiles.append({"name": name, "rating": rating, "rank": rank, "badge": badge, "wins": sum(int(x.get("position", 999)) == 1 for x in results), "podiums": sum(int(x.get("position", 999)) <= 3 for x in results), "points": points, "starts": len(results)})
    profiles.sort(key=lambda x: (-x["rating"], -x["points"], x["name"].lower()))
    return {"drivers": profiles, "races": races, "stats": {"drivers": len(profiles), "races": len(races), "completed": sum(r.get("status") == "locked" for r in races), "open": sum(r.get("status") != "locked" for r in races)}}


def next_race_id(races):
    year = datetime.now(timezone.utc).year % 100
    prefix = f"CRC-{year:02d}-"
    seq = max([int(str(r.get("id", ""))[len(prefix):]) for r in races if str(r.get("id", "")).startswith(prefix) and str(r.get("id", ""))[len(prefix):].isdigit()] or [0])
    return f"{prefix}{seq + 1:03d}"


def do_action(action, p):
    data = load_json("races.json", {"races": []})
    races = data.setdefault("races", [])
    if action == "create_race":
        name, track, date = str(p.get("name", "")).strip(), str(p.get("track", "")).strip(), str(p.get("date", "")).strip()
        laps = int(p.get("laps", 0))
        if not name or not track or not date or laps < 1: raise ValueError("Complete race details are required")
        race = {"id": next_race_id(races), "name": name, "track": track, "laps": laps, "date": date, "status": "open", "created_by": "dashboard", "created_at": now(), "qualifying": [], "results": [], "penalties": [], "reports": [], "reminders_sent": [], "channel_id": None}
        races.append(race); save_json("races.json", data); return f"Created {race['id']} — {name}"
    rid = str(p.get("race_id", "")).upper()
    race = next((r for r in races if str(r.get("id", "")).upper() == rid), None)
    if not race: raise ValueError("Race not found")
    if action in ("open_race", "lock_race"):
        race["status"] = "open" if action == "open_race" else "locked"; save_json("races.json", data); return f"{rid} is now {race['status']}"
    if action == "result":
        driver, pos = str(p.get("driver", "")).strip(), int(p.get("position", 0))
        if not driver or pos < 1: raise ValueError("Driver and position are required")
        race.setdefault("results", []).append({"driver": driver, "position": pos, "points": points_for_position(pos)})
        race["results"].sort(key=lambda x: x.get("position", 999)); save_json("races.json", data); return f"Recorded P{pos} — {driver}"
    if action == "qualifying":
        driver, lap, pos = str(p.get("driver", "")).strip(), str(p.get("lap_time", "")).strip(), int(p.get("position", 0))
        if not driver or not lap or pos < 1: raise ValueError("Driver, lap time and position are required")
        race["qualifying"] = [x for x in race.get("qualifying", []) if x.get("position") != pos] + [{"driver": driver, "lap_time": lap, "position": pos}]
        race["qualifying"].sort(key=lambda x: x.get("position", 999)); save_json("races.json", data); return f"Recorded qualifying P{pos} — {driver}"
    if action == "penalty":
        driver, pts, reason = str(p.get("driver", "")).strip(), int(p.get("points", 0)), str(p.get("reason", "")).strip()
        if not driver or pts < 1 or not reason: raise ValueError("Driver, penalty and reason are required")
        race.setdefault("penalties", []).append({"driver": driver, "points": pts, "reason": reason, "issued_by": p.get("actor", "dashboard"), "created_at": now()}); save_json("races.json", data); return f"Issued {pts} point penalty to {driver}"
    raise ValueError("Unknown action")


HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CRC Control Center</title><style>
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;background:#07090c;color:#eef2f6}button,input{font:inherit}.app{display:flex;min-height:100vh}.side{width:240px;background:#0d1014;border-right:1px solid #222a33;padding:22px 14px;position:fixed;height:100vh}.brand{padding:8px 10px 25px}.brand b{font-size:19px;letter-spacing:-.04em}.brand small{display:block;color:#75808c;margin-top:4px}.nav button{width:100%;text-align:left;border:0;background:transparent;color:#929ca7;padding:12px;border-radius:10px;margin:2px 0;cursor:pointer;font-weight:700}.nav button.active,.nav button:hover{background:#191f27;color:#fff}.main{margin-left:240px;width:calc(100% - 240px);padding:28px;max-width:1500px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}.ey{color:#7d8996;font-size:11px;letter-spacing:.16em;font-weight:800}.title{font-size:34px;font-weight:900;letter-spacing:-.05em;margin-top:3px}.user{display:flex;gap:10px;align-items:center;background:#11161c;border:1px solid #252e38;border-radius:12px;padding:8px 12px}.avatar{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#fff,#737d88);color:#111;display:grid;place-items:center;font-weight:900}.dot{width:7px;height:7px;background:#72d68b;border-radius:50%;display:inline-block;margin-right:6px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:15px}.card,.panel{background:linear-gradient(145deg,#151a21,#0f1318);border:1px solid #252e38;border-radius:16px;box-shadow:0 18px 50px #0005}.card{padding:18px}.label{font-size:10px;color:#7e8995;text-transform:uppercase;letter-spacing:.12em;font-weight:800}.big{font-size:30px;font-weight:900;margin-top:7px}.tabs{display:flex;gap:7px;margin:15px 0}.tab{background:#10151a;border:1px solid #252e38;color:#aeb7c0;border-radius:10px;padding:9px 13px;font-weight:800;cursor:pointer}.tab.active{background:#eef2f6;color:#0b0d10}.page{display:none}.page.active{display:block}.grid{display:grid;grid-template-columns:1.4fr .8fr;gap:12px}.panel h2{font-size:14px;margin:0;padding:16px 18px;border-bottom:1px solid #252e38}.body{padding:17px}.row{display:grid;grid-template-columns:35px 1fr 115px 70px;gap:10px;align-items:center;padding:13px 0;border-bottom:1px solid #20262d}.muted{font-size:12px;color:#78838f}.pill{font-size:10px;font-weight:900;border:1px solid #303a45;border-radius:99px;padding:5px 8px}.form{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.field label{display:block;color:#7e8995;font-size:10px;font-weight:800;text-transform:uppercase;margin-bottom:6px}input{width:100%;background:#0a0e12;border:1px solid #2a333e;color:#fff;border-radius:9px;padding:11px;outline:none}input:focus{border-color:#8995a2}.btn{border:0;border-radius:9px;padding:10px 14px;background:#eef2f6;color:#0b0d10;font-weight:900;cursor:pointer}.btn.dark{background:#161c23;color:#eef2f6;border:1px solid #2a333e}.btn.red{background:#2a171b;color:#ffb2b2}.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.notice{margin-top:10px;padding:10px;border:1px solid #2a333e;border-radius:9px;color:#aeb8c1}.staff{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid #20262d}.badge{font-size:10px;font-weight:900;border-radius:99px;padding:5px 8px;background:#1b222b;color:#cbd3da}.on{color:#79d58d}.off{color:#d97d7d}.login{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 70% 0,#252c35,transparent 35%),#07090c}.loginbox{width:min(420px,92vw);background:#10151b;border:1px solid #29323c;border-radius:20px;padding:30px;box-shadow:0 30px 100px #0009}.loginbox h1{margin:0;font-size:28px}.loginbox p{color:#7e8995;margin:7px 0 25px}.err{color:#ff9898;font-size:12px;margin-top:10px}@media(max-width:900px){.side{width:72px}.brand b,.brand small,.nav span{display:none}.main{margin-left:72px;width:calc(100% - 72px)}.cards{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}}@media(max-width:550px){.main{padding:16px}.cards{grid-template-columns:1fr 1fr}.form{grid-template-columns:1fr}.title{font-size:26px}}
</style></head><body><div id="root"></div><script>
let me=null;const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opt={}){let r=await fetch(path,{...opt,headers:{'Content-Type':'application/json',...(opt.headers||{})}});let d=await r.json();if(r.status===401){me=null;renderLogin();throw Error('Session expired')}if(!r.ok)throw Error(d.error||'Request failed');return d}
function renderLogin(msg=''){root.innerHTML=`<div class="login"><div class="loginbox"><div class="ey">CIRRUS RACING CLUB</div><h1>Control Center</h1><p>Race Control administration portal</p><form onsubmit="login(event)"><div class="field"><label>Username</label><input id="u" autocomplete="username"></div><div class="field" style="margin-top:12px"><label>Password</label><input id="pw" type="password" autocomplete="current-password"></div><button class="btn" style="width:100%;margin-top:16px">Sign in</button>${msg?`<div class="err">${esc(msg)}</div>`:''}</form></div></div>`}
async function login(e){e.preventDefault();try{me=await api('/api/login',{method:'POST',body:JSON.stringify({username:u.value,password:pw.value})});renderApp();}catch(x){renderLogin(x.message)}}
function nav(page){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));document.getElementById(page).classList.add('active');document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));document.querySelector(`[data-page="${page}"]`).classList.add('active');if(page==='audit')loadAudit();if(page==='staff')loadStaff()}
function renderApp(){root.innerHTML=`<aside class="side"><div class="brand"><b>CRC</b><small>CONTROL CENTER</small></div><div class="nav"><button class="active" data-page="home" onclick="nav('home')">⌂ <span>Overview</span></button><button data-page="races" onclick="nav('races')">◈ <span>Race Control</span></button><button data-page="drivers" onclick="nav('drivers')">◎ <span>Drivers</span></button>${me.role==='admin'?`<button data-page="staff" onclick="nav('staff')">♙ <span>Staff</span></button><button data-page="audit" onclick="nav('audit')">◌ <span>Audit Log</span></button>`:''}<button onclick="logout()">↪ <span>Sign out</span></button></div></aside><main class="main"><div class="top"><div><div class="ey">CIRRUS RACING CLUB</div><div class="title">Control Center</div></div><div class="user"><div class="avatar">${esc(me.username[0].toUpperCase())}</div><div><b>${esc(me.username)}</b><div class="muted"><span class="dot"></span>${esc(me.role)}</div></div></div></div><div id="pages"><section id="home" class="page active"><div class="cards"><div class="card"><div class="label">Drivers</div><div class="big" id="s1">—</div></div><div class="card"><div class="label">Races</div><div class="big" id="s2">—</div></div><div class="card"><div class="label">Completed</div><div class="big" id="s3">—</div></div><div class="card"><div class="label">Open events</div><div class="big" id="s4">—</div></div></div><div class="grid"><div class="panel"><h2>Driver Rankings</h2><div class="body" id="rankings"></div></div><div class="panel"><h2>Upcoming Events</h2><div class="body" id="upcoming"></div></div></div></section><section id="races" class="page"><div class="grid"><div class="panel"><h2>Create Race</h2><div class="body"><div class="form"><div class="field"><label>Name</label><input id="rn"></div><div class="field"><label>Track</label><input id="rt"></div><div class="field"><label>Laps</label><input id="rl" type="number"></div><div class="field"><label>Date / time</label><input id="rd"></div></div><div class="actions"><button class="btn" onclick="action('create_race',{name:rn.value,track:rt.value,laps:rl.value,date:rd.value})">Create race</button></div></div></div><div class="panel"><h2>Race Control</h2><div class="body"><div class="field"><label>Race ID</label><input id="rid" placeholder="CRC-26-001"></div><div class="actions"><button class="btn" onclick="action('open_race',{race_id:rid.value})">Open</button><button class="btn dark" onclick="action('lock_race',{race_id:rid.value})">Lock</button></div><hr style="border:0;border-top:1px solid #252e38;margin:18px 0"><div class="form"><div class="field"><label>Driver</label><input id="rdv"></div><div class="field"><label>Position</label><input id="rpos" type="number"></div></div><div class="actions"><button class="btn" onclick="action('result',{race_id:rid.value,driver:rdv.value,position:rpos.value})">Record result</button></div><div class="form" style="margin-top:10px"><div class="field"><label>Qualifying driver</label><input id="qd"></div><div class="field"><label>Lap time</label><input id="qt"></div><div class="field"><label>Grid</label><input id="qp" type="number"></div></div><div class="actions"><button class="btn dark" onclick="action('qualifying',{race_id:rid.value,driver:qd.value,lap_time:qt.value,position:qp.value})">Record qualifying</button></div><div class="form" style="margin-top:10px"><div class="field"><label>Penalty driver</label><input id="pd"></div><div class="field"><label>Points</label><input id="pp" type="number"></div></div><div class="field" style="margin-top:10px"><label>Reason</label><input id="pr"></div><div class="actions"><button class="btn red" onclick="action('penalty',{race_id:rid.value,driver:pd.value,points:pp.value,reason:pr.value})">Issue penalty</button></div><div id="notice" class="notice"></div></div></div></div></section><section id="drivers" class="page"><div class="panel"><h2>Driver Administration</h2><div class="body"><p class="muted">Driver administration remains available through the bot commands. This panel focuses on race operations and staff accountability.</p></div></div></section>${me.role==='admin'?`<section id="staff" class="page"><div class="grid"><div class="panel"><h2>Staff Accounts</h2><div class="body" id="staffList"></div></div><div class="panel"><h2>Add Race Hoster</h2><div class="body"><div class="field"><label>Username</label><input id="su"></div><div class="field" style="margin-top:10px"><label>Temporary password</label><input id="sp" type="password"></div><div class="actions"><button class="btn" onclick="addStaff()">Create hoster</button></div><div class="notice">Hosters can operate Race Control. Only Admin accounts can manage staff or view the audit log.</div></div></div></div></section><section id="audit" class="page"><div class="panel"><h2>Activity Log</h2><div class="body" id="auditList"></div></div></section>`:''}</div></main>`;loadHome()}
async function loadHome(){try{let d=await api('/api/data');s1.textContent=d.stats.drivers;s2.textContent=d.stats.races;s3.textContent=d.stats.completed;s4.textContent=d.stats.open;rankings.innerHTML=d.drivers.slice(0,10).map((x,i)=>`<div class="row"><b>${String(i+1).padStart(2,'0')}</b><div><b>${esc(x.name)}</b><div class="muted">${x.wins} wins · ${x.podiums} podiums · ${x.points} pts</div></div><span class="pill">${x.badge} ${esc(x.rank)}</span><b>${x.rating}</b></div>`).join('')||'<div class="muted">No drivers yet.</div>';upcoming.innerHTML=d.races.filter(x=>x.status!=='locked').slice(0,6).map(x=>`<div style="padding:12px 0;border-bottom:1px solid #20262d"><b>${esc(x.name)}</b><div class="muted">${esc(x.id)} · ${esc(x.track)} · ${x.laps} laps</div></div>`).join('')||'<div class="muted">No upcoming events.</div>'}catch(e){}}
async function action(action,p){try{let d=await api('/api/action',{method:'POST',body:JSON.stringify({action,...p})});notice.textContent='✓ '+d.message;notice.style.display='block';loadHome()}catch(e){notice.textContent='✕ '+e.message;notice.style.display='block'}}
async function addStaff(){try{let d=await api('/api/staff',{method:'POST',body:JSON.stringify({username:su.value,password:sp.value})});alert(d.message);su.value='';sp.value='';loadStaff()}catch(e){alert(e.message)}}
async function loadStaff(){if(!document.getElementById('staffList'))return;try{let d=await api('/api/staff');staffList.innerHTML=d.users.map(x=>`<div class="staff"><div><b>${esc(x.username)}</b><div class="muted">${esc(x.role)} · created ${esc(x.created_at||'')}</div></div><span class="badge ${x.active?'on':'off'}">${x.active?'ACTIVE':'DISABLED'}</span><button class="btn dark" onclick="toggleStaff('${encodeURIComponent(x.username)}')">${x.active?'Disable':'Enable'}</button></div>`).join('')}catch(e){}}
async function toggleStaff(u){try{await api('/api/staff/toggle',{method:'POST',body:JSON.stringify({username:decodeURIComponent(u)})});loadStaff()}catch(e){alert(e.message)}}
async function loadAudit(){if(!document.getElementById('auditList'))return;try{let d=await api('/api/audit');auditList.innerHTML=d.entries.map(x=>`<div style="padding:13px 0;border-bottom:1px solid #20262d"><b>${esc(x.actor)}</b> <span class="badge">${esc(x.action)}</span><div class="muted">${esc(x.detail)} · ${new Date(x.timestamp).toLocaleString()}</div></div>`).join('')||'<div class="muted">No activity yet.</div>'}catch(e){}}
async function logout(){await fetch('/api/logout',{method:'POST'});location.reload()}renderLogin();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def json(self, obj, status=200, headers=None):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store")
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)

    def session(self):
        jar=cookies.SimpleCookie(self.headers.get("Cookie", "")); sid=jar.get("crc_session")
        if not sid or sid.value not in SESSIONS: return None
        s=SESSIONS[sid.value]
        if s["expires"] < time.time(): SESSIONS.pop(sid.value,None); return None
        return s

    def body(self):
        n=int(self.headers.get("Content-Length","0")); return json.loads(self.rfile.read(min(n,100000)).decode())

    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/":
            raw=HTML.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        s=self.session()
        if not s: self.json({"error":"Unauthorized"},401); return
        if path=="/api/data": self.json(read_data()); return
        if path=="/api/staff":
            if s["role"]!="admin": self.json({"error":"Admin only"},403); return
            self.json({"users":[{k:v for k,v in u.items() if k!="password_hash"} for u in staff().get("users",[])]}); return
        if path=="/api/audit":
            if s["role"]!="admin": self.json({"error":"Admin only"},403); return
            self.json(load_json("audit_log.json",{"entries":[] })); return
        self.json({"error":"Not found"},404)

    def do_POST(self):
        path=urlparse(self.path).path
        if path=="/api/login":
            try:
                p=self.body(); username=str(p.get("username","")).strip(); password=str(p.get("password","")); found=next((u for u in staff().get("users",[]) if u.get("username")==username and u.get("active",True)),None)
                if not found or not password_ok(password,found.get("password_hash","")):
                    audit(username or "unknown","LOGIN_FAILED","Invalid credentials",False); self.json({"error":"Invalid username or password"},401); return
                sid=secrets.token_urlsafe(32); SESSIONS[sid]={"username":username,"role":found.get("role","hoster"),"expires":time.time()+SESSION_TTL}; audit(username,"LOGIN","Signed in")
                self.json({"username":username,"role":found.get("role","hoster")},headers={"Set-Cookie":f"crc_session={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}"}); return
            except Exception as e: self.json({"error":str(e)},400); return
        if path=="/api/logout":
            s=self.session();
            if s: audit(s["username"],"LOGOUT","Signed out")
            jar=cookies.SimpleCookie(self.headers.get("Cookie","")); sid=jar.get("crc_session");
            if sid: SESSIONS.pop(sid.value,None)
            self.json({"ok":True},headers={"Set-Cookie":"crc_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"}); return
        s=self.session()
        if not s: self.json({"error":"Unauthorized"},401); return
        try:
            p=self.body()
            if path=="/api/staff":
                if s["role"]!="admin": raise PermissionError("Admin only")
                username=str(p.get("username","")).strip(); password=str(p.get("password",""))
                if len(username)<3 or len(password)<8: raise ValueError("Username must be 3+ characters and password 8+ characters")
                data=staff(); users=data.setdefault("users",[])
                if any(u.get("username")==username for u in users): raise ValueError("Username already exists")
                users.append({"username":username,"role":"hoster","active":True,"password_hash":password_hash(password),"created_at":now(),"created_by":s["username"]}); save_json("staff.json",data); audit(s["username"],"STAFF_CREATE",f"Created race hoster {username}"); self.json({"message":f"Created {username}"}); return
            if path=="/api/staff/toggle":
                if s["role"]!="admin": raise PermissionError("Admin only")
                username=str(p.get("username","")); data=staff(); user=next((u for u in data["users"] if u.get("username")==username),None)
                if not user: raise ValueError("User not found")
                if user.get("role")=="admin": raise ValueError("Admin account cannot be disabled here")
                user["active"]=not user.get("active",True); save_json("staff.json",data); audit(s["username"],"STAFF_TOGGLE",f"{username} → {'active' if user['active'] else 'disabled'}"); self.json({"ok":True}); return
            if path=="/api/action":
                action=str(p.pop("action","")); allowed_admin={"create_race","open_race","lock_race","result","qualifying","penalty"}; allowed_hoster={"create_race","open_race","lock_race","result","qualifying","penalty"}
                if action not in (allowed_admin if s["role"]=="admin" else allowed_hoster): raise PermissionError("You do not have permission for that action")
                p["actor"]=s["username"]; message=do_action(action,p); audit(s["username"],action,message); self.json({"message":message}); return
            raise ValueError("Not found")
        except PermissionError as e: self.json({"error":str(e)},403)
        except Exception as e:
            audit(s["username"],"ACTION_FAILED",str(e),False); self.json({"error":str(e)},400)


def start_dashboard(port=DEFAULT_PORT):
    server=ThreadingHTTPServer(("0.0.0.0",port),Handler); Thread(target=server.serve_forever,name="crc-dashboard",daemon=True).start(); print(f"CRC Control Center listening on port {port}"); return server

if __name__=="__main__": start_dashboard()
