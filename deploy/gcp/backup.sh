#!/bin/bash
set -euo pipefail
umask 077
exec 9>/run/stockos-backup.lock
flock -n 9 || exit 0
cd /var/lib/stockos/current
bucket=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/stockos-backup-bucket)
[[ "$bucket" == stockos-eason-20261022-private-backup ]] || exit 10
stage=$(mktemp -d /srv/stockos/.backup-XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
chown 10001:10001 "$stage"
compose=(docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/gcp/compose.yaml)
"${compose[@]}" run --rm --no-deps -T -v "$stage:/backup" app \
  python scripts/product_backup.py backup --source /state --out /backup/state
# Also exercise semantic restore locally before the remote upload.
"${compose[@]}" run --rm --no-deps -T -v "$stage:/backup" app \
  python scripts/product_backup.py restore --source /backup/state --out /backup/restored
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)
tar -C "$stage" -czf "$stage/$stamp.tar.gz" state
sha256sum "$stage/$stamp.tar.gz" | cut -d ' ' -f 1 > "$stage/$stamp.sha256"
gcloud storage cp "$stage/$stamp.tar.gz" "$stage/$stamp.sha256" "gs://$bucket/daily/" \
  --project=stockos-eason-20261022 --quiet
printf '{"status":"uploaded","object":"daily/%s.tar.gz","remote_restore_verified":false}\n' "$stamp"
