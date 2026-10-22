"""Produce a separate, source-bound editorial revision without model or DB calls."""

import argparse
import json
from pathlib import Path

from valuation_engine.ai.review_revision import prepare_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--quant-context", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_revision(args.packet, args.quant_context, args.out), indent=2))


if __name__ == "__main__":
    main()
