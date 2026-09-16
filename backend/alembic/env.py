"""Alembic environment (async) — Prompts/00_PREREQUISITE_Project_Setup.md §3.22.

* ``sqlalchemy.url`` comes from ``settings.PLATFORM_DATABASE_URL`` (falls back to ``DATABASE_URL``): migrations run as
  the BYPASSRLS platform role so every object is owned by it — the app role then works through grants and Row-Level
  Security applies to it as a non-owner, while cross-tenant maintenance (outbox relay, partition creation,
  ``search_documents`` refresh) runs unrestricted on the platform role (Phase 01 decision, PROGRESS.md 2026-09-16).
* ``target_metadata = Base.metadata`` with ``import app.models`` so autogenerate sees every model.
* ``include_object`` skips partition default children (``*_default``) and read-model views (``info.is_view``).
* ``Base.metadata.create_all`` is forbidden outside ``scripts/check_schema_drift.py``.
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.session import Base

import app.models  # noqa: E402,F401  (registers all model metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Escape % for ConfigParser interpolation; DDL is owned by the platform role (see module docstring)
config.set_main_option(
    "sqlalchemy.url", (settings.PLATFORM_DATABASE_URL or settings.DATABASE_URL).replace("%", "%%")
)

target_metadata = Base.metadata


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    if type_ == "table":
        if name and name.endswith("_default"):  # partition default children live only in the DDL
            return False
        if getattr(obj, "info", {}).get("is_view"):  # materialized-view mappings (Phase 35)
            return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Any) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
