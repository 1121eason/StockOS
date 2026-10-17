"""Offline import/list/show CLI for the isolated research workspace database."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from valuation_engine.research.workspace import (  # noqa: E402
    import_bundle,
    list_runs,
    load_run,
    parse_bundle_json,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Explicit isolated SQLite file; never the formal application database",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="Validate and append one offline JSON bundle")
    importer.add_argument("bundle", type=Path)
    commands.add_parser("list", help="List verified research runs")
    show = commands.add_parser("show", help="Show one verified research run")
    show.add_argument("run_id")
    args = parser.parse_args(argv)
    result: dict | list[dict]
    try:
        if args.command == "import":
            bundle = parse_bundle_json(args.bundle.read_text(encoding="utf-8"))
            result = import_bundle(args.db, bundle)
        elif args.command == "list":
            result = list_runs(args.db)
        else:
            result = load_run(args.db, args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"Research workspace error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
