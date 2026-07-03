from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import get_settings

from sqlalchemy import event


def _enable_sqlite_foreign_keys(engine):
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def make_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    engine_kwargs = {}
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # A plain in-memory sqlite engine defaults to SingletonThreadPool,
            # which hands out a *new* (empty) database per thread. FastAPI's
            # TestClient executes requests on a different thread than the
            # fixture that creates the schema, so without StaticPool every
            # request would see "no such table" errors. StaticPool keeps a
            # single shared connection across all threads.
            engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **engine_kwargs)
    _enable_sqlite_foreign_keys(engine)
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
