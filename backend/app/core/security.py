"""Supabase JWT verification. The role is NEVER taken from the token; it comes from `users`."""
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


@lru_cache
def _jwks(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
    except jwt.PyJWTError as exc:
        raise AuthError("malformed token") from exc

    issuer = f"{settings.supabase_url}/auth/v1" if settings.supabase_url else None
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise AuthError("HS256 tokens are not accepted by this server")
        key: Any = settings.supabase_jwt_secret
        algorithms = ["HS256"]
    elif alg in ("RS256", "ES256", "EdDSA"):
        if not settings.supabase_jwks_url:
            raise AuthError("asymmetric tokens are not accepted by this server")
        try:
            key = _jwks(settings.supabase_jwks_url).get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthError("authentication service unreachable", 503) from exc
        except jwt.PyJWTError as exc:
            raise AuthError("unknown signing key") from exc
        algorithms = [alg]
    else:
        raise AuthError("unsupported token algorithm")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience="authenticated",
            issuer=issuer,
            leeway=10,
            options={"require": ["exp", "sub"], "verify_iss": issuer is not None},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("invalid token") from exc
    return claims
