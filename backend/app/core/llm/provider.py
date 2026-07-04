from typing import Protocol


class ProviderError(Exception):
    """Raised by a Provider when a call fails (timeout, rate limit, API error)."""


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, model: str, temperature: float) -> str: ...


def strip_json_code_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ``` or ``` ... ```), if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped
