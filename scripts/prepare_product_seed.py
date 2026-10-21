#!/usr/bin/env python3
"""Create a private deployment seed; does not upload anything."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valuation_engine.research.deployment import prepare_seed  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-db", required=True, type=Path)
parser.add_argument("--raw-dir", required=True, type=Path)
parser.add_argument("--out", required=True, type=Path)
args = parser.parse_args()
result = prepare_seed(args.source_db, args.raw_dir, args.out)
print(json.dumps({"version": result["version"], "quarter": result["current_quarter"],
                  "verified_sources": len(result["source_hashes"]), "uploaded": False}))
