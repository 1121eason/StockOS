#!/usr/bin/env python3
"""Back up a live product store or restore to a NEW directory; never overwrite."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valuation_engine.research.state_archive import backup_state, restore_state  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=("backup", "restore"))
parser.add_argument("--source", required=True, type=Path)
parser.add_argument("--out", required=True, type=Path)
args = parser.parse_args()
result = (backup_state if args.action == "backup" else restore_state)(args.source, args.out)
print(json.dumps({"action": args.action, "version": result["version"],
                  "verified_sources": len(result["source_hashes"]), "uploaded": False}))
