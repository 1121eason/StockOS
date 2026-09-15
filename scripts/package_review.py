"""Package source and local research evidence separately, excluding credentials/caches."""

import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
artifacts = root / "artifacts"
artifacts.mkdir(exist_ok=True)
root_files = ("README.md", "pyproject.toml", "uv.lock", ".env.example", ".gitignore", "alembic.ini")
with zipfile.ZipFile(
    artifacts / "quarterly-valuation-engine-m1-source.zip", "w", zipfile.ZIP_DEFLATED
) as archive:
    paths = [root / name for name in root_files]
    for directory in ("src", "tests", "migrations", "docs", "scripts"):
        paths.extend((root / directory).rglob("*"))
    for path in sorted(paths):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            archive.write(path, "quarterly-valuation-engine/" + str(path.relative_to(root)))
with zipfile.ZipFile(artifacts / "nvda-m1-local-data.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    paths = list((root / "data/raw").glob("*"))
    names = (
        "README.md",
        "qve.db",
        "labels.db",
        "ir-manifest.json",
        "latest-quarter.json",
        "known-at-2023-05-25.json",
        "quarterly-coverage.json",
        "coverage.json",
        "validation.json",
        "manual-validation.json",
        "idempotency.json",
        "db-audit.json",
        "integrity-audit.json",
        "test-results.txt",
        "forecast-replay.json",
        "forecast-current.json",
        "valuation.json",
    )
    paths.extend(root / "data" / name for name in names)
    for path in sorted(paths):
        if path.is_file():
            archive.write(path, "quarterly-valuation-engine/" + str(path.relative_to(root)))
for path in sorted(artifacts.glob("*.zip")):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        print(
            f"{path.name}: {len(archive.infolist())} entries, {path.stat().st_size} bytes, integrity OK"
        )
