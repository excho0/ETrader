from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.core.config import Settings, get_settings

READ_SCOPE = "read"
DIAGNOSTICS_SCOPE = "diagnostics"
PREVIEW_SCOPE = "trade.preview"
EXECUTE_SCOPE = "trade.execute"

http_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthPrincipal:
    token: str
    scopes: set[str]


def build_token_map(settings: Settings) -> dict[str, AuthPrincipal]:
    tokens: dict[str, AuthPrincipal] = {}

    def register(token: str | None, scopes: set[str]) -> None:
        if token:
            tokens[token] = AuthPrincipal(token=token, scopes=scopes)

    register(
        settings.auth_agent_token,
        {READ_SCOPE, DIAGNOSTICS_SCOPE, PREVIEW_SCOPE},
    )
    register(
        settings.auth_execute_token,
        {READ_SCOPE, DIAGNOSTICS_SCOPE, PREVIEW_SCOPE, EXECUTE_SCOPE},
    )
    return tokens


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, settings: Settings) -> None:
        self._tokens = build_token_map(settings)

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = self._tokens.get(token)
        if principal is None:
            return None

        return AccessToken(
            token=principal.token,
            client_id="etrader-static-client",
            scopes=sorted(principal.scopes),
            expires_at=None,
            resource=None,
        )


def build_token_verifier(settings: Settings) -> StaticTokenVerifier:
    return StaticTokenVerifier(settings)


def require_http_scopes(*required_scopes: str):
    async def dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
        settings: Settings = Depends(get_settings),
    ) -> AuthPrincipal | None:
        if not settings.auth_enabled:
            return None

        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        principal = build_token_map(settings).get(credentials.credentials)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
            )

        missing = [scope for scope in required_scopes if scope not in principal.scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(missing)}",
            )

        return principal

    return dependency


def require_mcp_scopes(*required_scopes: str) -> None:
    settings = get_settings()
    token = get_access_token()

    if token is None:
        if settings.mcp_stdio_auth_bypass:
            return
        raise PermissionError("Authenticated MCP access is required")

    missing = [scope for scope in required_scopes if scope not in token.scopes]
    if missing:
        raise PermissionError(f"Missing required scopes: {', '.join(missing)}")
