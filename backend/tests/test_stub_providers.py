import pytest
from app.core.llm.providers.stub_providers import GeminiProvider, ClaudeProvider, OpenAIProvider


def test_gemini_provider_raises_not_implemented():
    provider = GeminiProvider(api_key="unused")
    with pytest.raises(NotImplementedError):
        provider.generate("hi", model="gemini-x", temperature=0.5)


def test_claude_provider_raises_not_implemented():
    provider = ClaudeProvider(api_key="unused")
    with pytest.raises(NotImplementedError):
        provider.generate("hi", model="claude-x", temperature=0.5)


def test_openai_provider_raises_not_implemented():
    provider = OpenAIProvider(api_key="unused")
    with pytest.raises(NotImplementedError):
        provider.generate("hi", model="gpt-x", temperature=0.5)
