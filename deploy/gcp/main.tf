terraform {
  required_version = ">= 1.6.0, < 2.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.8.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = "asia-east1"
  zone    = "asia-east1-b"
}

locals {
  region = "asia-east1"
  labels = { application = "stockos", scope = "nvda", release = "r1-quant" }
}

resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com", "artifactregistry.googleapis.com",
    "storage.googleapis.com", "secretmanager.googleapis.com", "iam.googleapis.com"
  ])
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  account_id   = "stockos-runtime"
  display_name = "StockOS NVDA runtime"
  depends_on   = [google_project_service.required]
}

resource "google_artifact_registry_repository" "app" {
  location      = local.region
  repository_id = "stockos"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.required]
  lifecycle { prevent_destroy = true }
}

resource "google_artifact_registry_repository_iam_member" "reader" {
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "seed" {
  name                        = "${var.project_id}-private-seed"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  versioning { enabled = true }
  soft_delete_policy { retention_duration_seconds = 604800 }
  lifecycle { prevent_destroy = true }
}

resource "google_storage_bucket" "backup" {
  name                        = "${var.project_id}-private-backup"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  soft_delete_policy { retention_duration_seconds = 604800 }
  lifecycle_rule {
    condition { age = 30 }
    action { type = "Delete" }
  }
  lifecycle { prevent_destroy = true }
}

resource "google_storage_bucket_iam_member" "seed_reader" {
  bucket = google_storage_bucket.seed.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "backup_creator" {
  bucket = google_storage_bucket.backup.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret" "environment" {
  secret_id = "stockos-runtime-environment"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
  lifecycle { prevent_destroy = true }
}

resource "google_secret_manager_secret_iam_member" "reader" {
  secret_id = google_secret_manager_secret.environment.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_compute_network" "stockos" {
  name                    = "stockos"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "stockos" {
  name                     = "stockos-taiwan"
  ip_cidr_range            = "10.42.0.0/24"
  region                   = local.region
  network                  = google_compute_network.stockos.id
  private_ip_google_access = true
}

resource "google_compute_firewall" "web" {
  name          = "stockos-authenticated-web"
  network       = google_compute_network.stockos.name
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["stockos-web"]
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "iap" {
  name          = "stockos-ssh-through-iap"
  network       = google_compute_network.stockos.name
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["stockos-web"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_disk" "data" {
  count  = var.enable_runtime ? 1 : 0
  name   = "stockos-research"
  type   = "pd-standard"
  size   = 20
  zone   = "asia-east1-b"
  labels = local.labels
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}

resource "google_compute_address" "web" {
  count      = var.enable_runtime ? 1 : 0
  name       = "stockos-web"
  region     = local.region
  depends_on = [google_project_service.required]
}

resource "google_compute_instance" "app" {
  count               = var.enable_runtime ? 1 : 0
  name                = "stockos-nvda"
  machine_type        = "e2-small"
  zone                = "asia-east1-b"
  deletion_protection = true
  labels              = local.labels
  tags                = ["stockos-web"]
  boot_disk {
    initialize_params {
      image = "projects/debian-cloud/global/images/family/debian-12"
      type  = "pd-standard"
      size  = 20
    }
  }
  attached_disk {
    source      = google_compute_disk.data[0].id
    device_name = "stockos-research"
  }
  network_interface {
    subnetwork = google_compute_subnetwork.stockos.id
    access_config { nat_ip = google_compute_address.web[0].address }
  }
  service_account {
    email  = google_service_account.runtime.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  metadata = {
    enable-oslogin             = "TRUE"
    block-project-ssh-keys     = "TRUE"
    stockos-project            = var.project_id
    stockos-bundle             = "gs://${google_storage_bucket.seed.name}/${var.bundle_object}"
    stockos-bundle-sha256      = var.bundle_sha256
    stockos-environment-secret = google_secret_manager_secret.environment.secret_id
    stockos-secret-version     = var.environment_secret_version
    stockos-backup-bucket      = google_storage_bucket.backup.name
  }
  metadata_startup_script = file("${path.module}/startup.sh")
  depends_on = [
    google_artifact_registry_repository_iam_member.reader,
    google_storage_bucket_iam_member.seed_reader,
    google_storage_bucket_iam_member.backup_creator,
    google_secret_manager_secret_iam_member.reader
  ]
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = var.estimated_monthly_twd > 0 && var.estimated_monthly_twd <= 800
      error_message = "A reviewed total estimate <= NT$800 is required, leaving headroom within NT$1,000."
    }
    precondition {
      condition     = can(regex("^[0-9a-f]{64}$", var.bundle_sha256)) && can(regex("^[1-9][0-9]*$", var.environment_secret_version)) && can(regex("^[a-zA-Z0-9/_-]+[.]tar[.]gz$", var.bundle_object))
      error_message = "An immutable bundle hash/object and numeric secret version are required."
    }
  }
}

output "private_seed_bucket" { value = google_storage_bucket.seed.name }
output "private_backup_bucket" { value = google_storage_bucket.backup.name }
output "image_repository" { value = "${local.region}-docker.pkg.dev/${var.project_id}/stockos" }
output "public_ip" { value = try(google_compute_address.web[0].address, null) }
