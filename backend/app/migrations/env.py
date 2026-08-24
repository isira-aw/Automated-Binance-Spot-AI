"""Alembic environment.

The database URL always comes from application settings, so migrations use the
same configuration as the app and no credentials live in ``alembic.ini``.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models package registers every table on Base.metadata.
import app.models  # noqa: F401
from app.config import get_settings
from app.database.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# The URL is deliberately NOT written back with ``config.set_main_option``.
# Credentials are percent-encoded, and alembic stores main options in a
# ConfigParser that treats ``%`` as interpolation syntax -- a password
# containing ``%`` (or any encoded character) would raise ValueError before a
# connection is ever attempted.  It is passed straight to the engine instead.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database.sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = dict(config.get_section(config.config_ini_section, {}))
    section["sqlalchemy.url"] = settings.database.sync_url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
