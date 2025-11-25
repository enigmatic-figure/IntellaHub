import json
import os
import tempfile
import time
from typing import Any, Dict, Optional

import httpx

from litellm._logging import verbose_logger

from .common_utils import GetAccessTokenError, RefreshTokenError

QWEN_OAUTH_BASE_URL = "https://chat.qwen.ai"
QWEN_OAUTH_TOKEN_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/token"

# Default client ID, can be overridden via env var
QWEN_OAUTH_CLIENT_ID = os.getenv("QWEN_OAUTH_CLIENT_ID", "f0304373b74a44d2b584a3fb70ca9e56")

DEFAULT_TOKEN_PATH = os.path.join(os.path.expanduser("~/.qwen"), "oauth_creds.json")
DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class Authenticator:
    """
    Minimal device-flow credential loader/refresh helper for Qwen OAuth.

    Relies on the qwen-code CLI's cached credentials at ~/.qwen/oauth_creds.json:
      {
        "access_token": "...",
        "refresh_token": "...",
        "expiry_date": 1730000000000,
        "resource_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
      }
    """

    def __init__(self) -> None:
        token_path = os.getenv("QWEN_OAUTH_TOKEN_FILE", DEFAULT_TOKEN_PATH)
        token_dir = os.getenv("QWEN_OAUTH_TOKEN_DIR")
        if token_dir:
            token_path = os.path.join(os.path.expanduser(token_dir), "oauth_creds.json")
        self.token_path = os.path.expanduser(token_path)
        self.default_api_base = os.getenv("QWEN_OAUTH_API_BASE", DEFAULT_API_BASE)

    def get_api_base(self) -> str:
        creds = self._load_creds()
        return (
            creds.get("resource_url")
            if creds and creds.get("resource_url")
            else self.default_api_base
        )

    def get_access_token(self) -> str:
        creds = self._load_creds()
        if not creds:
            raise GetAccessTokenError(
                message="Qwen OAuth credentials not found. Please authenticate via Qwen CLI.",
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
            verbose_logger.debug(f"Unable to read Qwen OAuth credentials: {e}")
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
            verbose_logger.warning(f"Failed to persist refreshed Qwen credentials: {e}")
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _is_expired(self, expiry_date: Optional[float]) -> bool:
        if expiry_date is None:
            return False
        seconds = expiry_date / 1000 if expiry_date > 10_000_000_000 else expiry_date
        return seconds < time.time() + 60

    def _refresh_access_token(self, refresh_token: str) -> str:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": QWEN_OAUTH_CLIENT_ID,
        }
        try:
            resp = httpx.post(
                QWEN_OAUTH_TOKEN_ENDPOINT,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=data,
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise RefreshTokenError(
                    message="Qwen OAuth refresh response missing access_token",
                    status_code=401,
                )

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
                message=f"Qwen OAuth refresh failed: {e}",
                status_code=e.response.status_code,
                request=e.request,
                response=e.response,
            )
        except Exception as e:  # noqa: BLE001
            raise RefreshTokenError(
                message=f"Qwen OAuth refresh failed: {e}",
                status_code=500,
            )

