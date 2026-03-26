from google import genai
from google.genai.types import HttpOptions, HttpRetryOptions

from newspulse.config import settings

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=HttpOptions(
                timeout=60_000,
                retry_options=HttpRetryOptions(
                    attempts=4,
                    initial_delay=1.0,
                    max_delay=30.0,
                ),
            ),
        )
    return _client
