"""Tests for the FHIR Backend Services JWT token module."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest

import healthcarecli.config.manager as mgr
from healthcarecli.fhir.token import (
    build_jwt_assertion,
    cache_token,
    exchange_jwt_for_token,
    generate_rsa_keypair,
    keys_dir,
    load_cached_token,
    load_private_key,
    private_key_path,
    save_private_key,
    tokens_dir,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect all config/key/token writes to a temp directory."""
    monkeypatch.setattr(mgr, "config_dir", lambda: tmp_path)


# ── keypair generation ────────────────────────────────────────────────────────


def test_generate_rsa_keypair_returns_pem_and_jwk():
    private_pem, public_jwk_json = generate_rsa_keypair(bits=2048)

    # Private key PEM
    assert "-----BEGIN RSA PRIVATE KEY-----" in private_pem or (
        "-----BEGIN PRIVATE KEY-----" in private_pem
    )

    # Public JWK JSON is valid JSON
    jwk = json.loads(public_jwk_json)
    assert jwk["kty"] == "RSA"
    assert jwk["use"] == "sig"
    assert jwk["alg"] == "RS384"
    assert "n" in jwk
    assert "e" in jwk
    assert "kid" in jwk


def test_generate_rsa_keypair_kid_is_uuid():
    import re

    _, public_jwk_json = generate_rsa_keypair(bits=2048)
    jwk = json.loads(public_jwk_json)
    uuid_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    assert uuid_re.match(jwk["kid"]), f"kid is not a UUID: {jwk['kid']}"


def test_generate_rsa_keypair_unique_each_call():
    _, jwk1_json = generate_rsa_keypair(bits=2048)
    _, jwk2_json = generate_rsa_keypair(bits=2048)
    jwk1 = json.loads(jwk1_json)
    jwk2 = json.loads(jwk2_json)
    # Each call produces a different key (different modulus n)
    assert jwk1["n"] != jwk2["n"]
    # Each call produces a different kid
    assert jwk1["kid"] != jwk2["kid"]


# ── JWT assertion ─────────────────────────────────────────────────────────────


@pytest.fixture()
def rsa_keypair():
    """Return (private_pem, public_jwk_json) for a fresh 2048-bit key."""
    return generate_rsa_keypair(bits=2048)


def test_build_jwt_assertion_is_string(rsa_keypair):
    private_pem, _ = rsa_keypair
    assertion = build_jwt_assertion("client-id-123", "https://token.example.com", private_pem)
    assert isinstance(assertion, str)
    assert assertion.count(".") == 2  # header.payload.signature


def test_build_jwt_assertion_claims(rsa_keypair):
    private_pem, _ = rsa_keypair
    client_id = "my-client-id"
    token_url = "https://token.example.com/oauth2/token"

    assertion = build_jwt_assertion(client_id, token_url, private_pem)

    # Decode WITHOUT verifying signature so we can inspect claims in tests
    decoded = jwt.decode(
        assertion,
        options={"verify_signature": False},
        algorithms=["RS384"],
    )

    assert decoded["iss"] == client_id
    assert decoded["sub"] == client_id
    assert decoded["aud"] == token_url
    assert "jti" in decoded

    now = int(time.time())
    # iat should be close to now
    assert abs(decoded["iat"] - now) < 10
    # exp should be ~4 minutes ahead
    assert 230 <= decoded["exp"] - decoded["iat"] <= 250


def test_build_jwt_assertion_unique_jti(rsa_keypair):
    private_pem, _ = rsa_keypair
    a1 = build_jwt_assertion("cid", "https://tok.example.com", private_pem)
    a2 = build_jwt_assertion("cid", "https://tok.example.com", private_pem)
    d1 = jwt.decode(a1, options={"verify_signature": False}, algorithms=["RS384"])
    d2 = jwt.decode(a2, options={"verify_signature": False}, algorithms=["RS384"])
    assert d1["jti"] != d2["jti"]


