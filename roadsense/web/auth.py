"""Sign-in, sessions and roles for the web app.

    admin     everything, including users and city-data sync
    reviewer  approve / reject / correct / resend reports, run follow-up, upload trips
    driver    upload trips and see results
    viewer    read only

Two ways in: email + password (scrypt hashes), or single sign-on with any OpenID Connect provider (Microsoft
Entra ID for municipal staff: set ROADSENSE_OIDC_ISSUER / _CLIENT_ID / _CLIENT_SECRET). An Entra app role named like
one of the roles above sets the user's role at each sign-in; otherwise new SSO users get ROADSENSE_OIDC_DEFAULT_ROLE.

Sessions are HMAC-signed cookies (HttpOnly, SameSite=Strict, Secure behind HTTPS). Every state-changing request
must also carry the session's CSRF token in X-CSRF-Token.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from functools import lru_cache
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..common.config import settings
from ..common.db import audit, now, row, session

log = logging.getLogger("roadsense.auth")
ROLES = ("admin", "reviewer", "driver", "viewer")
COOKIE, STATE_COOKIE = "rs_session", "rs_oidc"
PERMS = {
    "read": ROLES,
    "upload": ("admin", "reviewer", "driver"),
    "review": ("admin", "reviewer"),
    "admin": ("admin",),
}
router = APIRouter()


# ---------------- secrets and hashing ----------------
@lru_cache(maxsize=1)
def secret() -> bytes:
    if settings.session_secret:
        return settings.session_secret.encode()
    path = settings.data_dir / ".session_secret"  # generated once per installation, never committed
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip().encode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    try:
        _, salt, digest = (stored or "").split("$")
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(test.hex(), digest)
    except ValueError:
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 12:
        return "password must be at least 12 characters"
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "password needs upper and lower case letters and a digit"
    return None


def _sign(data: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _unsign(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(hmac.new(secret(), raw.encode(), hashlib.sha256).hexdigest(), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        return None
    return data if data.get("exp", 0) > time.time() else None


# ---------------- users ----------------
def bootstrap_admin() -> str | None:
    """Create the first admin when there are no users. Returns where the generated password was written."""
    with session() as conn:
        if conn.execute("SELECT 1 FROM users").fetchone():
            return None
        password = settings.admin_password
        note = None
        if not password:
            password = secrets.token_urlsafe(14) + "A1"
            path = settings.data_dir / "initial_admin_password.txt"
            path.write_text(f"{settings.admin_email}\n{password}\n", encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            note = str(path)
        conn.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, 'admin', ?, ?)",
                     (settings.admin_email.lower(), "Administrator", hash_password(password), now()))
        audit(conn, "system", "user_created", f"user:{settings.admin_email.lower()}", {"role": "admin",
                                                                                      "bootstrap": True})
    if note:
        log.warning("Created the first admin %s; its password is in %s (change it after signing in)",
                    settings.admin_email, note)
    return note


def public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "role", "active", "created_at", "last_login")} | {
        "sso": bool(u.get("oidc_subject"))}


LOCAL_USER = {"id": 0, "email": "local", "name": "Local (sign-in disabled)", "role": "admin", "active": 1,
              "created_at": None, "last_login": None, "oidc_subject": None}


def current_user(request: Request) -> dict | None:
    if not settings.auth_enabled:
        return {**LOCAL_USER, "csrf": "local"}
    data = _unsign(request.cookies.get(COOKIE))
    if not data:
        return None
    with session() as conn:
        u = row(conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (data["uid"],)).fetchone())
    if u is None:
        return None
    return {**u, "csrf": data["csrf"]}


def allowed(user: dict, perm: str) -> bool:
    return user["role"] in PERMS[perm]


def _start_session(response, user: dict, csrf: str | None = None) -> str:
    csrf = csrf or secrets.token_urlsafe(18)
    value = _sign({"uid": user["id"], "csrf": csrf, "exp": int(time.time() + settings.session_hours * 3600)})
    response.set_cookie(COOKIE, value, httponly=True, samesite="strict", secure=settings.cookie_secure,
                        max_age=int(settings.session_hours * 3600), path="/")
    with session() as conn:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now(), user["id"]))
        audit(conn, f"user:{user['email']}", "signed_in", f"user:{user['email']}", None)
    return csrf


_attempts: dict[str, deque] = defaultdict(deque)


def _throttle(key: str, limit: int = 10, window: int = 300) -> None:
    q, t = _attempts[key], time.monotonic()
    while q and t - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "too many sign-in attempts; wait a few minutes", headers={"Retry-After": "120"})
    q.append(t)


# ---------------- routes ----------------
@router.get("/api/me")
def me(request: Request):
    u = current_user(request)
    sso = bool(settings.oidc_issuer and settings.oidc_client_id)
    if u is None:
        return {"authenticated": False, "auth_enabled": settings.auth_enabled, "sso": sso}
    return {"authenticated": True, "auth_enabled": settings.auth_enabled, "sso": sso, "user": public_user(u),
            "csrf": u["csrf"], "permissions": [p for p in PERMS if allowed(u, p)]}


@router.post("/api/auth/login")
def login(request: Request, body: dict = Body(...)):
    email, password = str(body.get("email") or "").strip().lower(), str(body.get("password") or "")
    _throttle(request.client.host if request.client else "?")
    _throttle(f"user:{email}", limit=8)
    with session() as conn:
        u = row(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())
    if not u or not u["active"] or not check_password(password, u["password_hash"]):
        with session() as conn:
            audit(conn, "anonymous", "sign_in_failed", f"user:{email[:80]}", None)
        raise HTTPException(401, "wrong email or password")
    csrf = secrets.token_urlsafe(18)
    response = JSONResponse({"ok": True, "csrf": csrf, "user": public_user(u)})
    _start_session(response, u, csrf)
    return response


@router.post("/api/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response


# ---------------- OpenID Connect (Entra ID and others) ----------------
@lru_cache(maxsize=1)
def _oidc_config() -> dict:
    r = httpx.get(settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    return r.json()


@router.get("/auth/oidc/login")
def oidc_login():
    if not (settings.oidc_issuer and settings.oidc_client_id):
        raise HTTPException(404, "single sign-on is not configured")
    state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    url = _oidc_config()["authorization_endpoint"] + "?" + urlencode({
        "client_id": settings.oidc_client_id, "response_type": "code", "scope": "openid email profile",
        "redirect_uri": settings.oidc_redirect_url, "state": state, "nonce": nonce})
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(STATE_COOKIE, _sign({"state": state, "nonce": nonce, "exp": int(time.time() + 600)}),
                        httponly=True, samesite="lax", secure=settings.cookie_secure, max_age=600, path="/auth")
    return response


@router.get("/auth/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = ""):
    import jwt

    saved = _unsign(request.cookies.get(STATE_COOKIE))
    if not saved or not secrets.compare_digest(saved["state"], state) or not code:
        raise HTTPException(400, "sign-in expired; try again")
    cfg = _oidc_config()
    r = httpx.post(cfg["token_endpoint"], timeout=15, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": settings.oidc_redirect_url,
        "client_id": settings.oidc_client_id, "client_secret": settings.oidc_client_secret})
    if r.status_code >= 400:
        raise HTTPException(401, "the identity provider refused the sign-in")
    id_token = r.json().get("id_token", "")
    key = jwt.PyJWKClient(cfg["jwks_uri"]).get_signing_key_from_jwt(id_token).key
    try:
        claims = jwt.decode(id_token, key, algorithms=["RS256", "ES256"], audience=settings.oidc_client_id,
                            issuer=cfg.get("issuer", settings.oidc_issuer))
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid identity token: {e}") from e
    if claims.get("nonce") != saved["nonce"]:
        raise HTTPException(401, "invalid identity token nonce")
    email = str(claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").lower()
    if not email:
        raise HTTPException(401, "the identity provider did not share an email address")
    role_claim = [r for r in claims.get("roles", []) if r in ROLES]
    with session() as conn:
        u = row(conn.execute("SELECT * FROM users WHERE oidc_subject = ? OR email = ?",
                             (claims["sub"], email)).fetchone())
        if u is None:
            role = role_claim[0] if role_claim else settings.oidc_default_role
            conn.execute("INSERT INTO users (email, name, role, oidc_subject, created_at) VALUES (?, ?, ?, ?, ?)",
                         (email, claims.get("name"), role if role in ROLES else "viewer", claims["sub"], now()))
            audit(conn, "sso", "user_created", f"user:{email}", {"role": role})
        else:
            conn.execute("UPDATE users SET oidc_subject = ?, name = COALESCE(name, ?)"
                         + (", role = ?" if role_claim else "") + " WHERE id = ?",
                         (claims["sub"], claims.get("name"), *( [role_claim[0]] if role_claim else []), u["id"]))
        u = row(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())
    if not u["active"]:
        raise HTTPException(403, "this account is disabled")
    response = RedirectResponse("/", status_code=302)
    _start_session(response, u)
    response.delete_cookie(STATE_COOKIE, path="/auth")
    return response


# ---------------- user management (admin) ----------------
def _admin(request: Request) -> dict:
    u = getattr(request.state, "user", None)
    if not u or not allowed(u, "admin"):
        raise HTTPException(403, "admins only")
    return u


@router.get("/api/users")
def list_users(request: Request):
    _admin(request)
    with session() as conn:
        return [public_user(dict(r)) for r in conn.execute("SELECT * FROM users ORDER BY email")]


@router.post("/api/users")
def create_user(request: Request, body: dict = Body(...)):
    admin = _admin(request)
    email, role = str(body.get("email") or "").strip().lower(), str(body.get("role") or "viewer")
    password = str(body.get("password") or "")
    if "@" not in email or len(email) > 120:
        raise HTTPException(422, "a valid email is required")
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if password and (problem := password_problem(password)):
        raise HTTPException(422, problem)
    with session() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "a user with this email exists")
        conn.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                     (email, str(body.get("name") or "")[:80] or None, role,
                      hash_password(password) if password else None, now()))
        audit(conn, f"user:{admin['email']}", "user_created", f"user:{email}", {"role": role})
        return public_user(row(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()))


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, request: Request, body: dict = Body(...)):
    admin = _admin(request)
    with session() as conn:
        u = row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        if u is None:
            raise HTTPException(404, "unknown user")
        changes = {}
        if "role" in body:
            if body["role"] not in ROLES:
                raise HTTPException(422, f"role must be one of {ROLES}")
            changes["role"] = body["role"]
        if "active" in body:
            changes["active"] = int(bool(body["active"]))
        if body.get("password"):
            if problem := password_problem(str(body["password"])):
                raise HTTPException(422, problem)
            changes["password_hash"] = hash_password(str(body["password"]))
        if u["id"] == admin["id"] and (changes.get("role", "admin") != "admin" or changes.get("active", 1) == 0):
            raise HTTPException(409, "you cannot remove your own admin access")
        if changes:
            conn.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                         [*changes.values(), user_id])
            audit(conn, f"user:{admin['email']}", "user_updated", f"user:{u['email']}",
                  {k: v for k, v in changes.items() if k != "password_hash"} | (
                      {"password": "reset"} if "password_hash" in changes else {}))
        return public_user(row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()))


@router.post("/api/me/password")
def change_password(request: Request, body: dict = Body(...)):
    u = getattr(request.state, "user", None)
    if not u or not u.get("id"):
        raise HTTPException(401, "sign in first")
    if u.get("password_hash") and not check_password(str(body.get("current") or ""), u["password_hash"]):
        raise HTTPException(403, "current password is wrong")
    new = str(body.get("new") or "")
    if problem := password_problem(new):
        raise HTTPException(422, problem)
    with session() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), u["id"]))
        audit(conn, f"user:{u['email']}", "password_changed", f"user:{u['email']}", None)
    return {"ok": True}
