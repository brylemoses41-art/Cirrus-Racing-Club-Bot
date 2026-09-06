from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlparse

from dashboard_v2 import do_action, read_data

DEFAULT_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
SESSION_TTL = 60 * 60 * 12
PASSWORD_ROUNDS = 220_000
DATA_LOCK = Lock()
SESSIONS: dict[str, dict] = {}
LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _path(name: str) -> str:
    os.makedirs("data", exist_ok=True)
    return os.path.join("data", name)


def load_staff() -> dict:
    path = _path("staff.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"users": []}
    data.setdefault("users", [])
    return data


def save_staff(data: dict) -> None:
    path = _path("staff.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def find_user(username: str):
    target = username.strip().lower()
    return next((u for u in load_staff()["users"] if str(u.get("username", "")).lower() == target), None)


def has_admin() -> bool:
    return any(u.get("role") == "admin" and u.get("active", True) for u in load_staff()["users"])


def audit(actor: str, action: str, detail: str, success: bool = True) -> None:
    path = _path("audit_log.json")
    with DATA_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"entries": []}
        entries = data.setdefault("entries", [])
        entries.insert(0, {"timestamp": time.time(), "actor": actor, "action": action, "detail": detail, "success": success})
        data["entries"] = entries[:500]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def new_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "username": user["username"],
        "role": user.get("role", "hoster"),
        "expires": time.time() + SESSION_TTL,
    }
    return token


def session_from(handler):
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        session = SESSIONS.get(token)
        if session and session.get("expires", 0) > time.time():
            return token, session
        if token:
            SESSIONS.pop(token, None)
    return None, None