def test_build_jwt_assertion_uses_rs384(rsa_keypair):
    private_pem, _ = rsa_keypair
    assertion = build_jwt_assertion("cid", "https://tok.example.com", private_pem)
    header = jwt.get_unverified_header(assertion)
    assert header["alg"] == "RS384"


# ── exchange_jwt_for_token ────────────────────────────────────────────────────


def test_exchange_jwt_for_token_posts_correct_params():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}

    with patch("healthcarecli.fhir.token.requests.post", return_value=mock_resp) as mock_post:
        result = exchange_jwt_for_token(
            "https://token.example.com", "my.jwt.assertion", scope="system/*.read"
        )

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    data = kwargs["data"]
    assert data["grant_type"] == "client_credentials"
    assert data["client_assertion_type"] == (
        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    )
    assert data["client_assertion"] == "my.jwt.assertion"
    assert data["scope"] == "system/*.read"
    assert result["access_token"] == "tok123"


def test_exchange_jwt_for_token_raises_on_http_error():
    import requests as req_lib

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req_lib.HTTPError("401 Unauthorized")

    with patch("healthcarecli.fhir.token.requests.post", return_value=mock_resp):
        with pytest.raises(req_lib.HTTPError):
            exchange_jwt_for_token("https://token.example.com", "bad.jwt")


# ── key file helpers ──────────────────────────────────────────────────────────


def test_save_and_load_private_key(rsa_keypair):
    private_pem, _ = rsa_keypair
    path = save_private_key("test-profile", private_pem)
    assert path.exists()
    loaded = load_private_key("test-profile")
    assert loaded == private_pem


def test_load_private_key_raises_if_missing():
    with pytest.raises(FileNotFoundError, match="test-missing"):
        load_private_key("test-missing")


def test_private_key_path_uses_profile_name():
    path = private_key_path("my-profile")
    assert path.name == "my-profile.pem"


# ── token caching ─────────────────────────────────────────────────────────────


def test_cache_token_and_load_cached_token():
    token_response = {"access_token": "tok_abc", "expires_in": 3600}
    cache_token("epic-sandbox", token_response)

    cached = load_cached_token("epic-sandbox")
    assert cached is not None
    assert cached["access_token"] == "tok_abc"


def test_load_cached_token_returns_none_when_missing():
    result = load_cached_token("nonexistent-profile")
    assert result is None


def test_load_cached_token_returns_none_when_expired():
    token_response = {"access_token": "expired_tok", "expires_in": 30}
    cache_token("expired-profile", token_response)

    # Manually backdate the _expires_at so it's in the past
    cache_path = tokens_dir() / "expired-profile.json"
    cached = json.loads(cache_path.read_text())
    cached["_expires_at"] = int(time.time()) - 10  # already expired
    cache_path.write_text(json.dumps(cached))

    result = load_cached_token("expired-profile")
    assert result is None


def test_load_cached_token_respects_min_remaining():
    token_response = {"access_token": "nearly_expired", "expires_in": 50}
    cache_token("nearly-profile", token_response)

    # Default min_remaining is 60; token only has ~50s left → should return None
    cache_path = tokens_dir() / "nearly-profile.json"
    cached = json.loads(cache_path.read_text())
    cached["_expires_at"] = int(time.time()) + 50
    cache_path.write_text(json.dumps(cached))

    result = load_cached_token("nearly-profile", min_remaining=60)
    assert result is None

    # But with min_remaining=30 it should return the token
    result = load_cached_token("nearly-profile", min_remaining=30)
    assert result is not None
    assert result["access_token"] == "nearly_expired"


def test_cache_token_avoids_network_call_on_second_fetch(rsa_keypair):
    """A cached valid token must be returned without any HTTP POST."""
    private_pem, _ = rsa_keypair
    token_response = {"access_token": "cached_tok", "expires_in": 3600}
    cache_token("cache-test", token_response)

    with patch("healthcarecli.fhir.token.requests.post") as mock_post:
        # Simulate what _fetch_jwt_token does
        cached = load_cached_token("cache-test")
        assert cached is not None
        access_token = cached["access_token"]

    mock_post.assert_not_called()
    assert access_token == "cached_tok"
