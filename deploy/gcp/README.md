# StockOS GCP R1

Scope: `stockos-eason-20261022`, NVDA Quant only, `stockos.easonpro.com`, NT$1,000/month. This directory is prepared infrastructure, not evidence of deployment. Current receipts and blockers: [cloud status](../../docs/product/CLOUD_R1_PLAN_2026_10_22.md).

## Resources and permissions

One e2-small in Taiwan, 20 GiB boot disk and a separate protected 20 GiB research disk. The app keeps its existing Compose contract. Private Artifact Registry, seed bucket and backup bucket use one dedicated runtime service account: registry reader, seed object viewer, backup object creator, and access to one Secret Manager secret. It cannot delete backups or administer the project. No service-account key is created. The seed and backups have public access prevention and uniform access control.

The VPC exposes only Caddy ports 80/443. SSH is limited to the IAP range and OS Login. The app has no host port. Password material lives in a numbered Secret Manager version and a root-only host file, never Terraform state, VM metadata, Git or logs. Startup rejects a non-StockOS image, mutable image tag, wrong hostname, exposed app port or absent bcrypt hash. The reviewed image and private bundle must be pinned independently.

The backup bucket removes objects after 30 days with seven-day soft deletion. The daily job performs a consistent snapshot and local semantic restore, then uploads a unique archive plus SHA-256. Upload success is explicitly **not remote restore success**. The VM can only create backups; an owner/operator downloads one into an independent environment for the acceptance test. No destructive restore or automatic volume replacement is included.

## Before applying

1. Authenticate the personal Google account that owns this project in a separate gcloud configuration. Do not reuse the current CRM project or change its configuration. Confirm `gcloud projects describe stockos-eason-20261022` using that account. Terraform must use the same explicit identity (short-lived access token via its standard environment variable, or a dedicated ADC configuration); never store the token in a file or plan.
2. Confirm the GCP service terms when enabling Compute Engine, and verify necessary API permissions. Do not treat an enabled API as a running VM.
3. Review the monthly estimate in TWD including Taiwan VM, two disks, IPv4, registry, backups, downloads, tax and headroom. Budget alerts at 50/80/100% already exist; these are not a VM hard cap. Runtime creation requires a reviewed estimate <= NT$800, leaving NT$200 headroom. No estimate has yet been accepted.
4. Verify DNS ownership before pointing `stockos.easonpro.com` to the reserved IP. Avoid changing the domain's other records.

## Two-stage provisioning

Run Terraform only with the explicit StockOS identity. The existing project and browser-created budget are intentionally outside this configuration.

```sh
terraform init
terraform validate
terraform plan -out=foundation.tfplan
terraform apply foundation.tfplan
```

Default `enable_runtime=false` creates only the private repository/buckets, secret metadata, dedicated runtime identity and VPC/firewalls. It does not create a VM, disk, public IP or secret value. Apply requires reviewing the plan and credentials; there is no auto-apply script.

Build the accepted source as `linux/amd64`, push to the private repository, and record its digest. Verify the real FY2027-Q2 seed using `verify_seed`; package only `deploy/compose.yaml`, `deploy/Caddyfile`, the runtime files in this directory, and the manifest-enumerated seed DB/raw files. Exclude `.env`, Terraform state, local credentials, reviewer packets and unrelated files. Upload the bundle to the private seed bucket under its hash. Keep the local bundle receipt private.

Create the numbered `stockos-runtime-environment` secret version outside Terraform. Its contents follow `deploy/.env.example`, with:

- `STOCKOS_IMAGE=asia-east1-docker.pkg.dev/stockos-eason-20261022/stockos/app@sha256:...`
- `STOCKOS_DOMAIN=stockos.easonpro.com`
- `STOCKOS_SEED_DIR=/var/lib/stockos/current/seed`
- a project-specific login and bcrypt password hash; retain the password privately for the owner;
- the approved SEC project/contact identity.

Create an untracked `.tfvars` file with `enable_runtime=true`, the reviewed `estimated_monthly_twd`, immutable `bundle_object`, `bundle_sha256` and numeric `environment_secret_version`. Review the second plan before applying. The VM then mounts its separate disk, verifies the bundle, retrieves only that secret version, checks configuration, and starts Compose plus the health/backup timers. The startup script is scoped to the newly provisioned Debian 12 VM; do not run it on a workstation or existing server.

## Acceptance and recovery

Record actual image/base-image digests, bundle/seed hashes, VM identity, time and source versions. Test external 401 without login, 200 after login, private/import routes 404, foreign Origin update 403, trusted update queue, successful financial rebuild, retained old research on source failure, quote timestamps, reboot persistence and a downloaded remote backup restored into a **new** directory. Never use `down -v` or overwrite the running state to test recovery.

The health timer restarts only an unhealthy StockOS app, at most three times per UTC hour. Missing containers or exhausted recovery are failures requiring inspection. Docker/systemd liveness is not financial correctness. Failed timer units currently remain in the host journal; external notifications still need delivery acceptance.

The service can start on boot without the personal computer. Evidence must demonstrate a later cloud job timestamp while the local service is stopped; only a real observed computer shutdown can establish that literal user scenario. Future-quarter publication remains a separate observation from the existing FY2027-Q2 replay.

These files do not implement a 12-month price, current-quarter AI, event interpretation, external notifications, high availability or multi-stock research. See the corresponding product gates rather than inferring completion from infrastructure validation.
