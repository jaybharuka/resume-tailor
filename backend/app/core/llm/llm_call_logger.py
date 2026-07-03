from sqlalchemy.orm import Session
from app.models.db_models import LLMCall


def make_db_logger(db: Session, session_id: int | None = None):
    def log(record: dict) -> None:
        db.add(LLMCall(
            session_id=session_id,
            prompt_version_id=record.get("prompt_version_id"),
            provider=record["provider"],
            model=record["model"],
            task_type=record["task_type"],
            temperature=record.get("temperature"),
            request_payload=record.get("request_payload"),
            response_payload={"text": record["response_payload"]} if record.get("response_payload") else None,
            validated=record["validated"],
            latency_ms=record.get("latency_ms"),
        ))
        db.commit()

    return log
