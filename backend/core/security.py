from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

import jwt
import requests
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from backend.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class EntraPrincipal:
    token: str
    claims: dict[str, Any]
    validation_mode: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenIDConfiguration:
    issuer: str
    jwks_uri: str


class EntraTokenValidator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._openid_config = self._load_openid_configuration()
        self._jwk_client = PyJWKClient(
            self._openid_config.jwks_uri,
            cache_jwk_set=True,
            lifespan=settings.entra_jwks_cache_ttl_seconds,
        )

    def validate_token(self, token: str) -> EntraPrincipal:
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=self.settings.entra_allowed_algorithms,
            audience=_build_valid_audiences(self.settings),
            issuer=self.settings.entra_expected_issuer or self._openid_config.issuer,
            leeway=self.settings.entra_clock_skew_seconds,
            options={"require": ["aud", "exp", "iat", "iss", "nbf"]},
        )
        return EntraPrincipal(token=token, claims=claims, validation_mode="jwks")

    def _load_openid_configuration(self) -> OpenIDConfiguration:
        metadata_url = self.settings.entra_metadata_url or _build_metadata_url(self.settings)
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        issuer = self.settings.entra_expected_issuer or payload["issuer"]
        return OpenIDConfiguration(issuer=issuer, jwks_uri=payload["jwks_uri"])


def _build_metadata_url(settings: Settings) -> str:
    tenant_id = settings.entra_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Entra tenant id is missing.",
        )
    return f"{settings.entra_authority_host.rstrip('/')}/{tenant_id}/v2.0/.well-known/openid-configuration"


def _build_valid_audiences(settings: Settings) -> list[str]:
    audiences: set[str] = set()
    if settings.entra_audience:
        audiences.add(settings.entra_audience)
        if settings.entra_audience.startswith("api://"):
            audiences.add(settings.entra_audience.removeprefix("api://"))
    if settings.entra_client_id:
        audiences.add(settings.entra_client_id)
        audiences.add(f"api://{settings.entra_client_id}")
    return sorted(audiences)


@lru_cache(maxsize=1)
def get_token_validator() -> EntraTokenValidator:
    return EntraTokenValidator(get_settings())


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> EntraPrincipal | None:
    if not settings.entra_enabled:
        return None
    if not settings.entra_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Entra is enabled but backend configuration is incomplete.",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    try:
        return get_token_validator().validate_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid access token: {exc}",
        ) from exc
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Entra discovery is temporarily unavailable.",
        ) from exc


def get_principal_object_id(principal: EntraPrincipal) -> str | None:
    return principal.claims.get("oid") or principal.claims.get("sub")


def principal_has_required_scope_or_role(principal: EntraPrincipal, settings: Settings) -> bool:
    principal_roles = set(principal.claims.get("roles", []))
    if principal_roles.intersection(settings.admin_required_roles):
        return True

    scopes = principal.claims.get("scp", "")
    principal_scopes = {value.strip() for value in scopes.split(" ") if value.strip()}
    if principal_scopes.intersection(settings.admin_required_scopes):
        return True

    principal_id = get_principal_object_id(principal)
    if principal_id and principal_id in settings.admin_bootstrap_object_ids:
        return True

    return False


async def require_admin_principal(
    request: Request,
    principal: EntraPrincipal | None = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> EntraPrincipal:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    if principal_has_required_scope_or_role(principal, settings):
        return principal

    admin_service = request.app.state.admin_service
    principal_id = get_principal_object_id(principal)
    if principal_id is not None:
        user = await admin_service.get_user(principal_id)
        if user is not None and user.enabled and user.is_admin:
            return principal

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access is required.",
    )
