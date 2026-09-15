"""Package M2 code and frozen review evidence; preserve all earlier milestone archives."""

import json
import sqlite3

from package_m11 import OUTPUT, ROOT, package, sha


def main():
    OUTPUT.mkdir(exist_ok=True)
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
    for directory in ("src", "tests", "migrations", "docs", "scripts"):
        source.extend(
            p
            for p in (ROOT / directory).rglob("*")
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
            "m2/policy-freeze.json",
            "m2/preservation.json",
            "m2/backend-parity.json",
            "m2/test-results.txt",
            "m2/lint.txt",
            "m2/format.txt",
            "m2/type-check.txt",
        )
    ]
    with sqlite3.connect(f"file:{ROOT / 'data/qve.db'}?mode=ro", uri=True) as db:
        for (digest,) in db.execute("SELECT DISTINCT content_hash FROM source_documents"):
            path = ROOT / "data/raw" / digest
            assert sha(path.read_bytes()) == digest
            data.append(path)
    data.extend(p for p in (ROOT / "data/m11/external").rglob("*") if p.is_file())
    for directory in ("data/m2/report", "data/m2/postgresql"):
        data.extend((ROOT / directory).glob("*.json"))
    data.append(ROOT / "data/m2/postgresql/test-results.txt")
    result = {
        "quarterly-valuation-engine-m2-source.zip": package(
            "quarterly-valuation-engine-m2-source.zip", source
        ),
        "nvda-m2-review-data.zip": package("nvda-m2-review-data.zip", data),
    }
    (OUTPUT / "m2-checksums.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
