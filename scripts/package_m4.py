"""Separate M4 delivery archives, preserving every accepted M1/M2 archive."""

import json
import zipfile

from package_m11 import OUTPUT, ROOT, package


def main():
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
    with zipfile.ZipFile(OUTPUT / "nvda-m31-review-data.zip") as archive:
        manifest = json.loads(
            archive.read("quarterly-valuation-engine/nvda-m31-review-data-files.json")
        )
    data = [ROOT / name for name in manifest]
    data.extend(
        ROOT / "data/m4" / name
        for name in (
            "policy-freeze.json",
            "test-results.txt",
            "lint.txt",
            "format.txt",
            "type-check.txt",
            "received-request.txt",
        )
    )
    for folder in ("data/m4/report", "data/m4/postgresql"):
        data.extend((ROOT / folder).glob("*.json"))
    data.append(ROOT / "data/m4/postgresql/test-results.txt")
    result = {
        "quarterly-valuation-engine-m4-source.zip": package(
            "quarterly-valuation-engine-m4-source.zip", source
        ),
        "nvda-m4-review-data.zip": package("nvda-m4-review-data.zip", data),
    }
    (OUTPUT / "m4-checksums.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
