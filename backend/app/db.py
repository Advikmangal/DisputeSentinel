from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_settings


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def database_url():
    value = get_settings().database_url.get_secret_value()
    if not value or "replace-" in value:
        raise ValueError("Configure DATABASE_URL for PostgreSQL")
    url = make_url(value)
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use PostgreSQL with psycopg")
    return url


@lru_cache
def get_engine():
    return create_engine(database_url(), pool_pre_ping=True, hide_parameters=True,
                         pool_timeout=5, connect_args={"connect_timeout": 5, "options": "-c statement_timeout=15000"})


def get_db():
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session

