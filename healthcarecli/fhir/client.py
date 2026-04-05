"""FHIR R4 HTTP client — profile management, CRUD, search, auth."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from healthcarecli.config.manager import (
    delete_profile,
    get_profile,
    list_profiles,
    save_profile,
)

SECTION = "fhir"

# FHIR resource types agents commonly need
COMMON_RESOURCE_TYPES = [
    "Patient",
    "Observation",
    "Condition",
    "MedicationRequest",
    "Procedure",
    "DiagnosticReport",
    "ImagingStudy",
    "Encounter",
    "AllergyIntolerance",
    "Immunization",
    "Practitioner",
    "Organization",
    "Location",
    "ServiceRequest",
    "DocumentReference",
]


# ── Profile ───────────────────────────────────────────────────────────────────


@dataclass
class FHIRProfile:
    """Connection profile for a FHIR R4 server."""

    name: str
    url: str  # Base URL, e.g. https://hapi.fhir.org/baseR4
    auth_type: str = "none"  # "none" | "basic" | "bearer" | "smart"
    username: str = ""
    password: str = ""
    token: str = ""  # Bearer / SMART access token
    # SMART on FHIR: token endpoint for client-credentials flow
    token_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    # Backend Services JWT flow: path to RSA private key PEM
    private_key_path: str = ""

    # ── persistence ───────────────────────────────────────────────────────

    def save(self) -> None:
        data = asdict(self)
        data.pop("name")
        save_profile(SECTION, self.name, data)

    @classmethod
    def load(cls, name: str) -> FHIRProfile:
        data = get_profile(SECTION, name)
        if data is None:
            raise FHIRProfileNotFoundError(name)
        return cls(name=name, **data)

    @classmethod
    def list_all(cls) -> list[FHIRProfile]:
        return [cls(name=n, **v) for n, v in list_profiles(SECTION).items()]

    def delete(self) -> None:
        if not delete_profile(SECTION, self.name):
            raise FHIRProfileNotFoundError(self.name)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("password"):
            d["password"] = "***"
        if d.get("token"):
            d["token"] = "***"
        if d.get("client_secret"):
            d["client_secret"] = "***"
        return d

    # ── HTTP session ──────────────────────────────────────────────────────

    def session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"}
        )
        if self.auth_type == "basic":
            s.auth = HTTPBasicAuth(self.username, self.password)
        elif self.auth_type in ("bearer", "smart"):
            token = self._resolve_token()
            s.headers.update({"Authorization": f"Bearer {token}"})
        return s

    def _resolve_token(self) -> str:
        """Return bearer token; for smart/client-credentials, fetch one if not set."""
        if self.token:
            return self.token
        if self.auth_type == "smart" and self.token_url and self.client_id:
            # Backend Services JWT flow (private key present)
            if self.private_key_path:
                return _fetch_jwt_token(self.name, self.token_url, self.client_id)
            # Legacy client-secret flow
            return _fetch_client_credentials_token(
                self.token_url, self.client_id, self.client_secret
            )
        raise FHIRAuthError(
            "No token configured. Set --token or configure SMART client credentials."
        )


class FHIRProfileNotFoundError(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"FHIR profile '{name}' not found")
        self.name = name


class FHIRAuthError(RuntimeError):
    pass


class FHIRError(RuntimeError):
    """HTTP-level or FHIR OperationOutcome error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _fetch_client_credentials_token(token_url: str, client_id: str, client_secret: str) -> str:
    resp = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    _raise_for_fhir(resp)
    return resp.json()["access_token"]


def _fetch_jwt_token(profile_name: str, token_url: str, client_id: str) -> str:
    """Fetch (or return cached) a Backend Services JWT access token."""
    from healthcarecli.fhir.token import (
        build_jwt_assertion,
        cache_token,
        exchange_jwt_for_token,
        load_cached_token,
        load_private_key,
    )

    cached = load_cached_token(profile_name)
    if cached:
        return cached["access_token"]

    private_key_pem = load_private_key(profile_name)
    assertion = build_jwt_assertion(client_id, token_url, private_key_pem)
    token_response = exchange_jwt_for_token(token_url, assertion)
    cache_token(profile_name, token_response)
    return token_response["access_token"]


