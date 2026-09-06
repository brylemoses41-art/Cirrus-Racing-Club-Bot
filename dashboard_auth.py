from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "dashboard_users.json"
AUDIT_FILE = DATA_DIR / "dashboard_audit.jsonl"
PASSWORD_ITERATIONS = 310_000
SESSIONS: dict[str, dict] = {}
LOCK = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_users() -> dict:
    if not USERS_FILE.exists():
        return {"users": {}}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"users": {}}


def _write_users(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(USERS_FILE)


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    try:
        _, candidate = _hash_password(password, bytes.fromhex(salt_hex))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest_hex)


def ensure_admin() -> None:
    username = os.getenv("DASHBOARD_ADMIN_USERNAME", "admin").strip().lower()
    password = os.getenv("DASHBOARD_ADMIN_PASSWORD", "").strip()
    if not password:
        return
    with LOCK:
        data = _read_users()
        users = data.setdefault("users", {})
        if username in users:
            return
        salt, digest = _hash_password(password)
        users[username] = {
            "username": username,
            "role": "admin",
            "salt": salt,
            "password_hash": digest,
            "created_at": _now(),
            "active": True,
        }
        _write_users(data)


def authenticate(username: str, password: str) -> dict | None:
    ensure_admin()
    username = str(username).strip().lower()
    with LOCK:
        user = _read_users().get("users", {}).get(username)
        if not user or not user.get("active", True):
            return None
        if not verify_password(password, user.get("salt", ""), user.get("password_hash", "")):
            return None
        session = secrets.token_urlsafe(32)
        SESSIONS[session] = {"username": username, "role": user.get("role", "hoster"), "created_at": _now()}
        return {"session": session, "username": username, "role": user.get("role", "hoster")}


def session_user(session: str | None) -> dict | None:
    if not session:
        return None
    return SESSIONS.get(session)


def logout(session: str | None) -> None:
    if session:
        SESSIONS.pop(session, None)


def create_user(username: str, password: str, role: str = "hoster") -> None:
    username = str(username).strip().lower()
    role = "admin" if role == "admin" else "hoster"
    if len(username) < 3 or len(password) < 8:
        raise ValueError("Username must be at least 3 characters and password at least 8 characters")
    with LOCK:
        data = _read_users()
        users = data.setdefault("users", {})
        if username in users:
            raise ValueError("Username already exists")
        salt, digest = _hash_password(password)
        users[username] = {
            "username": username,
            "role": role,
            "salt": salt,
            "password_hash": digest,
            "created_at": _now(),
            "active": True,
        }
        _write_users(data)


def set_user_active(username: str, active: bool) -> None:
    username = str(username).strip().lower()
    with LOCK:
        data = _read_users()
        user = data.setdefault("users", {}).get(username)
        if not user:
            raise ValueError("User not found")
        user["active"] = bool(active)
        _write_users(data)


def list_users() -> list[dict]:
    ensure_admin()
    with LOCK:
        users = _read_users().get("users", {})
        return [
            {
                "username": u.get("username", name),
                "role": u.get("role", "hoster"),
                "active": bool(u.get("active", True)),
                "created_at": u.get("created_at"),
            }
            for name, u in sorted(users.items())
        ]


def audit(username: str, action: str, details: dict | None = None, ip: str = "") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now(),
        "username": username,
        "action": action,
        "details": details or {},
        "ip": ip,
    }
    with LOCK:
        with AUDIT_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recent_audit(limit: int = 100) -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)):]
        return [json.loads(line) for line in reversed(lines) if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
