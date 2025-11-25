from typing import Optional, Tuple

from litellm.exceptions import AuthenticationError
from litellm.llms.openai.openai import OpenAIConfig

from ..authenticator import Authenticator
from ..common_utils import GetAccessTokenError, RefreshTokenError


class GeminiOAuthConfig(OpenAIConfig):
    """
    OpenAI-compatible config for Gemini API when authenticated via OAuth.

    Uses the Google OAuth access token as the bearer credential and points to
    the Gemini OpenAI-compatible base URL.
    """

    def __init__(self) -> None:
        super().__init__()
        self.authenticator = Authenticator()

    def _get_openai_compatible_provider_info(
        self,
        model: str,
        api_base: Optional[str],
        api_key: Optional[str],
        custom_llm_provider: str,
    ) -> Tuple[Optional[str], Optional[str], str]:
        dynamic_api_base = api_base or self.authenticator.get_api_base()
        try:
            dynamic_api_key = api_key or self.authenticator.get_access_token()
        except (GetAccessTokenError, RefreshTokenError) as e:
            raise AuthenticationError(
                model=model,
                llm_provider=custom_llm_provider,
                message=str(e),
            )
        return dynamic_api_base, dynamic_api_key, custom_llm_provider
