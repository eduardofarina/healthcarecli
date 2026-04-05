"""Backend Services JWT token exchange for SMART on FHIR / Epic.

Implements: https://hl7.org/fhir/smart-app-launch/backend-services.html
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from uuid import uuid4

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from healthcarecli.config.manager import config_dir

# ── Key generation ────────────────────────────────────────────────────────────


def generate_rsa_keypair(bits: int = 2048) -> tuple[str, str]:
    """Generate an RSA keypair.

    Returns:
        (private_key_pem, public_key_jwk_json) where private_key_pem is a
        PEM string and public_key_jwk_json is a JSON string of the public JWK.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
    )

    # Serialize private key to PEM
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Build public JWK
    pub = private_key.public_key()
    pub_numbers = pub.public_numbers()

    def _b64url_uint(n: int) -> str:
        byte_length = (n.bit_length() + 7) // 8
        raw = n.to_bytes(byte_length, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    kid = str(uuid4())
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS384",
        "n": _b64url_uint(pub_numbers.n),
        "e": _b64url_uint(pub_numbers.e),
        "kid": kid,
    }
    return private_pem, json.dumps(jwk, indent=2)


# ── JWT assertion ─────────────────────────────────────────────────────────────


def build_jwt_assertion(client_id: str, token_url: str, private_key_pem: str) -> str:
    """Build a signed JWT assertion for the client_credentials flow.

    Args:
        client_id:       OAuth2 client ID (iss and sub claims).
        token_url:       Token endpoint URL (aud claim).
        private_key_pem: RSA private key in PEM format.

    Returns:
        A signed JWT string (RS384).
    """
    now = int(time.time())
    claims = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        "jti": str(uuid4()),
        "exp": now + 240,  # 4 minutes
        "iat": now,
    }
    token = jwt.encode(claims, private_key_pem, algorithm="RS384")
    # PyJWT >= 2.x returns str; older versions returned bytes — normalise
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


# ── Token exchange ────────────────────────────────────────────────────────────


def exchange_jwt_for_token(
    token_url: str,
    jwt_assertion: str,
    scope: str = "system/*.read",
) -> dict:
    """POST a JWT assertion to the token endpoint and return the full response.

    Args:
        token_url:      SMART token endpoint.
        jwt_assertion:  Signed JWT produced by build_jwt_assertion().
        scope:          OAuth2 scope string.

    Returns:
        Dict with at minimum ``access_token`` and ``expires_in`` keys.

    Raises:
        requests.HTTPError: on non-2xx response.
    """
    resp = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_assertion_type": ("urn:ietf:params:oauth:client-assertion-type:jwt-bearer"),
            "client_assertion": jwt_assertion,
            "scope": scope,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Key file helpers ──────────────────────────────────────────────────────────


def keys_dir() -> Path:
    """Return (and create if needed) the keys sub-directory inside config dir."""
    path = config_dir() / "keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tokens_dir() -> Path:
    """Return (and create if needed) the tokens cache directory."""
    path = config_dir() / "tokens"
    path.mkdir(parents=True, exist_ok=True)
    return path


def private_key_path(profile_name: str) -> Path:
    """Canonical path for a profile's private key PEM file."""
    return keys_dir() / f"{profile_name}.pem"


def save_private_key(profile_name: str, private_key_pem: str) -> Path:
    """Write the private key PEM to disk and return the path."""
    path = private_key_path(profile_name)
    path.write_text(private_key_pem, encoding="utf-8")
    # Restrict permissions on Unix-like systems
    try:
        path.chmod(0o600)
    except NotImplementedError:
        pass  # Windows — skip
    return path


def load_private_key(profile_name: str) -> str:
    """Read and return the private key PEM for a profile.

    Raises:
        FileNotFoundError: if the key file does not exist.
    """
    path = private_key_path(profile_name)
    if not path.exists():
        raise FileNotFoundError(
            f"Private key not found for profile '{profile_name}'. "
            f"Run: healthcarecli fhir keygen {profile_name}"
        )
    return path.read_text(encoding="utf-8")


# ── Token cache ───────────────────────────────────────────────────────────────


def _token_cache_path(profile_name: str) -> Path:
    return tokens_dir() / f"{profile_name}.json"


def cache_token(profile_name: str, token_response: dict) -> None:
    """Persist a token response dict with an absolute expiry timestamp."""
    expires_in = int(token_response.get("expires_in", 3600))
    cached = dict(token_response)
    cached["_expires_at"] = int(time.time()) + expires_in
    path = _token_cache_path(profile_name)
    path.write_text(json.dumps(cached, indent=2), encoding="utf-8")


def load_cached_token(profile_name: str, min_remaining: int = 60) -> dict | None:
    """Return a cached token if it has at least *min_remaining* seconds left.

    Returns:
        The cached token dict, or None if absent / expired.
    """
    path = _token_cache_path(profile_name)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    expires_at = cached.get("_expires_at", 0)
    if int(time.time()) + min_remaining < expires_at:
        return cached
    return None
