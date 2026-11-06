#!/bin/zsh
set -eu

# Reproduce without overwriting the reviewed original outputs.
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_root="$(cd -- "$source_dir/../../.." && pwd)"
reviewed_run="$(dirname -- "$source_dir")"
replay_dir="$(mktemp -d "$project_root/runs/nvda-reproduce-XXXXXX")"
mkdir -p "$replay_dir/source_only"
cp "$source_dir/config.json" "$replay_dir/source_only/config.json"
ln -s "$reviewed_run/backend" "$replay_dir/backend"
PYTHONDONTWRITEBYTECODE=1 "$project_root/.venv/bin/python" "$source_dir/run_nvda.py" --project "$project_root" --run-dir "$replay_dir"
PYTHONDONTWRITEBYTECODE=1 "$project_root/.venv/bin/python" "$source_dir/verify_results.py" "$replay_dir/outputs"
printf '\nFresh local reproduction directory: %s\n' "$replay_dir"
