"""Restore final PostgreSQL exports into temporary databases and verify their contents."""

import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
BASE = "postgresql://postgres@127.0.0.1:55439/"
CONTAINER = "stockos-m11-postgres"


def snapshot(name):
    with psycopg.connect(BASE + name) as db:
        db.execute("SET TIME ZONE 'UTC'")
        tables = db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ).fetchall()
        rows = {}
        for (table,) in tables:
            values = db.execute(
                sql.SQL("SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text").format(
                    sql.Identifier("public", table)
                )
            ).fetchall()
            rows[table] = {
                "count": len(values),
                "sha256": hashlib.sha256(json.dumps(values).encode()).hexdigest(),
            }
        triggers = db.execute(
            "SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1"
        ).fetchall()
    return {"tables": rows, "triggers": [t[0] for t in triggers]}


def main():
    result = {}
    with psycopg.connect(BASE + "postgres", autocommit=True) as admin:
        for original in ("qve_verified", "qve_labels"):
            restored = "m11_restore_" + uuid.uuid4().hex
            archive = ROOT / "data/m11/postgresql" / f"{original}.dump"
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored)))
            try:
                with archive.open("rb") as data:
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            "-i",
                            CONTAINER,
                            "pg_restore",
                            "-U",
                            "postgres",
                            "--exit-on-error",
                            "-d",
                            restored,
                        ],
                        stdin=data,
                        check=True,
                    )
                before, after = snapshot(original), snapshot(restored)
                assert before == after, f"Restored contents differ for {original}"
                result[original] = {
                    "dump_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "restored_all_tables_equal": True,
                    "restored_trigger_definitions_equal": True,
                    **after,
                }
            finally:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restored)))
    destination = ROOT / "data/m11/postgresql/dump-restore-validation.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print("Both exports restored successfully; all table hashes and trigger definitions match.")


if __name__ == "__main__":
    main()
