import json
import os
import tempfile
import time
from typing import Any, Dict, Optional

import httpx

from litellm._logging import verbose_logger

from .common_utils import GetAccessTokenError, RefreshTokenError

# Google OAuth endpoints/constants
# Defaults pulled from Gemini CLI but can be overridden via env vars for custom apps
OAUTH_CLIENT_ID = os.getenv(
    "GEMINI_OAUTH_CLIENT_ID",
    "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com",
)
OAUTH_CLIENT_SECRET = os.getenv(
    "GEMINI_OAUTH_CLIENT_SECRET",
    "INSERT_CLIENT_SECRET_HERE",
)
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

DEFAULT_TOKEN_PATH = os.path.join(os.path.expanduser("~/.gemini"), "oauth_creds.json")
DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


class Authenticator:
    """
    Lightweight Gemini OAuth token loader/refresh helper.

    The Gemini CLI stores OAuth credentials at ~/.gemini/oauth_creds.json in the
    google-auth-library format:
      {
        "access_token": "...",
        "refresh_token": "...",
        "token_type": "Bearer",
        "expiry_date": 1730000000000,
        "scope": "..."
      }
    """

    def __init__(self) -> None:
        token_path = os.getenv("GEMINI_OAUTH_TOKEN_FILE", DEFAULT_TOKEN_PATH)
        token_dir = os.getenv("GEMINI_OAUTH_TOKEN_DIR")
        if token_dir:
            token_path = os.path.join(os.path.expanduser(token_dir), "oauth_creds.json")
        self.token_path = os.path.expanduser(token_path)
        self.api_base = os.getenv("GEMINI_OAUTH_API_BASE", DEFAULT_API_BASE)

    def get_api_base(self) -> str:
        return self.api_base

    def get_access_token(self) -> str:
        creds = self._load_creds()
        if not creds:
            raise GetAccessTokenError(
                message="Gemini OAuth credentials not found. Please log in via Gemini CLI.",
                status_code=401,
            )

        access_token = creds.get("access_token")
        expiry_date = creds.get("expiry_date")

        if access_token and not self._is_expired(expiry_date):
            return access_token

        refresh_token = creds.get("refresh_token")
        if not refresh_token:
            raise GetAccessTokenError(
                message="Access token expired and no refresh token available.",
                status_code=401,
            )

        refreshed = self._refresh_access_token(refresh_token)
        return refreshed

    def _load_creds(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self.token_path, "r") as f:
                return json.load(f)
        except Exception as e:  # noqa: BLE001
            verbose_logger.debug(f"Unable to read Gemini OAuth credentials: {e}")
        return None

    def _save_creds(self, creds: Dict[str, Any]) -> None:
        """
        Persists credentials using an atomic write to prevent corruption
        during concurrent refreshes.
        """

        tmp_path = None
        try:
            dir_name = os.path.dirname(self.token_path)
            os.makedirs(dir_name, exist_ok=True)

            # Write to a temp file first
            with tempfile.NamedTemporaryFile("w", delete=False, dir=dir_name) as tmp_f:
                json.dump(creds, tmp_f)
                tmp_path = tmp_f.name

            # Atomic replacement of the target file
            os.replace(tmp_path, self.token_path)
        except Exception as e:  # noqa: BLE001
            verbose_logger.warning(f"Failed to persist refreshed Gemini credentials: {e}")
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _is_expired(self, expiry_date: Optional[float]) -> bool:
        if expiry_date is None:
            return False
        # expiry_date from google-auth is milliseconds; normalize to seconds
        seconds = expiry_date / 1000 if expiry_date > 10_000_000_000 else expiry_date
        return seconds < time.time() + 60  # refresh 1 minute early

    def _refresh_access_token(self, refresh_token: str) -> str:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
        }
        try:
            resp = httpx.post(
                GOOGLE_TOKEN_ENDPOINT,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise RefreshTokenError(
                    message="Gemini OAuth refresh response missing access_token",
                    status_code=401,
                )

            # Merge back into credential cache; keep existing refresh token if not returned
            updated_creds = self._load_creds() or {}
            updated_creds.update(payload)
            if "refresh_token" not in updated_creds:
                updated_creds["refresh_token"] = refresh_token
            if "expiry_date" not in updated_creds and "expires_in" in payload:
                updated_creds["expiry_date"] = (time.time() + int(payload["expires_in"])) * 1000
            self._save_creds(updated_creds)
            return access_token
        except httpx.HTTPStatusError as e:
            raise RefreshTokenError(
                message=f"Gemini OAuth refresh failed: {e}",
                status_code=e.response.status_code,
                request=e.request,
                response=e.response,
            )
        except Exception as e:  # noqa: BLE001
            raise RefreshTokenError(message=f"Gemini OAuth refresh failed: {e}", status_code=500)
