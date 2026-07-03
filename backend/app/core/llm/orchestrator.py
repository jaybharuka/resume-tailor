import time
from dataclasses import dataclass, field
from typing import Callable, Type
from pydantic import BaseModel, ValidationError
from app.core.llm.provider import ProviderError


class OrchestratorError(Exception):
    """Raised when every provider (primary + fallbacks, with same-provider retry) has failed."""


@dataclass
class TaskConfig:
    task_type: str
    provider: str
    model: str
    temperature: float
    response_schema: Type[BaseModel]
    fallback_providers: list[str] = field(default_factory=list)


@dataclass
class OrchestratorResult:
    output: BaseModel
    provider_used: str
    attempts: int


class AIOrchestrator:
    def __init__(self, providers: dict, on_call_logged: Callable[[dict], None] | None = None):
        self.providers = providers
        self.on_call_logged = on_call_logged or (lambda record: None)

    def _attempt(self, task: TaskConfig, provider_name: str, prompt: str):
        provider = self.providers[provider_name]
        started = time.monotonic()
        try:
            raw_output = provider.generate(prompt, model=task.model, temperature=task.temperature)
        except ProviderError as exc:
            self.on_call_logged({
                "provider": provider_name, "model": task.model, "task_type": task.task_type,
                "temperature": task.temperature, "validated": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "response_payload": None, "error": str(exc),
            })
            return None

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            parsed = task.response_schema.model_validate_json(raw_output)
        except ValidationError as exc:
            self.on_call_logged({
                "provider": provider_name, "model": task.model, "task_type": task.task_type,
                "temperature": task.temperature, "validated": False,
                "latency_ms": latency_ms, "response_payload": raw_output, "error": str(exc),
            })
            return None

        self.on_call_logged({
            "provider": provider_name, "model": task.model, "task_type": task.task_type,
            "temperature": task.temperature, "validated": True,
            "latency_ms": latency_ms, "response_payload": raw_output, "error": None,
        })
        return OrchestratorResult(output=parsed, provider_used=provider_name, attempts=1)

    def run(self, task: TaskConfig, prompt: str) -> OrchestratorResult:
        # task.provider appears twice: same-provider retry (failure policy step 1),
        # then each fallback in order (step 2), then OrchestratorError (step 3).
        provider_order = [task.provider, task.provider] + task.fallback_providers
        for provider_name in provider_order:
            result = self._attempt(task, provider_name, prompt)
            if result is not None:
                return result
        raise OrchestratorError(
            f"All providers exhausted for task_type={task.task_type}: "
            f"tried {task.provider} (x2) then fallbacks {task.fallback_providers}"
        )
