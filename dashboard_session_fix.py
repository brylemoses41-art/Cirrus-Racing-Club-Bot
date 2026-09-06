from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from threading import Event, Thread

import dashboard_v2

SESSION_FILE = Path(__file__).resolve().parent / "data" / "dashboard_sessions.json"
SAVE_INTERVAL = 2
_SIGNUP_PATCHED = False


def _load_sessions() -> None:
    try:
        if not SESSION_FILE.exists():
            return
        raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        current = time.time()
        for token, session in raw.items():
            if isinstance(session, dict) and float(session.get("expires", 0)) > current:
                dashboard_v2.SESSIONS[str(token)] = session
    except Exception as exc:
        print(f"Dashboard session restore skipped: {exc}")


def _save_sessions() -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = time.time()
    active = {
        token: session
        for token, session in list(dashboard_v2.SESSIONS.items())
        if isinstance(session, dict) and float(session.get("expires", 0)) > current
    }
    temp = SESSION_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(active, indent=2), encoding="utf-8")
    temp.replace(SESSION_FILE)


def _send_json(handler, status: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _signup(handler, payload: dict) -> None:
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    confirm = str(payload.get("confirm_password", ""))
    admin_key = str(payload.get("admin_key", ""))

    if not 3 <= len(username) <= 32:
        _send_json(handler, 400, {"error": "Username must be 3–32 characters"})
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        _send_json(handler, 400, {"error": "Username may only use letters, numbers, _ and -"})
        return
    if len(password) < 12:
        _send_json(handler, 400, {"error": "Password must be at least 12 characters"})
        return
    if password != confirm:
        _send_json(handler, 400, {"error": "Passwords do not match"})
        return
    if dashboard_v2.find_user(username):
        _send_json(handler, 409, {"error": "That username already exists"})
        return

    # The real admin key is read only on the server. It is never sent to the UI
    # and never written into staff.json.
    configured_key = (
        os.getenv("DASHBOARD_ADMIN_SECRET", "").strip()
        or os.getenv("DASHBOARD_SETUP_KEY", "").strip()
    )
    if admin_key:
        if not configured_key or not hmac.compare_digest(admin_key, configured_key):
            _send_json(handler, 403, {"error": "Invalid admin access key"})
            return
        role = "admin"
    else:
        role = "race_hoster"

    # Do not allow an accidental public signup to become the first admin.
    if not dashboard_v2.has_admin() and role != "admin":
        _send_json(handler, 403, {"error": "The first account must be created with the admin access key"})
        return

    data = dashboard_v2.staff()
    data.setdefault("users", [])
    data["users"].append(
        {
            "username": username,
            "role": role,
            "active": True,
            "password_hash": dashboard_v2.password_hash(password),
            "created_at": dashboard_v2.now(),
            "created_by": "self_signup",
        }
    )
    dashboard_v2.save_json("staff.json", data)
    dashboard_v2.audit(username, "ACCOUNT_CREATED", f"Created {role} account")
    _send_json(handler, 201, {"ok": True, "username": username, "role": role})


def _install_signup_endpoint() -> None:
    global _SIGNUP_PATCHED
    if _SIGNUP_PATCHED:
        return

    original_do_post = dashboard_v2.DashboardHandler.do_POST

    def patched_do_post(self):
        from urllib.parse import urlparse

        if urlparse(self.path).path != "/api/signup":
            return original_do_post(self)
        try:
            payload = self.body()
            _signup(self, payload)
        except ValueError as exc:
            _send_json(self, 400, {"error": str(exc)})
        except Exception as exc:
            _send_json(self, 500, {"error": str(exc)})

    dashboard_v2.DashboardHandler.do_POST = patched_do_post
    _SIGNUP_PATCHED = True


def _account_overlay() -> str:
    return r'''
<script>
(function(){
  function addAccountButton(){
    const box=document.querySelector('.loginbox');
    if(!box || document.getElementById('crc-signup-btn')) return;
    const wrap=document.createElement('div');
    wrap.style='margin-top:12px';
    wrap.innerHTML='<button type="button" class="btn dark" id="crc-signup-btn" style="width:100%">Create Account</button>';
    box.appendChild(wrap);
    document.getElementById('crc-signup-btn').onclick=showSignup;
  }
  function showSignup(){
    const box=document.querySelector('.loginbox');
    if(!box) return;
    box.innerHTML=`
      <div class="ey">CIRRUS RACING CLUB</div>
      <h1>Create account</h1>
      <p>Set up your Control Center access.</p>
      <form id="crc-signup-form">
        <div class="field"><label>Username</label><input id="crc-su-user" autocomplete="username" required></div>
        <div class="field"><label>Password</label><input id="crc-su-pass" type="password" autocomplete="new-password" minlength="12" required></div>
        <div class="field"><label>Confirm password</label><input id="crc-su-confirm" type="password" autocomplete="new-password" minlength="12" required></div>
        <div class="field"><label>Admin access key <span class="muted">optional</span></label><input id="crc-su-key" type="password" autocomplete="off"><div class="hint">Leave this empty for a Race Hoster account. Enter the private admin access key for Admin access.</div></div>
        <div class="actions"><button class="btn" type="submit">Create Account</button><button class="btn dark" type="button" id="crc-back-login">Back to sign in</button></div>
        <div class="err" id="crc-su-error"></div>
      </form>`;
    document.getElementById('crc-back-login').onclick=()=>location.reload();
    document.getElementById('crc-signup-form').onsubmit=async function(e){
      e.preventDefault();
      const err=document.getElementById('crc-su-error'); err.textContent='';
      const username=document.getElementById('crc-su-user').value.trim();
      const password=document.getElementById('crc-su-pass').value;
      const confirm=document.getElementById('crc-su-confirm').value;
      const key=document.getElementById('crc-su-key').value;
      try{
        const r=await fetch('/api/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,confirm_password:confirm,admin_key:key})});
        const d=await r.json();
        if(!r.ok) throw Error(d.error||'Account creation failed');
        alert('Account created successfully. Role: '+d.role.replace('_',' '));
        location.reload();
      }catch(x){err.textContent=x.message||'Account creation failed';}
    };
  }
  const observer=new MutationObserver(addAccountButton);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  addAccountButton();
  setTimeout(addAccountButton,250);
  setTimeout(addAccountButton,1000);
})();
</script>'''


def install() -> None:
    _load_sessions()
    _install_signup_endpoint()

    original_send_header = dashboard_v2.DashboardHandler.send_header

    def send_header(self, keyword, value):
        if keyword.lower() == "set-cookie" and value.startswith("crc_session="):
            value = value.replace("SameSite=Strict", "SameSite=Lax")
        return original_send_header(self, keyword, value)

    dashboard_v2.DashboardHandler.send_header = send_header

    marker = "</body>"
    if marker in dashboard_v2.HTML:
        dashboard_v2.HTML = dashboard_v2.HTML.replace(marker, _account_overlay() + marker, 1)

    stop = Event()

    def saver() -> None:
        while not stop.wait(SAVE_INTERVAL):
            try:
                _save_sessions()
            except Exception as exc:
                print(f"Dashboard session save skipped: {exc}")

    Thread(target=saver, name="crc-dashboard-session-store", daemon=True).start()

    original_start = dashboard_v2.start_dashboard

    def start_dashboard(port=dashboard_v2.DEFAULT_PORT):
        server = original_start(port)
        try:
            _save_sessions()
        except Exception:
            pass
        return server

    dashboard_v2.start_dashboard = start_dashboard
