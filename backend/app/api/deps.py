from functools import lru_cache
from typing import Generator
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory


@lru_cache
def _get_session_factory():
    engine = make_engine(get_settings().database_url)
    return make_session_factory(engine)


def get_db() -> Generator[Session, None, None]:
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()
