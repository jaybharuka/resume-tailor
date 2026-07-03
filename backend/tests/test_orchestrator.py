import pytest
from pydantic import BaseModel
from app.core.llm.provider import ProviderError
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError


class EchoResult(BaseModel):
    text: str


class FailNTimesProvider:
    def __init__(self, name: str, fail_times: int, output: str = '{"text": "ok"}'):
        self.name = name
        self.fail_times = fail_times
        self.output = output
        self.calls = 0

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("simulated failure")
        return self.output


class AlwaysFailsProvider:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        self.calls += 1
        raise ProviderError("simulated failure")


class BadJsonProvider:
    name = "bad_json"

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        return "not json"


class RaisesUnexpectedErrorProvider:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        self.calls += 1
        raise RuntimeError("unexpected bug, not a ProviderError")


def test_succeeds_on_same_provider_retry():
    provider = FailNTimesProvider(name="gemini", fail_times=1)
    orchestrator = AIOrchestrator(providers={"gemini": provider})
    task = TaskConfig(task_type="echo", provider="gemini", model="m1", temperature=0.5, response_schema=EchoResult)

    result = orchestrator.run(task, prompt="hi")

    assert result.output.text == "ok"
    assert result.provider_used == "gemini"
    assert provider.calls == 2


def test_falls_back_to_next_provider_after_same_provider_retry_fails():
    primary = AlwaysFailsProvider(name="nvidia")
    fallback = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(providers={"nvidia": primary, "gemini": fallback})
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    result = orchestrator.run(task, prompt="hi")

    assert result.provider_used == "gemini"
    assert primary.calls == 2
    assert fallback.calls == 1


def test_raises_orchestrator_error_when_all_providers_exhausted():
    primary = AlwaysFailsProvider(name="nvidia")
    fallback = AlwaysFailsProvider(name="gemini")
    orchestrator = AIOrchestrator(providers={"nvidia": primary, "gemini": fallback})
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    with pytest.raises(OrchestratorError):
        orchestrator.run(task, prompt="hi")


def test_schema_validation_failure_is_treated_as_a_failed_attempt():
    bad = BadJsonProvider()
    good = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(providers={"bad_json": bad, "gemini": good})
    task = TaskConfig(
        task_type="echo", provider="bad_json", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    result = orchestrator.run(task, prompt="hi")

    assert result.provider_used == "gemini"


def test_every_attempt_is_logged_including_failures():
    logged = []
    primary = AlwaysFailsProvider(name="nvidia")
    fallback = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(
        providers={"nvidia": primary, "gemini": fallback},
        on_call_logged=logged.append,
    )
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    orchestrator.run(task, prompt="hi")

    assert len(logged) == 3
    assert [entry["validated"] for entry in logged] == [False, False, True]


def test_unexpected_non_provider_error_is_logged_and_still_falls_back():
    logged = []
    primary = RaisesUnexpectedErrorProvider(name="nvidia")
    fallback = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(
        providers={"nvidia": primary, "gemini": fallback},
        on_call_logged=logged.append,
    )
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    result = orchestrator.run(task, prompt="hi")

    assert result.provider_used == "gemini"
    assert primary.calls == 2  # same-provider retry still happened despite the unexpected exception type
    assert len(logged) == 3  # nvidia attempt 1 (fail), nvidia attempt 2 (fail), gemini attempt 1 (success)
    assert [entry["validated"] for entry in logged] == [False, False, True]
