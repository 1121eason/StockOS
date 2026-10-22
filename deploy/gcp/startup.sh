#!/bin/bash
# GCE root bootstrap. No xtrace: .env contains authentication material.
set -euo pipefail
umask 077
meta() { curl --fail --silent --show-error --retry 3 -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
project=$(meta stockos-project)
[[ "$project" == stockos-eason-20261022 ]] || exit 10
bundle=$(meta stockos-bundle)
bundle_hash=$(meta stockos-bundle-sha256)
secret=$(meta stockos-environment-secret)
secret_version=$(meta stockos-secret-version)
[[ "$bundle_hash" =~ ^[0-9a-f]{64}$ ]] || exit 11
[[ "$secret_version" =~ ^[1-9][0-9]*$ ]] || exit 12

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg python3
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable' > /etc/apt/sources.list.d/docker.list
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor --yes -o /etc/apt/keyrings/google-cloud.gpg
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/google-cloud.gpg] https://packages.cloud.google.com/apt cloud-sdk main' > /etc/apt/sources.list.d/google-cloud-sdk.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin google-cloud-cli

disk=/dev/disk/by-id/google-stockos-research
for attempt in $(seq 1 30); do [[ -b "$disk" ]] && break; sleep 1; done
[[ -b "$disk" ]] || exit 13
fs_type=$(blkid -o value -s TYPE "$disk" || true)
if [[ -z "$fs_type" ]]; then
  # Only the newly created, empty dedicated data disk may be formatted.
  [[ -z "$(wipefs --no-act --noheadings --output TYPE "$disk")" ]] || exit 14
  mkfs.ext4 -F "$disk"
elif [[ "$fs_type" != ext4 ]]; then
  exit 15
fi
mkdir -p /srv/stockos
uuid=$(blkid -o value -s UUID "$disk")
if ! grep -q "^UUID=$uuid " /etc/fstab; then
  printf 'UUID=%s /srv/stockos ext4 defaults 0 2\n' "$uuid" >> /etc/fstab
fi
mountpoint -q /srv/stockos || mount /srv/stockos
[[ "$(findmnt -n -o UUID /srv/stockos)" == "$uuid" ]] || exit 16
install -d -m 0700 /srv/stockos/tls /srv/stockos/caddy_config
install -d -m 0700 -o 10001 -g 10001 /srv/stockos/research

release=/var/lib/stockos/releases/$bundle_hash
if [[ ! -d "$release" ]]; then
  install -d -m 0755 /var/lib/stockos/releases
  stage=$(mktemp -d /var/lib/stockos/releases/.incoming-XXXXXXXX)
  trap 'rm -rf -- "$stage"' EXIT
  gcloud storage cp "$bundle" "$stage/bundle.tar.gz" --project="$project" --quiet
  printf '%s  %s\n' "$bundle_hash" "$stage/bundle.tar.gz" | sha256sum --check --status
  python3 - "$stage" <<'PY'
import pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
with tarfile.open(root / "bundle.tar.gz") as archive:
    members = archive.getmembers()
    names = set()
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or not path.parts
                or path.parts[0] not in {"deploy", "seed"}
                or member.name in names or not (member.isfile() or member.isdir())):
            raise ValueError("Unsafe deployment bundle member")
        names.add(member.name)
    if sum(m.size for m in members) > 4 * 1024**3:
        raise ValueError("Deployment bundle exceeds 4 GiB")
    archive.extractall(root / "release", members=members, filter="data")
PY
  test -f "$stage/release/seed/seed-manifest.json"
  test -f "$stage/release/deploy/gcp/backup.sh"
  mv "$stage/release" "$release"
fi
# Root can operate the release; the non-root container can read its seed.
chown -R root:10001 "$release"
find "$release" -type d -exec chmod 0750 {} +
find "$release" -type f -exec chmod 0640 {} +
gcloud secrets versions access "$secret_version" --secret="$secret" --project="$project" > "$release/deploy/.env"
chmod 0600 "$release/deploy/.env"
gcloud auth configure-docker asia-east1-docker.pkg.dev --quiet
ln -sfn "$release" /var/lib/stockos/current
cd /var/lib/stockos/current
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/gcp/compose.yaml config --format json | python3 -c '
import json, re, sys
c = json.load(sys.stdin)
app, gateway = c["services"]["app"], c["services"]["gateway"]
assert re.fullmatch(r"asia-east1-docker[.]pkg[.]dev/stockos-eason-20261022/stockos/[a-z0-9_-]+@sha256:[0-9a-f]{64}", app["image"])
assert not app.get("ports")
assert app["environment"]["STOCKOS_PUBLIC_ORIGIN"] == "https://stockos.easonpro.com"
assert gateway["environment"]["STOCKOS_DOMAIN"] == "stockos.easonpro.com"
assert gateway["environment"]["STOCKOS_PASSWORD_HASH"].startswith(("$2a$", "$2b$", "$2y$"))
assert app["environment"]["SEC_USER_AGENT"].strip() and "@" in app["environment"]["SEC_USER_AGENT"]
'

install -m 0750 "$release/deploy/gcp/backup.sh" /usr/local/sbin/stockos-backup
install -m 0750 "$release/deploy/gcp/health-watch.sh" /usr/local/sbin/stockos-health-watch
install -m 0644 "$release/deploy/gcp/stockos.service" /etc/systemd/system/stockos.service
install -m 0644 "$release/deploy/gcp/stockos-backup.service" /etc/systemd/system/stockos-backup.service
install -m 0644 "$release/deploy/gcp/stockos-backup.timer" /etc/systemd/system/stockos-backup.timer
install -m 0644 "$release/deploy/gcp/stockos-health.service" /etc/systemd/system/stockos-health.service
install -m 0644 "$release/deploy/gcp/stockos-health.timer" /etc/systemd/system/stockos-health.timer
systemctl daemon-reload
systemctl enable docker stockos stockos-backup.timer stockos-health.timer
systemctl restart stockos
systemctl start stockos-backup.timer stockos-health.timer
