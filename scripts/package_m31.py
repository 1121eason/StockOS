"""Separate M3.1 delivery archives, preserving every accepted M1/M2 archive."""

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
    with zipfile.ZipFile(OUTPUT / "nvda-m3-review-data.zip") as archive:
        manifest = json.loads(
            archive.read("quarterly-valuation-engine/nvda-m3-review-data-files.json")
        )
    data = [ROOT / name for name in manifest]
    data.extend(
        ROOT / "data/m31" / name
        for name in (
            "policy-freeze.json",
            "test-results.txt",
            "lint.txt",
            "format.txt",
            "type-check.txt",
            "received-request.txt",
        )
    )
    for folder in ("data/m31/report", "data/m31/postgresql"):
        data.extend((ROOT / folder).glob("*.json"))
    data.append(ROOT / "data/m31/postgresql/test-results.txt")
    result = {
        "quarterly-valuation-engine-m31-source.zip": package(
            "quarterly-valuation-engine-m31-source.zip", source
        ),
        "nvda-m31-review-data.zip": package("nvda-m31-review-data.zip", data),
    }
    (OUTPUT / "m31-checksums.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
