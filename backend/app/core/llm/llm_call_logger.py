import json
from sqlalchemy.orm import Session
from app.models.db_models import LLMCall
from app.core.config import get_settings


def _known_secrets() -> list[str]:
    settings = get_settings()
    return [value for value in (settings.nvidia_api_key, settings.gemini_api_key) if value]


def _sanitize_value(value, secrets: list[str]):
    if value is None or not secrets:
        return value
    if isinstance(value, str):
        text = value
        for secret in secrets:
            text = text.replace(secret, "***REDACTED***")
        return text
    text = json.dumps(value)
    for secret in secrets:
        text = text.replace(secret, "***REDACTED***")
    return json.loads(text)


def make_db_logger(db: Session, session_id: int | None = None):
    def log(record: dict) -> None:
        secrets = _known_secrets()
        sanitized_response = _sanitize_value(record.get("response_payload"), secrets)
        sanitized_request = _sanitize_value(record.get("request_payload"), secrets)

        db.add(LLMCall(
            session_id=session_id,
            prompt_version_id=record.get("prompt_version_id"),
            provider=record["provider"],
            model=record["model"],
            task_type=record["task_type"],
            temperature=record.get("temperature"),
            request_payload=sanitized_request,
            response_payload={"text": sanitized_response} if sanitized_response else None,
            validated=record["validated"],
            latency_ms=record.get("latency_ms"),
        ))
        db.commit()

    return log
