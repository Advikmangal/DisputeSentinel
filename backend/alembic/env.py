from alembic import context
from sqlalchemy import create_engine, pool

from app.db import Base, database_url
from app import models  # noqa: F401: register all tables

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url(), poolclass=pool.NullPool, hide_parameters=True,
                           connect_args={"connect_timeout": 10, "options": "-c lock_timeout=30000 -c statement_timeout=120000"})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
