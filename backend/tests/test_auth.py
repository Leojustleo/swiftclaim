import time
import os
import pytest

os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "testsecret")

from app.auth import create_token, verify_token, check_password, TokenError


def test_create_and_verify_token():
    token = create_token()
    payload = verify_token(token)
    assert payload["sub"] == "admin"


def test_expired_token_raises():
    token = create_token(ttl=-1)  # already expired
    with pytest.raises(TokenError):
        verify_token(token)


def test_tampered_token_raises():
    token = create_token()
    parts = token.split(".")
    parts[1] = parts[1][:-2] + "XX"
    with pytest.raises(TokenError):
        verify_token(".".join(parts))


def test_check_password_correct():
    assert check_password("testpass") is True


def test_check_password_wrong():
    assert check_password("wrongpass") is False
