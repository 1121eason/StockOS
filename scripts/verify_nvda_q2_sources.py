import argparse
import json
from pathlib import Path

from valuation_engine.ai.q2_source_evidence import verify


def main():
    parser = argparse.ArgumentParser(
        description="Verify current official text and conservative Q2 source-time bounds without models or database writes"
    )
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--browser-evidence", type=Path, required=True)
    parser.add_argument("--release-captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.preparation, args.raw_dir, args.browser_evidence, args.release_captures)
    with args.out.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "exact_text_matches",
                    "historical_minute_assertions",
                    "classification",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
