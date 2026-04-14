"""OBO (On-Behalf-Of) token exchange helper for SharePoint access.

This module handles exchanging a user's delegated access token for a
Microsoft Graph or SharePoint-scoped token using the OAuth 2.0 OBO flow.
"""

from __future__ import annotations

import logging
from typing import Any

import msal

logger = logging.getLogger(__name__)


class OBOTokenProvider:
    """Provides OBO token exchange using MSAL ConfidentialClientApplication.

    The OBO flow allows a middle-tier service to exchange a user's access token
    for a new token scoped to downstream APIs (e.g., Microsoft Graph, SharePoint).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._authority = f"https://login.microsoftonline.com/{tenant_id}"
        self._client_id = client_id
        self._client_secret = client_secret
        self._app: msal.ConfidentialClientApplication | None = None

    def _get_app(self) -> msal.ConfidentialClientApplication:
        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                client_id=self._client_id,
                client_credential=self._client_secret,
                authority=self._authority,
            )
        return self._app

    def exchange_token(
        self,
        user_assertion: str,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Exchange a user token for a downstream API token via OBO flow.

        Args:
            user_assertion: The user's access token (Bearer token) to exchange.
            scopes: Target API scopes. Defaults to Microsoft Graph scopes.

        Returns:
            MSAL token response dict containing 'access_token' on success,
            or 'error' / 'error_description' on failure.
        """
        if scopes is None:
            scopes = ["https://graph.microsoft.com/.default"]

        app = self._get_app()
        result = app.acquire_token_on_behalf_of(
            user_assertion=user_assertion,
            scopes=scopes,
        )

        if "access_token" in result:
            logger.info("OBO token exchange succeeded for scopes: %s", scopes)
        else:
            logger.error(
                "OBO token exchange failed: %s - %s",
                result.get("error"),
                result.get("error_description"),
            )
        return result

    def get_graph_token(self, user_assertion: str) -> str | None:
        """Exchange user token for a Microsoft Graph token.

        Args:
            user_assertion: The user's incoming access token.

        Returns:
            The downstream Graph access token, or None on failure.
        """
        result = self.exchange_token(
            user_assertion=user_assertion,
            scopes=["https://graph.microsoft.com/.default"],
        )
        return result.get("access_token")

    def get_sharepoint_token(
        self,
        user_assertion: str,
        sharepoint_host: str,
    ) -> str | None:
        """Exchange user token for a SharePoint-scoped token.

        Args:
            user_assertion: The user's incoming access token.
            sharepoint_host: The SharePoint host, e.g. 'contoso.sharepoint.com'.

        Returns:
            The downstream SharePoint access token, or None on failure.
        """
        result = self.exchange_token(
            user_assertion=user_assertion,
            scopes=[f"https://{sharepoint_host}/.default"],
        )
        return result.get("access_token")
