"""Frozen v3 SQLite NUMERIC -> decimal text migration, with semantic preservation proof.

No application ORM metadata is imported: future models cannot change this migration.
SQLite migrations use a dedicated connection with FK enforcement off while tables are
recreated; constraints are checked explicitly before completion. No precision is invented
for legacy values: preserve exactly the decimal values the old SQLAlchemy NUMERIC reader
returned. New writes no longer pass through binary floating point.
"""

import hashlib
import json
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.schema import CreateIndex, CreateTable, DropTable


def migrate_decimal_storage(connection):  # type: ignore[no-untyped-def]
    if connection.dialect.name != "sqlite":
        return []
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "SQLite storage migration requires a dedicated migration connection with foreign_keys off"
        )
    # pysqlite legacy transaction mode does not BEGIN for DDL/SELECT; explicitly
    # include every replacement table in the migration transaction.
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")
    metadata = sa.MetaData()
    metadata.reflect(bind=connection)
    audit = []
    # Freeze the list before adding temporary tables to the metadata.
    for original in list(metadata.sorted_tables):
        numeric = [c.name for c in original.c if isinstance(c.type, sa.Numeric)]
        if not numeric:
            continue
        before = [
            dict(r)
            for r in connection.execute(sa.select(original).order_by(original.c.id)).mappings()
        ]
        temporary = original.to_metadata(metadata, name="_qve_decimal_v3_" + original.name)
        for name in numeric:
            temporary.c[name].type = sa.String(128)
        connection.execute(CreateTable(temporary))
        if before:
            converted = [
                {k: format(v, "f") if k in numeric and v is not None else v for k, v in row.items()}
                for row in before
            ]
            connection.execute(temporary.insert(), converted)
        connection.execute(DropTable(original))
        quote = connection.dialect.identifier_preparer.quote
        connection.exec_driver_sql(
            f"ALTER TABLE {quote(temporary.name)} RENAME TO {quote(original.name)}"
        )
        for index in original.indexes:
            connection.execute(CreateIndex(index))
        reflected = sa.Table(original.name, sa.MetaData(), autoload_with=connection)
        after = [
            dict(r)
            for r in connection.execute(sa.select(reflected).order_by(reflected.c.id)).mappings()
        ]
        for row in after:
            for name in numeric:
                if row[name] is not None:
                    row[name] = Decimal(row[name])
        if before != after:
            raise RuntimeError(f"Numeric migration changed values in {original.name}")

        def fingerprint(rows):
            return hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str).encode()
            ).hexdigest()

        audit.append(
            {
                "table": original.name,
                "rows_verified": len(before),
                "before_hash": fingerprint(before),
                "after_hash": fingerprint(after),
            }
        )
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Foreign-key check failed after exact decimal migration")
    # Drop/recreate removed the row guards on the rebuilt tables. Reinstall those
    # originally specified by the frozen M1/M1.1 schema (including isolated labels).
    immutable = (
        "financial_facts",
        "forecast_snapshots",
        "assumption_sets",
        "quarterly_snapshots",
        "quant_features",
        "guidance_items",
        "segment_facts",
        "source_documents",
        "valuation_snapshots",
        "availability_evidence",
        "corporate_actions",
        "price_bases",
        "reconciliation_results",
        "quality_reviews",
        "future_outcomes",
    )
    tables = set(sa.inspect(connection).get_table_names())
    for name in immutable:
        if name not in tables:
            continue
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{name}_{action.lower()} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'immutable record'); END"
            )
    return audit
