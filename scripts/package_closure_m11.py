"""Package final-closure source/evidence separately from the retained M1.1 archives."""

import hashlib
import json
import sqlite3

from package_m11 import OUTPUT, ROOT, package

source = [
    ROOT / name
    for name in (
        "README.md",
        "pyproject.toml",
        "uv.lock",
        ".env.example",
        ".gitignore",
        "alembic.ini",
    )
]
for folder in ("src", "tests", "migrations", "docs", "scripts"):
    source.extend(
        p
        for p in (ROOT / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
data = [
    ROOT / "data" / name
    for name in (
        "README.md",
        "qve.db",
        "labels.db",
        "ir-manifest.json",
        "m11/timestamps-manifest.json",
        "m11/splits-manifest.json",
        "m11/price-manifest.json",
        "m11/decimal-migration-audit.json",
        "m11/backend-parity.json",
        "m11-closure/test-results.txt",
        "m11-closure/lint.txt",
        "m11-closure/type-check.txt",
        "m11-closure/idempotency.json",
        "m11-closure/pm-policy-review.json",
        "m11-closure/changed-source-files.json",
        "m11-closure/preservation-audit.json",
        "m11-closure/postgresql/test-results.txt",
    )
]
with sqlite3.connect(f"file:{ROOT / 'data/qve.db'}?mode=ro", uri=True) as db:
    for (digest,) in db.execute("SELECT DISTINCT content_hash FROM source_documents"):
        path = ROOT / "data/raw" / digest
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        data.append(path)
for name in ("timestamps", "splits", "price"):
    manifest = json.loads((ROOT / f"data/m11/{name}-manifest.json").read_text())
    for row in manifest if isinstance(manifest, list) else [manifest]:
        data.append(ROOT / row["path"])
data.extend((ROOT / "data/m11/report").glob("*.json"))
for folder in ("report", "report-second", "postgresql", "postgresql-second"):
    data.extend((ROOT / "data/m11-closure" / folder).glob("*.json"))
results = {
    "quarterly-valuation-engine-m11-closure-source.zip": package(
        "quarterly-valuation-engine-m11-closure-source.zip", source
    ),
    "nvda-m11-closure-review-data.zip": package("nvda-m11-closure-review-data.zip", data),
}
(OUTPUT / "m11-closure-checksums.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
