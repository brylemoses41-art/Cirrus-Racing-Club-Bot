from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event, Thread

import dashboard_v2

SESSION_FILE = Path(__file__).resolve().parent / "data" / "dashboard_sessions.json"
SAVE_INTERVAL = 2


def _load_sessions() -> None:
    try:
        if not SESSION_FILE.exists():
            return
        raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        now = time.time()
        for token, session in raw.items():
            if isinstance(session, dict) and float(session.get("expires", 0)) > now:
                dashboard_v2.SESSIONS[str(token)] = session
    except Exception as exc:
        print(f"Dashboard session restore skipped: {exc}")


def _save_sessions() -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    active = {
        token: session
        for token, session in list(dashboard_v2.SESSIONS.items())
        if isinstance(session, dict) and float(session.get("expires", 0)) > now
    }
    temp = SESSION_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(active, indent=2), encoding="utf-8")
    temp.replace(SESSION_FILE)


def _account_overlay() -> str:
    # The existing dashboard contains the login screen, but older deployments
    # can still have a cached page without the account-creation controls. This
    # overlay adds a clearly visible Create Account action without exposing
    # any server-side admin secret to the browser.
    return r'''
<script>
(function(){
  function addAccountButton(){
    const box=document.querySelector('.loginbox');
    if(!box || document.getElementById('crc-create-account')) return;
    const actions=document.createElement('div');
    actions.id='crc-create-account';
    actions.style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap';
    actions.innerHTML='<button type="button" class="btn dark" id="crc-signup-btn">Create Account</button>';
    box.appendChild(actions);
    document.getElementById('crc-signup-btn').onclick=showSignup;
  }
  function showSignup(){
    const box=document.querySelector('.loginbox');
    if(!box) return;
    box.innerHTML=`
      <div class="ey">CIRRUS RACING CLUB</div>
      <h1>Create account</h1>
      <p>Set up your Control Center account.</p>
      <form id="crc-signup-form">
        <div class="field"><label>Username</label><input id="crc-su-user" autocomplete="username" required></div>
        <div class="field"><label>Password</label><input id="crc-su-pass" type="password" autocomplete="new-password" required></div>
        <div class="field"><label>Confirm password</label><input id="crc-su-confirm" type="password" autocomplete="new-password" required></div>
        <div class="field"><label>Admin access key <span style="opacity:.55">optional</span></label><input id="crc-su-key" type="password" autocomplete="off"><div class="hint">Leave this empty for a Race Hoster account. Only the private server key can create an Admin account.</div></div>
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
      if(password!==confirm){err.textContent='Passwords do not match.';return;}
      try{
        const r=await fetch('/api/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,confirm_password:confirm,admin_key:key})});
        const d=await r.json();
        if(!r.ok) throw Error(d.error||'Account creation failed');
        alert('Account created. You can now sign in as '+d.role+'.');
        location.reload();
      }catch(x){err.textContent=x.message||'Account creation failed';}
    };
  }
  const observer=new MutationObserver(addAccountButton);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(addAccountButton,100);
  setTimeout(addAccountButton,500);
})();
</script>'''


def install() -> None:
    _load_sessions()

    original_send_header = dashboard_v2.DashboardHandler.send_header

    def send_header(self, keyword, value):
        if keyword.lower() == "set-cookie" and value.startswith("crc_session="):
            value = value.replace("SameSite=Strict", "SameSite=Lax")
        return original_send_header(self, keyword, value)

    dashboard_v2.DashboardHandler.send_header = send_header

    # Add the account button to the already-built dashboard HTML. This is
    # intentionally UI-only; the backend endpoint is supplied by the dashboard
    # auth implementation and the admin key never appears in this source.
    marker = "</body>"
    if marker in dashboard_v2.HTML and "id=\"crc-signup-btn\"" not in dashboard_v2.HTML:
        dashboard_v2.HTML = dashboard_v2.HTML.replace(marker, _account_overlay() + marker, 1)

    stop = Event()

    def saver() -> None:
        while not stop.wait(SAVE_INTERVAL):
            try:
                _save_sessions()
            except Exception as exc:
                print(f"Dashboard session save skipped: {exc}")

    Thread(target=saver, name="crc-dashboard-session-store", daemon=True).start()

    # Keep the module-level dashboard start function in sync for callers that
    # import it after this installer has run.
    original_start = dashboard_v2.start_dashboard

    def start_dashboard(port=dashboard_v2.DEFAULT_PORT):
        server = original_start(port)
        try:
            _save_sessions()
        except Exception:
            pass
        return server

    dashboard_v2.start_dashboard = start_dashboard
