import time
from typing import Callable
from openai import OpenAI
from openai import APIStatusError, APIConnectionError, APITimeoutError
from app.core.llm.provider import ProviderError, strip_json_code_fence
from app.core.llm.retry import with_backoff


def _is_retryable_nvidia_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _sanitize(message: str, api_key: str) -> str:
    if api_key and api_key in message:
        return message.replace(api_key, "***REDACTED***")
    return message


class NvidiaProvider:
    name = "nvidia"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._api_key = api_key
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._sleep = sleep

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        def call():
            completion = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=1,
                max_tokens=16384,
                seed=42,
            )
            return strip_json_code_fence(completion.choices[0].message.content)

        try:
            return with_backoff(
                call, is_retryable=_is_retryable_nvidia_error,
                max_retries=5, base_delay=10.0, max_delay=120.0,
                sleep=self._sleep,
            )
        except Exception as exc:
            raise ProviderError(f"NVIDIA call failed: {_sanitize(str(exc), self._api_key)}") from exc