def body(handler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw = handler.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CRC Control Center</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,-apple-system,sans-serif;background:#07090c;color:#eef2f6}button,input{font:inherit}.hidden{display:none!important}
.auth{min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(circle at 70% 0,#29323d,transparent 38%),#07090c}.authbox{width:min(430px,94vw);background:#10151b;border:1px solid #29323c;border-radius:22px;padding:30px;box-shadow:0 30px 100px #0009}.ey{color:#7d8996;font-size:11px;letter-spacing:.16em;font-weight:900}.authbox h1{margin:8px 0 5px;font-size:31px;letter-spacing:-.05em}.sub{color:#7e8995;margin:0 0 24px}.tabs{display:grid;grid-template-columns:1fr 1fr;background:#0a0e12;padding:4px;border-radius:10px;margin-bottom:16px}.tabs button{border:0;background:transparent;color:#7d8996;padding:9px;border-radius:7px;font-weight:800;cursor:pointer}.tabs button.active{background:#1b222a;color:#fff}.field{margin-top:12px}.field label{display:block;color:#7e8995;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}input{width:100%;background:#0a0e12;border:1px solid #2a333e;color:#fff;border-radius:9px;padding:11px;outline:none}input:focus{border-color:#8995a2}.btn{width:100%;border:0;border-radius:9px;padding:11px;margin-top:16px;background:#eef2f6;color:#0b0d10;font-weight:900;cursor:pointer}.err{color:#ff9898;font-size:12px;margin-top:10px}.hint{font-size:11px;color:#697580;margin-top:12px;line-height:1.5}.app{display:flex;min-height:100vh}.side{width:240px;background:#0d1014;border-right:1px solid #222a33;padding:22px 14px;position:fixed;height:100vh}.brand{padding:8px 10px 25px}.brand b{font-size:19px}.brand small{display:block;color:#75808c;margin-top:4px}.nav button{width:100%;text-align:left;border:0;background:transparent;color:#929ca7;padding:12px;border-radius:10px;margin:2px 0;cursor:pointer;font-weight:700}.nav button.active,.nav button:hover{background:#191f27;color:#fff}.main{margin-left:240px;width:calc(100% - 240px);padding:28px;max-width:1500px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}.title{font-size:34px;font-weight:900;letter-spacing:-.05em}.user{display:flex;gap:10px;align-items:center;background:#11161c;border:1px solid #252e38;border-radius:12px;padding:8px 12px}.avatar{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#fff,#737d88);color:#111;display:grid;place-items:center;font-weight:900}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:15px}.card,.panel{background:linear-gradient(145deg,#151a21,#0f1318);border:1px solid #252e38;border-radius:16px;box-shadow:0 18px 50px #0005}.card{padding:18px}.label{font-size:10px;color:#7e8995;text-transform:uppercase;letter-spacing:.12em;font-weight:800}.big{font-size:30px;font-weight:900;margin-top:7px}.page{display:none}.page.active{display:block}.grid{display:grid;grid-template-columns:1.4fr .8fr;gap:12px}.panel h2{font-size:14px;margin:0;padding:16px 18px;border-bottom:1px solid #252e38}.body{padding:17px}.row{display:grid;grid-template-columns:35px 1fr 115px 70px;gap:10px;align-items:center;padding:13px 0;border-bottom:1px solid #20262d}.muted{font-size:12px;color:#78838f}.pill{font-size:10px;font-weight:900;border:1px solid #303a45;border-radius:99px;padding:5px 8px}.form{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.actions .btn{width:auto;margin:0}.staff{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid #20262d}.badge{font-size:10px;font-weight:900;border-radius:99px;padding:5px 8px;background:#1b222b;color:#cbd3da}@media(max-width:900px){.side{width:72px}.brand b,.brand small,.nav span{display:none}.main{margin-left:72px;width:calc(100% - 72px)}.cards{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}}@media(max-width:550px){.main{padding:16px}.cards{grid-template-columns:1fr 1fr}.form{grid-template-columns:1fr}.title{font-size:26px}.top{align-items:flex-start;gap:10px}}
</style></head><body><div id="root"></div>
<script>
let token=sessionStorage.getItem('crc_token')||'',me=null,data=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opt={}){let headers={'Content-Type':'application/json',...(opt.headers||{})};if(token)headers.Authorization='Bearer '+token;let r=await fetch(path,{...opt,headers});let d=await r.json();if(r.status===401){token='';sessionStorage.removeItem('crc_token');renderAuth('login');throw Error(d.error||'Session expired')}if(!r.ok)throw Error(d.error||'Request failed');return d}
function renderAuth(mode='login'){document.getElementById('root').innerHTML=`<div class="auth"><div class="authbox"><div class="ey">CIRRUS RACING CLUB</div><h1>Control Center</h1><p class="sub">Race operations, standings and administration.</p><div class="tabs"><button class="${mode==='login'?'active':''}" onclick="renderAuth('login')">Sign in</button><button class="${mode==='signup'?'active':''}" onclick="renderAuth('signup')">Create account</button></div>${mode==='login'?`<div class="field"><label>Username</label><input id="u" autocomplete="username"></div><div class="field"><label>Password</label><input id="p" type="password" autocomplete="current-password"></div><button class="btn" onclick="login()">Sign in</button><div id="err"></div>`:`<div class="field"><label>Username</label><input id="u" autocomplete="username"></div><div class="field"><label>Password</label><input id="p" type="password" autocomplete="new-password"></div><div class="field"><label>Confirm password</label><input id="c" type="password" autocomplete="new-password"></div><div class="field"><label>Admin access key <span style="text-transform:none">(optional)</span></label><input id="k" type="password" autocomplete="off" placeholder="Leave blank for Race Hoster"></div><button class="btn" onclick="signup()">Create account</button><div class="hint">A correct admin access key creates an Admin account. Leaving it blank creates a Race Hoster account.</div><div id="err"></div>`}</div></div>`}
async function login(){let err=document.getElementById('err');try{let d=await api('/api/login',{method:'POST',body:JSON.stringify({username:u.value,password:p.value})});token=d.token;sessionStorage.setItem('crc_token',token);await boot()}catch(e){err.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
async function signup(){let err=document.getElementById('err');try{if(p.value!==c.value)throw Error('Passwords do not match');let d=await api('/api/signup',{method:'POST',body:JSON.stringify({username:u.value,password:p.value,admin_key:k.value})});token=d.token;sessionStorage.setItem('crc_token',token);await boot()}catch(e){err.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
function nav(page){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));document.getElementById(page).classList.add('active');document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));let b=document.querySelector('[data-page="'+page+'"]');if(b)b.classList.add('active');document.getElementById('pageTitle').textContent=page[0].toUpperCase()+page.slice(1)}
function renderApp(){document.getElementById('root').innerHTML=`<div class="app"><aside class="side"><div class="brand"><b>CRC</b><small>Control Center</small></div><div class="nav"><button data-page="overview" class="active" onclick="nav('overview')">⌂ <span>Overview</span></button><button data-page="races" onclick="nav('races')">▣ <span>Races</span></button><button data-page="drivers" onclick="nav('drivers')">◉ <span>Drivers</span></button>${me.role==='admin'?'<button data-page="staff" onclick="nav(\'staff\')">♙ <span>Staff</span></button><button data-page="audit" onclick="nav(\'audit\')">≡ <span>Audit Log</span></button>':''}<button onclick="logout()">↪ <span>Sign out</span></button></div></aside><main class="main"><div class="top"><div><div class="ey">CRC OPERATIONS</div><div class="title" id="pageTitle">Overview</div></div><div class="user"><div class="avatar">${esc(me.username[0]?.toUpperCase()||'?')}</div><div><b>${esc(me.username)}</b><div class="muted">${me.role==='admin'?'Administrator':'Race Hoster'}</div></div></div></div><section id="overview" class="page active"></section><section id="races" class="page"></section><section id="drivers" class="page"></section>${me.role==='admin'?'<section id="staff" class="page"></section><section id="audit" class="page"></section>':''}</main></div>`;renderOverview();renderRaces();renderDrivers();if(me.role==='admin'){renderStaff();renderAudit()}}
function renderOverview(){let s=data.stats||{};overview.innerHTML=`<div class="cards"><div class="card"><div class="label">Drivers</div><div class="big">${s.drivers||0}</div></div><div class="card"><div class="label">Races</div><div class="big">${s.races||0}</div></div><div class="card"><div class="label">Completed</div><div class="big">${s.completed||0}</div></div><div class="card"><div class="label">Open</div><div class="big">${s.open||0}</div></div></div><div class="grid"><div class="panel"><h2>Driver standings</h2><div class="body">${(data.drivers||[]).slice(0,8).map((d,i)=>`<div class="row"><b>#${i+1}</b><div><b>${esc(d.name)}</b><div class="muted">${esc(d.rank)}</div></div><span class="pill">${d.rating} SR</span><b>${d.points} pts</b></div>`).join('')||'<div class="muted">No drivers registered yet.</div>'}</div></div><div class="panel"><h2>Access</h2><div class="body"><div class="notice">Signed in as <b>${esc(me.username)}</b><br><span class="muted">${me.role==='admin'?'Full administration access':'Race hoster access'}</span></div></div></div></div>`}
function renderRaces(){races.innerHTML=`<div class="panel"><h2>Race operations</h2><div class="body"><div class="form"><div class="field"><label>Race name</label><input id="rn" placeholder="CRC Daily #1"></div><div class="field"><label>Track</label><input id="rt" placeholder="Nürburgring Nordschleife"></div><div class="field"><label>Date</label><input id="rd" type="datetime-local"></div><div class="field"><label>Laps</label><input id="rl" type="number" min="1" value="5"></div></div><div class="actions"><button class="btn" onclick="action('create_race',{name:rn.value,track:rt.value,date:rd.value,laps:rl.value})">Create race</button></div><div id="racemsg"></div><div style="margin-top:22px">${(data.races||[]).slice().reverse().map(r=>`<div class="row"><b>${esc(r.id)}</b><div><b>${esc(r.name)}</b><div class="muted">${esc(r.track)} · ${esc(r.date)}</div></div><span class="pill">${esc(r.status)}</span><span>${r.laps} laps</span></div>`).join('')||'<div class="muted">No races yet.</div>'}</div></div></div>`}
function renderDrivers(){drivers.innerHTML=`<div class="panel"><h2>Driver registry</h2><div class="body">${(data.drivers||[]).map((d,i)=>`<div class="row"><b>#${i+1}</b><div><b>${esc(d.name)}</b><div class="muted">${esc(d.rank)} · ${d.starts} starts</div></div><span class="pill">${d.rating} SR</span><b>${d.points} pts</b></div>`).join('')||'<div class="muted">No drivers registered yet.</div>'}</div></div>`}
function renderStaff(){staff.innerHTML=`<div class="panel"><h2>Staff accounts</h2><div class="body"><div class="form"><div class="field"><label>Username</label><input id="su"></div><div class="field"><label>Temporary password</label><input id="sp" type="password"></div></div><div class="actions"><button class="btn" onclick="createHoster()">Create Race Hoster</button></div><div id="staffmsg"></div>${data.users.map(u=>`<div class="staff"><div><b>${esc(u.username)}</b><div class="muted">${u.active===false?'Disabled':'Active'}</div></div><span class="badge">${u.role==='admin'?'ADMIN':'RACE HOSTER'}</span>${u.role==='admin'?'<span></span>':`<button class="btn dark" onclick="resetHoster('${encodeURIComponent(u.username)}')">Reset password</button>`}</div>`).join('')}</div></div>`}
function renderAudit(){audit.innerHTML=`<div class="panel"><h2>Recent audit activity</h2><div class="body">${(data.audit||[]).map(x=>`<div class="row"><b>${x.success?'OK':'ERR'}</b><div><b>${esc(x.action)}</b><div class="muted">${esc(x.actor)} · ${esc(x.detail)}</div></div><span></span><span></span></div>`).join('')||'<div class="muted">No audit entries yet.</div>'}</div></div>`}
async function action(a,p){try{let d=await api('/api/action',{method:'POST',body:JSON.stringify({action:a,...p})});racemsg.innerHTML='<div class="notice">'+esc(d.message)+'</div>';data=await api('/api/data');renderOverview();renderRaces();renderDrivers()}catch(e){racemsg.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
async function createHoster(){try{let d=await api('/api/staff/create',{method:'POST',body:JSON.stringify({username:su.value,password:sp.value})});staffmsg.innerHTML='<div class="notice">'+esc(d.message)+'</div>';data=await api('/api/data');renderStaff()}catch(e){staffmsg.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
async function resetHoster(name){let password=prompt('Enter the new password for this Race Hoster:');if(!password)return;try{let d=await api('/api/staff/reset',{method:'POST',body:JSON.stringify({username:decodeURIComponent(name),password})});alert(d.message)}catch(e){alert(e.message)}}
async function logout(){try{await api('/api/logout',{method:'POST'})}catch(e){}token='';sessionStorage.removeItem('crc_token');renderAuth('login')}
async function boot(){try{let s=await api('/api/status');if(s.setup_required){renderAuth('signup');return}let m=await api('/api/me');me=m;data=await api('/api/data');renderApp()}catch(e){renderAuth('login')}}
boot();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "CRC-Control/1.0"

    def send_json(self, status: int, data: dict):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self):
        raw = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send_html()
        if path == "/api/status":
            return self.send_json(200, {"setup_required": not has_admin()})
        if path == "/api/me":
            _, session = session_from(self)
            if not session:
                return self.send_json(401, {"error": "Session expired"})
            return self.send_json(200, session)
        if path == "/api/data":
            _, session = session_from(self)
            if not session:
                return self.send_json(401, {"error": "Authentication required"})
            data = read_data()
            if session.get("role") == "admin":
                data["users"] = [{k: v for k, v in u.items() if k != "password_hash"} for u in load_staff()["users"]]
                try:
                    with open(_path("audit_log.json"), "r", encoding="utf-8") as f:
                        data["audit"] = json.load(f).get("entries", [])[:100]
                except Exception:
                    data["audit"] = []
            return self.send_json(200, data)
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        p = body(self)
        if path == "/api/login":
            username = str(p.get("username", "")).strip()
            password = str(p.get("password", ""))
            user = find_user(username)
            if not user or not user.get("active", True) or not verify_password(password, str(user.get("password_hash", ""))):
                audit(username or "unknown", "login_failed", "Invalid credentials", False)
                return self.send_json(401, {"error": "Invalid username or password"})
            token = new_session(user)
            audit(username, "login", "Dashboard sign-in")
            return self.send_json(200, {"token": token})
        if path == "/api/signup":
            username = str(p.get("username", "")).strip()
            password = str(p.get("password", ""))
            admin_key = str(p.get("admin_key", ""))
            if len(username) < 3 or len(username) > 32 or not username.replace("_", "").replace("-", "").isalnum():
                return self.send_json(400, {"error": "Username must be 3–32 characters and use letters, numbers, _ or -."})
            if len(password) < 8:
                return self.send_json(400, {"error": "Password must be at least 8 characters."})
            if find_user(username):
                return self.send_json(409, {"error": "That username is already in use."})
            configured_key = os.getenv("DASHBOARD_ADMIN_SECRET", "")
            if admin_key and (not configured_key or not hmac.compare_digest(admin_key, configured_key)):
                return self.send_json(403, {"error": "Invalid admin access key."})
            if has_admin() and admin_key and configured_key and not hmac.compare_digest(admin_key, configured_key):
                return self.send_json(403, {"error": "Invalid admin access key."})
            role = "admin" if admin_key and configured_key and hmac.compare_digest(admin_key, configured_key) else "hoster"
            if role == "admin" and has_admin():
                return self.send_json(403, {"error": "An admin account already exists. Use the admin account to create additional staff."})
            user = {"username": username, "role": role, "active": True, "created_at": time.time(), "password_hash": hash_password(password)}
            staff_data = load_staff()
            staff_data["users"].append(user)
            save_staff(staff_data)
            audit(username, "account_created", f"Created {role} account")
            token = new_session(user)
            return self.send_json(200, {"token": token, "role": role})
        if path == "/api/logout":
            token, session = session_from(self)
            if token:
                SESSIONS.pop(token, None)
                audit(session["username"], "logout", "Dashboard sign-out")
            return self.send_json(200, {"ok": True})
        token, session = session_from(self)
        if not session:
            return self.send_json(401, {"error": "Authentication required"})
        if path == "/api/action":
            try:
                action = str(p.pop("action", ""))
                message = do_action(action, p, session["username"])
                audit(session["username"], action, message)
                return self.send_json(200, {"message": message})
            except Exception as exc:
                audit(session["username"], str(p.get("action", "action")), str(exc), False)
                return self.send_json(400, {"error": str(exc)})
        if path == "/api/staff/create":
            if session.get("role") != "admin":
                return self.send_json(403, {"error": "Admin access required"})
            username = str(p.get("username", "")).strip()
            password = str(p.get("password", ""))
            if len(username) < 3 or len(password) < 8:
                return self.send_json(400, {"error": "Use a username of at least 3 characters and a password of at least 8 characters."})
            if find_user(username):
                return self.send_json(409, {"error": "That username is already in use."})
            user = {"username": username, "role": "hoster", "active": True, "created_at": time.time(), "password_hash": hash_password(password)}
            d = load_staff(); d["users"].append(user); save_staff(d)
            audit(session["username"], "staff_created", f"Created Race Hoster {username}")
            return self.send_json(200, {"message": f"Race Hoster {username} created."})
        if path == "/api/staff/reset":
            if session.get("role") != "admin":
                return self.send_json(403, {"error": "Admin access required"})
            username = str(p.get("username", "")).strip()
            password = str(p.get("password", ""))
            if len(password) < 8:
                return self.send_json(400, {"error": "Password must be at least 8 characters."})
            d = load_staff(); user = next((u for u in d["users"] if u.get("username", "").lower() == username.lower()), None)
            if not user or user.get("role") == "admin":
                return self.send_json(404, {"error": "Race Hoster account not found."})
            user["password_hash"] = hash_password(password); save_staff(d)
            audit(session["username"], "staff_password_reset", f"Reset password for {username}")
            return self.send_json(200, {"message": f"Password reset for {username}."})
        return self.send_json(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        print(f"[CRC Dashboard] {fmt % args}")


def start_dashboard(port: int = DEFAULT_PORT):
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"CRC Control Center running on port {port}")
    return server
