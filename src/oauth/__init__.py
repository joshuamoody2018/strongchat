"""StrongChat OAuth 2.0 authorization-server provider (MCP SDK plug-in).

Implements ``mcp.server.auth.provider.OAuthAuthorizationServerProvider`` for
the single-user self-hosted deploy, so a hosted claude.ai web custom-connector
can run the full OAuth 2.0 PKCE onboarding flow against the same streamable-HTTP
endpoint (no separately-pasted static bearer needed for that flow).
"""

from .provider import (
    StrongChatOAuthProvider,
    load_oauth_config,
    SCOPE_RETRIEVE_CONTEXT,
    SCOPES_SUPPORTED,
)

__all__ = [
    "StrongChatOAuthProvider",
    "load_oauth_config",
    "SCOPE_RETRIEVE_CONTEXT",
    "SCOPES_SUPPORTED",
]