# ── FHIR CRUD + search ────────────────────────────────────────────────────────


def fhir_search(
    profile: FHIRProfile,
    resource_type: str,
    params: dict[str, str] | None = None,
    count: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Search for FHIR resources. Returns a raw Bundle dict.

    Args:
        profile:        FHIR server profile.
        resource_type:  e.g. "Patient", "Observation".
        params:         FHIR search parameters as {param: value}.
        count:          _count (max results per page).
        offset:         _getpagesoffset.

    Raises:
        FHIRError: on HTTP error or OperationOutcome failure.
    """
    url = f"{profile.url.rstrip('/')}/{resource_type}"
    query: dict[str, str] = dict(params or {})
    if count is not None:
        query["_count"] = str(count)
    if offset is not None:
        query["_getpagesoffset"] = str(offset)

    resp = profile.session().get(url, params=query, timeout=30)
    _raise_for_fhir(resp)
    return resp.json()


def fhir_get(
    profile: FHIRProfile,
    resource_type: str,
    resource_id: str,
) -> dict[str, Any]:
    """Read a single FHIR resource by type/id."""
    url = f"{profile.url.rstrip('/')}/{resource_type}/{resource_id}"
    resp = profile.session().get(url, timeout=30)
    _raise_for_fhir(resp)
    return resp.json()


def fhir_create(
    profile: FHIRProfile,
    resource: dict[str, Any],
) -> dict[str, Any]:
    """Create a new FHIR resource (POST). Returns the created resource."""
    resource_type = resource.get("resourceType")
    if not resource_type:
        raise FHIRError("Resource must include a 'resourceType' field")
    url = f"{profile.url.rstrip('/')}/{resource_type}"
    resp = profile.session().post(url, data=json.dumps(resource), timeout=30)
    _raise_for_fhir(resp)
    return resp.json()


def fhir_update(
    profile: FHIRProfile,
    resource_type: str,
    resource_id: str,
    resource: dict[str, Any],
) -> dict[str, Any]:
    """Update a FHIR resource (PUT). Returns the updated resource."""
    url = f"{profile.url.rstrip('/')}/{resource_type}/{resource_id}"
    resource.setdefault("resourceType", resource_type)
    resource.setdefault("id", resource_id)
    resp = profile.session().put(url, data=json.dumps(resource), timeout=30)
    _raise_for_fhir(resp)
    return resp.json()


def fhir_delete(
    profile: FHIRProfile,
    resource_type: str,
    resource_id: str,
) -> None:
    """Delete a FHIR resource (DELETE)."""
    url = f"{profile.url.rstrip('/')}/{resource_type}/{resource_id}"
    resp = profile.session().delete(url, timeout=30)
    _raise_for_fhir(resp)


def fhir_capabilities(profile: FHIRProfile) -> dict[str, Any]:
    """Fetch the server's CapabilityStatement (metadata)."""
    url = f"{profile.url.rstrip('/')}/metadata"
    resp = profile.session().get(url, timeout=30)
    _raise_for_fhir(resp)
    return resp.json()


# ── helpers ───────────────────────────────────────────────────────────────────


def _raise_for_fhir(resp: requests.Response) -> None:
    """Raise FHIRError on non-2xx, surfacing OperationOutcome details if present."""
    if resp.ok:
        return
    detail = ""
    try:
        body = resp.json()
        if body.get("resourceType") == "OperationOutcome":
            issues = body.get("issue", [])
            detail = "; ".join(
                i.get("diagnostics") or i.get("details", {}).get("text", "")
                for i in issues
                if i.get("severity") in ("error", "fatal")
            )
    except Exception:
        detail = resp.text[:300]
    raise FHIRError(
        f"HTTP {resp.status_code} — {detail or resp.reason}",
        status_code=resp.status_code,
    )


def bundle_entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract resource dicts from a FHIR Bundle searchset."""
    return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]


def bundle_total(bundle: dict[str, Any]) -> int | None:
    return bundle.get("total")
