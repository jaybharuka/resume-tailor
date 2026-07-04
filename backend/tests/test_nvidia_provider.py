import pytest
from app.core.llm.provider import ProviderError
from app.core.llm.providers import nvidia_provider as nvidia_provider_module
from app.core.llm.providers.nvidia_provider import NvidiaProvider


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeAPIStatusError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class FakeCompletions:
    def create(self, **kwargs):
        return FakeCompletion('{"text": "hello from nvidia"}')


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeOpenAIClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = FakeChat()


def test_generate_returns_model_text(monkeypatch):
    monkeypatch.setattr(nvidia_provider_module, "OpenAI", FakeOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key")
    result = provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert result == '{"text": "hello from nvidia"}'


def test_generate_wraps_unexpected_errors_as_provider_error(monkeypatch):
    class BrokenCompletions:
        def create(self, **kwargs):
            raise RuntimeError("connection reset")

    class BrokenChat:
        def __init__(self):
            self.completions = BrokenCompletions()

    class BrokenOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = BrokenChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", BrokenOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key")
    with pytest.raises(ProviderError):
        provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)


def test_auth_error_fails_fast_without_retrying(monkeypatch):
    monkeypatch.setattr(nvidia_provider_module, "APIStatusError", FakeAPIStatusError)

    call_count = {"n": 0}

    class AuthFailingCompletions:
        def create(self, **kwargs):
            call_count["n"] += 1
            raise FakeAPIStatusError("Invalid API key", status_code=401)

    class AuthFailingChat:
        def __init__(self):
            self.completions = AuthFailingCompletions()

    class AuthFailingOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = AuthFailingChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", AuthFailingOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key", sleep=lambda s: None)
    with pytest.raises(ProviderError):
        provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert call_count["n"] == 1


def test_rate_limit_error_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(nvidia_provider_module, "APIStatusError", FakeAPIStatusError)

    call_count = {"n": 0}

    class FlakyCompletions:
        def create(self, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise FakeAPIStatusError("Rate limited", status_code=429)
            return FakeCompletion('{"text": "hello from nvidia"}')

    class FlakyChat:
        def __init__(self):
            self.completions = FlakyCompletions()

    class FlakyOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = FlakyChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", FlakyOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key", sleep=lambda s: None)
    result = provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert result == '{"text": "hello from nvidia"}'
    assert call_count["n"] == 2


def test_api_key_never_appears_in_provider_error_message(monkeypatch):
    secret_key = "nvapi-super-secret-value-123"

    class LeakyCompletions:
        def create(self, **kwargs):
            raise RuntimeError(f"request failed, Authorization: Bearer {secret_key}")

    class LeakyChat:
        def __init__(self):
            self.completions = LeakyCompletions()

    class LeakyOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = LeakyChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", LeakyOpenAIClient)

    provider = NvidiaProvider(api_key=secret_key, sleep=lambda s: None)
    with pytest.raises(ProviderError) as exc_info:
        provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert secret_key not in str(exc_info.value)


def test_generate_strips_markdown_json_code_fence(monkeypatch):
    class FencedCompletions:
        def create(self, **kwargs):
            return FakeCompletion('```json\n{"text": "hello from nvidia"}\n```')

    class FencedChat:
        def __init__(self):
            self.completions = FencedCompletions()

    class FencedOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = FencedChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", FencedOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key")
    result = provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert result == '{"text": "hello from nvidia"}'
