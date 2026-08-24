terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region — must be one of us-west1, us-central1, us-east1 for the always-free e2-micro"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "owner_ip" {
  description = "Your home/office IPv4 — used for the SSH allowlist. Residential IPs drift; see owner_cidr_bits."
  type        = string
}

variable "owner_cidr_bits" {
  description = <<-EOT
    Prefix length for the SSH allowlist. 32 pins one exact address (tightest,
    but breaks whenever your ISP reassigns). 24 allows your ISP's local /24,
    which survives drift at the cost of a wider allowlist — acceptable given
    SSH is key-only with no password auth.
  EOT
  type        = number
  default     = 32
}

variable "ssh_user" {
  description = "Linux username to create on the VM and attach the SSH key to."
  type        = string
  default     = "fwdev"
}

variable "ssh_public_key_path" {
  description = "Public key granted SSH access. Must be the pair gcloud/ssh actually offers."
  type        = string
  default     = "~/.ssh/google_compute_engine.pub"
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_compute_address" "norman" {
  name = "norman-static-ip"
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-norman-artifacts"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  versioning { enabled = true }

  # Postgres dumps accumulate; 5 GB is the always-free ceiling. Expire old
  # objects so backups can't silently grow into a billable bucket.
  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }

  # Versioning is on, so deleted/overwritten objects linger as noncurrent
  # versions. Reap those faster than live ones.
  lifecycle_rule {
    condition {
      age                = 30
      with_state         = "ARCHIVED"
      num_newer_versions = 3
    }
    action { type = "Delete" }
  }
}

# The VM writes nightly Postgres dumps here. The default Compute Engine
# service account only carries `devstorage.read_only` in its default scopes,
# so without this the VM can list the bucket but not write to it.
#
# Granting `cloud-platform` scope on the instance + a narrow IAM role here is
# the modern pattern: scopes are a legacy coarse filter, IAM is the real gate.
# Net effect is "write objects in this one bucket", nothing else.
data "google_compute_default_service_account" "default" {}

resource "google_storage_bucket_iam_member" "vm_artifacts_writer" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${data.google_compute_default_service_account.default.email}"
}

resource "google_compute_firewall" "ssh" {
  name    = "norman-ssh"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  # cidrhost(..., 0) normalises to the network address, so owner_cidr_bits = 24
  # yields 212.11.95.0/24 rather than the non-canonical 212.11.95.6/24 that
  # GCP would reject.
  source_ranges = ["${cidrhost("${var.owner_ip}/${var.owner_cidr_bits}", 0)}/${var.owner_cidr_bits}"]
  target_tags   = ["norman"]
}

resource "google_compute_firewall" "public" {
  name    = "norman-public"
  network = "default"
  allow {
    protocol = "tcp"
    #   80 = Caddy: ACME HTTP-01 challenge + redirect to HTTPS.
    #  443 = Caddy: terminates TLS for norman.<domain>, reverse-proxies to
    #        the api container on :8000 over the internal docker network.
    #        Cloudflare proxies public 443 → origin 443 (SSL mode "Full").
    #        NOTE: 8000 is NOT a Cloudflare-proxiable port, which is why
    #        Caddy fronts the API rather than exposing uvicorn directly.
    # 8883 = mosquitto MQTT-over-TLS. Carl hubs reach this directly via
    #        mqtt.<domain> with grey-cloud DNS — Cloudflare's free tier
    #        doesn't proxy MQTT at all.
    ports = ["80", "443", "8883"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["norman"]
}

resource "google_compute_instance" "norman" {
  name         = "norman"
  machine_type = "e2-micro"
  zone         = var.zone
  tags         = ["norman"]

  boot_disk {
    initialize_params {
      # Debian 12 rather than Ubuntu 24.04 deliberately. On Noble the Google
      # guest agent fails to wire up SSH — it tries to reload `sshd.service`,
      # which doesn't exist there (the unit is `ssh.service`), and neither
      # metadata keys nor OS Login end up working. Debian is Google's
      # reference platform for the guest environment.
      image = "debian-cloud/debian-12"
      size  = 30
      type  = "pd-standard"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.norman.address
    }
  }

  # Set at create time on purpose — changing a service account or its scopes
  # on an existing instance requires stopping the VM, so getting it right
  # before the first apply avoids downtime later.
  service_account {
    email  = data.google_compute_default_service_account.default.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    # Provision the SSH key declaratively instead of letting `gcloud compute
    # ssh` push it to *project* metadata on first connect. Instance metadata
    # takes precedence and is applied at boot, so access works immediately.
    ssh-keys = "${var.ssh_user}:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"

    # Force the simple metadata-key path. OS Login is the other option, but
    # its guest-agent code path is what broke on the first attempt; metadata
    # keys need no sshd_config surgery, so there's less to go wrong.
    enable-oslogin = "FALSE"
  }

  metadata_startup_script = templatefile("${path.module}/cloud-init.sh", {
    ssh_user = var.ssh_user
    ssh_key  = trimspace(file(pathexpand(var.ssh_public_key_path)))
  })
}

output "external_ip" {
  value = google_compute_address.norman.address
}

output "artifacts_bucket" {
  value = google_storage_bucket.artifacts.name
}
