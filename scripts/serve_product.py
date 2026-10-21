#!/usr/bin/env python3
"""Container entrypoint. Seed is read-only; operational state must be persistent."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from valuation_engine.research.deployment import verify_seed  # noqa: E402

verify_seed(Path("/seed"))
origin = os.environ.get("STOCKOS_PUBLIC_ORIGIN")
if not origin:
    raise SystemExit("STOCKOS_PUBLIC_ORIGIN is required; use the authenticated HTTPS gateway")
sys.argv = [
    "serve_ui.py", "--port", "8511", "--bind", "0.0.0.0", "--behind-auth-proxy",
    "--public-origin", origin, "--deployment", os.environ.get("STOCKOS_DEPLOYMENT", "cloud"),
    "--automation", "--source-db", "/seed/qve.db", "--raw-dir", "/seed/raw",
    "--product-store", "/state",
]
from serve_ui import main  # noqa: E402

main()
