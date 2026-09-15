from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from valuation_engine.db.schema import Base, LabelBase


def test_postgresql_ddl_compilation():
    for table in list(Base.metadata.sorted_tables) + list(LabelBase.metadata.sorted_tables):
        sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in sql
        if "available_at" in table.c:
            assert "TIMESTAMP WITH TIME ZONE" in sql


def test_postgresql_migrations_offline():
    for labels in (False, True):
        output = StringIO()
        cfg = Config("alembic.ini", output_buffer=output)
        cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://localhost/qve")
        cfg.attributes["labels"] = labels
        if labels:
            cfg.set_main_option("version_locations", str(Path("migrations/labels").resolve()))
        command.upgrade(cfg, "head", sql=True)
        sql = output.getvalue()
        assert "CREATE TABLE" in sql and "qve_reject_mutation" in sql
