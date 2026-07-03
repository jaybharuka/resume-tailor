from typing import Protocol


class ProviderError(Exception):
    """Raised by a Provider when a call fails (timeout, rate limit, API error)."""


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, model: str, temperature: float) -> str: ...
