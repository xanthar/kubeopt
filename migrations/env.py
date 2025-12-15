"""
Alembic migration environment configuration.

This module configures Alembic to use the Flask application's
SQLAlchemy database connection and models.
"""

import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


def get_engine():
    """Get the database engine from Flask-SQLAlchemy."""
    try:
        # This works with Flask-SQLAlchemy >= 3.0
        return current_app.extensions["sqlalchemy"].engine
    except (TypeError, KeyError):
        # Fallback for older versions
        return current_app.extensions["sqlalchemy"].db.engine


def get_engine_url():
    """Get the database URL from Flask configuration."""
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            "%", "%%"
        )
    except AttributeError:
        return str(get_engine().url).replace("%", "%%")


# Set SQLAlchemy URL from Flask config
config.set_main_option("sqlalchemy.url", get_engine_url())

# Import all models to ensure they're registered with SQLAlchemy
# This is necessary for autogenerate to detect model changes
target_db = current_app.extensions["sqlalchemy"]


def get_metadata():
    """Get metadata from Flask-SQLAlchemy."""
    if hasattr(target_db, "metadatas"):
        return target_db.metadatas.get(None)
    return target_db.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a
    connection with the context.
    """

    def process_revision_directives(context, revision, directives):
        """Prevent auto-generation of empty migrations."""
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
            **current_app.extensions["migrate"].configure_args,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
