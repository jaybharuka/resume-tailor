class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        raise NotImplementedError("GeminiProvider is a Phase 1 stub; wired in a later phase.")


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        raise NotImplementedError("ClaudeProvider is a Phase 1 stub; wired in a later phase.")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        raise NotImplementedError("OpenAIProvider is a Phase 1 stub; wired in a later phase.")
