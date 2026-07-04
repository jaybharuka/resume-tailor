from typing import Protocol


class ProviderError(Exception):
    """Raised by a Provider when a call fails (timeout, rate limit, API error)."""


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, model: str, temperature: float) -> str: ...


def strip_json_code_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ``` or ``` ... ```), if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    if "\n" not in stripped:
        # Single-line fence: the entire payload sits between the opening and
        # closing ``` with no line breaks at all, e.g. '```json{"a": 1}```'.
        inner = stripped[3:]
        if inner.endswith("```"):
            inner = inner[:-3]
        if inner.lower().startswith("json"):
            inner = inner[4:]
        return inner.strip()

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines:
        last = lines[-1].rstrip()
        if last == "```":
            lines = lines[:-1]
        elif last.endswith("```"):
            # Closing fence attached to the same line as trailing content,
            # e.g. the last line is '{"a": 1}```' rather than '```' alone.
            lines[-1] = last[:-3]
    return "\n".join(lines).strip()
