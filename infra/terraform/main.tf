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
  description = "Your home/office IPv4 with /32 — used for SSH allowlist"
  type        = string
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
}

resource "google_compute_firewall" "ssh" {
  name    = "norman-ssh"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = ["${var.owner_ip}/32"]
  target_tags   = ["norman"]
}

resource "google_compute_firewall" "public" {
  name    = "norman-public"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["443", "8883"]
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
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
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

  metadata_startup_script = file("${path.module}/cloud-init.sh")
}

output "external_ip" {
  value = google_compute_address.norman.address
}

output "artifacts_bucket" {
  value = google_storage_bucket.artifacts.name
}
