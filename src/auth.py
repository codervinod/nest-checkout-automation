"""OAuth token management for Google SDM API."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# Google OAuth endpoints
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
SDM_SCOPES = ["https://www.googleapis.com/auth/sdm.service"]


class TokenManager:
    """Manages OAuth tokens for Google SDM API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._credentials: Optional[Credentials] = None
        self._last_refresh: Optional[datetime] = None

    def _create_credentials(self) -> Credentials:
        """Create credentials object from refresh token."""
        return Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=SDM_SCOPES,
        )

    def get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Returns:
            Valid access token string.

        Raises:
            Exception: If token refresh fails.
        """
        # Create credentials if not exists
        if self._credentials is None:
            self._credentials = self._create_credentials()

        # Check if token needs refresh (expired or expiring within 10 minutes)
        needs_refresh = (
            self._credentials.token is None
            or self._credentials.expired
            or (
                self._credentials.expiry
                and self._credentials.expiry < datetime.utcnow() + timedelta(minutes=10)
            )
        )

        if needs_refresh:
            logger.info("Refreshing OAuth token...")
            try:
                self._credentials.refresh(Request())
                self._last_refresh = datetime.utcnow()
                logger.info(
                    f"Token refreshed successfully. Expires at: {self._credentials.expiry}"
                )
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                raise

        return self._credentials.token

    @property
    def token_expiry(self) -> Optional[datetime]:
        """Get the current token expiry time."""
        if self._credentials:
            return self._credentials.expiry
        return None

    @property
    def last_refresh_time(self) -> Optional[datetime]:
        """Get the last time the token was refreshed."""
        return self._last_refresh

    def get_auth_header(self) -> dict:
        """Get authorization header for API requests.

        Returns:
            Dictionary with Authorization header.
        """
        token = self.get_valid_token()
        return {"Authorization": f"Bearer {token}"}
