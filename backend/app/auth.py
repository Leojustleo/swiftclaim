from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


class TokenError(Exception):
    pass


def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        from pathlib import Path
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
    return val


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(header_b64: str, body_b64: str) -> str:
    secret = _env("SECRET_KEY").encode()
    msg = f"{header_b64}.{body_b64}".encode()
    return _b64(hmac.new(secret, msg, hashlib.sha256).digest())


def create_token(ttl: int = 8 * 3600) -> str:
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = {"sub": "admin", "exp": int(time.time()) + ttl}
    body = _b64(json.dumps(payload).encode())
    sig = _sign(header, body)
    return f"{header}.{body}.{sig}"


def verify_token(token: str) -> dict[str, Any]:
    try:
        header, body, sig = token.split(".")
    except ValueError:
        raise TokenError("Malformed token")
    expected = _sign(header, body)
    if not hmac.compare_digest(sig, expected):
        raise TokenError("Invalid signature")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=="))
    except Exception:
        raise TokenError("Cannot decode payload")
    if payload.get("exp", 0) < time.time():
        raise TokenError("Token expired")
    return payload


def check_password(password: str) -> bool:
    expected = _env("ADMIN_PASSWORD")
    if not expected:
        return False
    return hmac.compare_digest(password, expected)


def require_admin_token(
    creds: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> dict[str, Any]:
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        return verify_token(creds.credentials)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
