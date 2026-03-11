"""Tests for core/auth.py — JWT helpers, AuthUser."""
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.auth import AuthUser, issue_session_token, decode_jwt
from fastapi import HTTPException


SECRET = "test-secret-key-for-jwt"
ALGORITHM = "HS256"


class TestAuthUser:
    def test_defaults(self):
        user = AuthUser()
        assert user.tenant_id == "default"
        assert user.user_id == "U001"
        assert user.roles == []

    def test_custom_values(self):
        user = AuthUser(tenant_id="T1", user_id="U2", roles=["admin"])
        assert user.tenant_id == "T1"
        assert user.roles == ["admin"]


class TestIssueSessionToken:
    def test_issue_and_decode(self):
        token = issue_session_token(
            user_id="U1",
            tenant_id="T1",
            roles=["admin"],
            secret=SECRET,
            algorithm=ALGORITHM,
        )
        assert isinstance(token, str)

        payload = decode_jwt(token, SECRET, ALGORITHM)
        assert payload["sub"] == "U1"
        assert payload["tenant_id"] == "T1"
        assert payload["roles"] == ["admin"]
        assert "iat" in payload
        assert "exp" in payload

    def test_custom_expiry(self):
        token = issue_session_token(
            user_id="U1", tenant_id="T1", roles=[],
            secret=SECRET, expires_in=3600,
        )
        payload = decode_jwt(token, SECRET, ALGORITHM)
        assert payload["exp"] - payload["iat"] == 3600


class TestDecodeJwt:
    def test_expired_token(self):
        token = issue_session_token(
            user_id="U1", tenant_id="T1", roles=[],
            secret=SECRET, expires_in=-10,  # Already expired
        )
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token, SECRET, ALGORITHM)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_invalid_token(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt("not.a.jwt", SECRET, ALGORITHM)
        assert exc_info.value.status_code == 401
        assert "Invalid token" in exc_info.value.detail

    def test_wrong_secret(self):
        token = issue_session_token(
            user_id="U1", tenant_id="T1", roles=[],
            secret=SECRET,
        )
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token, "wrong-secret", ALGORITHM)
        assert exc_info.value.status_code == 401
