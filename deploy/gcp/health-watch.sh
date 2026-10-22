#!/bin/bash
# Bounded recovery of an unhealthy worker; does not restart other containers.
set -euo pipefail
umask 077
exec 9>/run/stockos-health.lock
flock -n 9 || exit 0
cd /var/lib/stockos/current
compose=(docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/gcp/compose.yaml)
container=$("${compose[@]}" ps -q app)
[[ -n "$container" ]] || { echo 'StockOS app container missing'; exit 1; }
health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container")
[[ "$health" == healthy || "$health" == starting ]] && exit 0
[[ "$health" == unhealthy ]] || { echo 'StockOS health unavailable'; exit 1; }
hour=$(date -u +%Y%m%d%H)
count_file=/run/stockos-health-restarts
previous_hour=none
count=0
if [[ -f "$count_file" ]]; then read -r previous_hour count < "$count_file"; fi
[[ "$previous_hour" == "$hour" ]] || count=0
[[ "$count" =~ ^[0-9]+$ ]] || exit 2
if (( count >= 3 )); then echo 'StockOS recovery limit reached; inspect worker failure'; exit 1; fi
printf '%s %s\n' "$hour" "$((count + 1))" > "$count_file"
"${compose[@]}" restart --timeout 45 app
