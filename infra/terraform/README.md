# Norman — GCP free-tier infra

Provisions an `e2-micro` VM (always-free in `us-west1` / `us-central1` / `us-east1`), a static external IP, a GCS bucket for ML artifacts, and firewall rules. The VM is bootstrapped with Docker via `cloud-init.sh`.

> **Heads up — this is not run yet.** Terraform is here so the infra is reviewable, not deployed.

## First-time setup

```bash
gcloud auth application-default login
gcloud projects create norman-<your-suffix> --name="Norman"
gcloud config set project norman-<your-suffix>
gcloud services enable compute.googleapis.com storage.googleapis.com

cd infra/terraform
cat > terraform.tfvars <<EOF
project_id = "norman-<your-suffix>"
region     = "us-central1"
zone       = "us-central1-a"
owner_ip   = "1.2.3.4"   # your home/office public IPv4
EOF

terraform init
terraform plan
terraform apply
```

## After `apply`

1. SSH into the VM (`gcloud compute ssh norman --zone=us-central1-a`).
2. Clone this repo on the VM.
3. Copy `.env.example` to `.env` and set `JWT_SECRET` to a real secret (`openssl rand -hex 32`).
4. Terminate TLS in front of the API — Cloudflare proxied DNS for `norman.<domain>` works without any cert config on the VM (origin runs plain HTTP on :8000, Cloudflare adds the public HTTPS).
5. `docker compose up -d`.
6. Point your domain at the static IP (Cloudflare proxied → `norman.<domain>` → port 8000).

## Free-tier notes

- e2-micro is always-free **only** in `us-west1` / `us-central1` / `us-east1`. One instance per project.
- Egress: 1 GB/mo to most regions free, then $0.12/GB. Telemetry is small JSON; this is fine.
- GCS standard: 5 GB/mo free in those same regions. Don't dump raw NetCDFs there.
