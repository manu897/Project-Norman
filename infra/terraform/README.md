# Norman — GCP deploy runbook

Provisions and deploys Norman onto GCP's always-free tier: one `e2-micro` VM, a static IP, a GCS bucket, and two firewall rules. The VM runs the whole stack in Docker.

**Target topology**

```
Carl hub ──mqtts://mqtt.manideepreddy.com:8883──┐   (grey-cloud DNS, direct to VM)
                                                 ▼
iPhone ──https://norman.manideepreddy.com──▶ Cloudflare ──443──▶ [ caddy ]
  (off-LAN)                                                          │
                                                            ┌────────┴────────┐
                                                            │  api  mosquitto │
                                                            │  ingest postgres│
                                                            └─────────────────┘
                                                              GCP e2-micro VM
```

Caddy exists because **Cloudflare's proxy only forwards to a fixed set of origin ports** (443, 2053, 2083, 2087, 2096, 8443 for HTTPS) — `8000` is not one of them. Caddy terminates a real Let's Encrypt cert on 443 and reverse-proxies to `api:8000` over the internal docker network, so Cloudflare→origin stays encrypted.

---

## 0 · Local prep

Terraform is **not** in Homebrew core — HashiCorp relicensed it to BUSL in 2023 and it moved to their own tap:

```bash
brew install hashicorp/tap/terraform
```

(`brew install terraform` fails with "No available formula". If you'd rather avoid the BUSL license, `brew install opentofu` is a drop-in fork — substitute `tofu` for `terraform` in every command below.)

Terraform reads a *different* credential file than the `gcloud` CLI. Create it (opens a browser):

```bash
gcloud auth application-default login
```

This stamps whatever project is *currently* active into the credential file as the quota project. If you run it before step 1 (as is easy to do), you'll get `WARNING: Your active project does not match the quota project in your local Application Default Credentials file` on later commands. Harmless, but fix it after step 1 with:

```bash
gcloud auth application-default set-quota-project norman-mrt
```

## 1 · GCP project

Project IDs are globally unique, lowercase, 6–30 chars. Swap `norman-mrt` for whatever you prefer — and use the same value everywhere below.

```bash
gcloud projects create norman-mrt --name="Norman"
```

Link billing (required to enable Compute Engine; you stay inside the free tier):

```bash
gcloud billing projects link norman-mrt --billing-account=01CAD3-2A0F9E-6578A6
```

Use `gcloud billing`, not `gcloud beta billing` — the beta variant prompts to install an extra SDK component for no benefit. Confirm it took with `gcloud billing projects describe norman-mrt` (expect `billingEnabled: true`).

Set it active and enable the two APIs Norman needs (~2 min):

```bash
gcloud config set project norman-mrt && gcloud services enable compute.googleapis.com storage.googleapis.com
```

> This switches your active gcloud project. To go back to a previous one later:
> `gcloud config set project <other-project-id>`

## 2 · Provision

Get your public IP — this scopes the SSH allowlist:

```bash
curl -s ifconfig.me
```

Write the variables (substitute the IP you just got):

```bash
cd infra/terraform && cat > terraform.tfvars <<'EOF'
project_id = "norman-mrt"
region     = "us-central1"
zone       = "us-central1-a"

# Residential IPs drift (mine changed .9 → .6 mid-setup). owner_cidr_bits = 24
# allowlists your ISP's local /24 instead of one exact address, so SSH keeps
# working across DHCP reshuffles. SSH is key-only (no password auth), so the
# wider range is an acceptable trade. Use 32 if you have a static IP.
owner_ip        = "1.2.3.4"
owner_cidr_bits = 24

# Access key. Must be the pair `gcloud compute ssh` / `ssh` actually offers.
# Defaults to ~/.ssh/google_compute_engine.pub and user `fwdev` — override
# ssh_public_key_path / ssh_user here if yours differ.
EOF
```

`us-central1` matters — `e2-micro` is only always-free in `us-west1` / `us-central1` / `us-east1`.

The VM runs **Debian 12**, not Ubuntu. On Ubuntu 24.04 the Google guest agent fails to wire up SSH (it reloads `sshd.service`, which is `ssh.service` there) and locks you out — Debian is Google's reference image for the guest environment. The key is provisioned declaratively via the startup script, so access works at first boot without waiting for `gcloud` to push a key.

```bash
cd infra/terraform && terraform init && terraform plan
```

`plan` should show **6 to add**: `google_compute_address`, `google_compute_instance`, `google_compute_firewall.ssh`, `google_compute_firewall.public`, `google_storage_bucket`, `google_storage_bucket_iam_member`.

### Set a budget alert first

Sixty seconds, and it's the difference between a surprise bill and an email at $5. GCP has **no hard spend cap** — budgets notify, they don't stop anything.

1. `console.cloud.google.com/billing` → your billing account → **Budgets & alerts** → **Create budget**
2. Scope: project `norman-mrt`. Amount: **$5/month**. Thresholds: 50% / 90% / 100%.

Then apply:

```bash
cd infra/terraform && terraform apply
```

Outputs:

```
external_ip      = "34.x.x.x"
artifacts_bucket = "norman-mrt-norman-artifacts"
```

## 3 · Cloudflare DNS

Two A records in the `manideepreddy.com` zone, both pointing at `external_ip`:

| Name | Type | Content | Proxy status |
|---|---|---|---|
| `norman` | A | `<external_ip>` | **Proxied** (orange cloud) |
| `mqtt` | A | `<external_ip>` | **DNS only** (grey cloud) |

`mqtt` *must* be grey — Cloudflare's free plan can't proxy MQTT at all, and an orange cloud there returns an HTTP error page to the hub instead of a broker handshake.

Then under **SSL/TLS → Overview**, set the encryption mode to **Full**. Not Flexible — Caddy serves a genuine cert, and Flexible would make Cloudflare talk plaintext to the origin.

Confirm propagation before continuing:

```bash
dig +short A norman.manideepreddy.com mqtt.manideepreddy.com
```

## 4 · VM setup

Log in:

```bash
gcloud compute ssh norman --zone=us-central1-a
```

This is Google's wrapper around plain `ssh` — it resolves the VM's current IP and connects as `fwdev` with `~/.ssh/google_compute_engine`. Everything after this runs **on the VM**; your prompt changes from `…MacBook-Pro %` to `fwdev@norman:~$`. Type `exit` to come back.

> **If you get `Permission denied (publickey)` on every attempt**, the problem is almost certainly client-side, not the VM. The most common cause: the private key has a passphrase and isn't loaded into ssh-agent (`ssh-add -l` says "The agent has no identities"). Fix it once:
> ```bash
> ssh-add --apple-use-keychain ~/.ssh/google_compute_engine
> ```
> `--apple-use-keychain` saves the passphrase to macOS Keychain so it auto-loads after a reboot. Confirm with `ssh-add -l` (should list the key), then retry. Only look at the server (serial console, OS Login, metadata keys) after ruling this out — a passphrase-locked key fails identically no matter what the VM does.
>
> **If you forgot the passphrase**, don't fight it — generate a fresh key, since provisioning is declarative:
> ```bash
> ssh-keygen -t ed25519 -f ~/.ssh/norman -N "" -C "norman"
> ```
> Set `ssh_public_key_path = "~/.ssh/norman.pub"` in `terraform.tfvars`, `terraform apply`, then `ssh -i ~/.ssh/norman fwdev@<external_ip>`.

Verify the bootstrap finished — Docker installed, swap active, daemon running:

```bash
docker --version && docker compose version && swapon --show && sudo systemctl is-active docker
```

`swapon --show` should list `/swapfile` (2 GB). If Docker isn't found yet, the startup script is still running — check `sudo journalctl -u google-startup-scripts -n 20` and retry after a minute. The serial log ends with `norman bootstrap complete` when it's done.

Clone and check out the branch:

```bash
sudo apt-get update && sudo apt-get install -y git certbot
```

```bash
git clone https://github.com/manu897/Project-Norman.git && cd Project-Norman && git checkout pilot
```

### 4a · Secrets

```bash
cp .env.example .env
```

Generate values to paste in:

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)"; echo "MQTT_PASSWORD=$(openssl rand -hex 16)"; echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
```

Now edit `.env` and set:

| Key | Value |
|---|---|
| `JWT_SECRET` | the generated hex |
| `POSTGRES_PASSWORD` | the generated hex |
| `DATABASE_URL` / `ALEMBIC_DATABASE_URL` | update the password segment to match |
| `MQTT_USERNAME` | `carl` |
| `MQTT_PASSWORD` | the generated hex — **Carl's firmware needs this too, save it** |
| `NORMAN_DOMAIN` | `norman.manideepreddy.com` |
| `ACME_EMAIL` | your real email (Let's Encrypt expiry notices) |

```bash
nano .env
```

### 4b · Broker password file

Use the same username/password you just put in `.env`:

```bash
mkdir -p infra/mosquitto/secrets && docker run --rm -v "$(pwd)/infra/mosquitto/secrets:/out" eclipse-mosquitto:2 mosquitto_passwd -b -c /out/passwd carl '<MQTT_PASSWORD>'
```

### 4c · TLS cert for the broker

**Order matters here.** `certbot --standalone` binds port 80, and Caddy will claim port 80 the moment the stack starts. So get this cert *before* `docker compose up`.

```bash
sudo certbot certonly --standalone -d mqtt.manideepreddy.com --agree-tos -m you@example.com -n
```

Copy the cert where mosquitto expects it:

```bash
sudo cp /etc/letsencrypt/live/mqtt.manideepreddy.com/fullchain.pem /etc/letsencrypt/live/mqtt.manideepreddy.com/privkey.pem infra/mosquitto/secrets/ && sudo chown "$USER:$USER" infra/mosquitto/secrets/* && chmod 600 infra/mosquitto/secrets/passwd infra/mosquitto/secrets/privkey.pem
```

Caddy fetches its own cert for `norman.manideepreddy.com` automatically on first boot — certbot is not involved there.

## 5 · Launch

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Migrations run automatically as part of the `api` container's start command. Watch the first boot:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

Look for:
- `caddy` — `certificate obtained successfully` for `norman.manideepreddy.com`
- `ingest` — `subscribed to carl/+/+` (and *not* a reconnect loop)
- `api` — `Uvicorn running on http://0.0.0.0:8000`

`Ctrl-C` to stop tailing (containers keep running).

## 6 · Verify

From your laptop:

```bash
curl https://norman.manideepreddy.com/health
```

Expect `{"status":"ok"}`.

Create your account:

```bash
curl -sX POST https://norman.manideepreddy.com/v1/auth/register -H 'Content-Type: application/json' -d '{"email":"you@example.com","password":"<strong-password>"}'
```

Save the `access_token` it returns as `$JWT`, then register your hub — the `id` must match what you'll configure on the firmware:

```bash
curl -sX POST https://norman.manideepreddy.com/v1/hubs -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' -d '{"id":"hub-001","name":"Home Hub"}'
```

Now push fake telemetry through the real public broker:

```bash
python scripts/fake_hub_publish.py --host mqtt.manideepreddy.com --port 8883 --username carl --password '<MQTT_PASSWORD>' --site hub-001 --node aabbccddeeff --interval 3
```

On the VM, `docker compose ... logs -f ingest` should print `ingested N metrics for site=hub-001 …`. Then read it back:

```bash
curl -s -H "Authorization: Bearer $JWT" https://norman.manideepreddy.com/v1/nodes
```

The fake node appears with its latest reading. That closes the loop: broker → ingest → Postgres → API.

## 7 · Point Carl at it

In `Project-Carl/firmware/hub/`:

```bash
idf.py menuconfig
```

```
Carl Hub configuration
  → [*] Stream readings to Project-Norman over MQTT
  → Norman MQTT broker URI = mqtts://mqtt.manideepreddy.com:8883
  → Norman MQTT username   = carl
  → Norman MQTT password   = <MQTT_PASSWORD from .env>
  → Site / hub identifier  = hub-001        ← must match POST /v1/hubs
  → Publish interval (s)   = 30
```

```bash
idf.py build flash monitor
```

Real hub traffic should start appearing in the `ingest` logs within 30 seconds.

---

## Operations

### Verify the real cost (do this ~48 h after apply)

This is the number that decides whether GCP stays the host. Estimates in docs drift; the billing table doesn't.

1. `console.cloud.google.com/billing` → your billing account → **Cost table**
2. Filter to project `norman-mrt`, group by **SKU**
3. Expect one meaningful line — an external/static IP charge SKU — and effectively nothing else

Two days of data extrapolates cleanly to a monthly run-rate. If it's near **$3.65/mo**, the estimate held. If the compute or disk SKUs show non-zero, something fell outside the free tier — most likely the wrong zone or an oversized disk.

Also check **Credits** on the same page: a live $300 / 90-day trial would zero the bill for three months and change the calculus.

> A home Ubuntu laptop (~£2–3.50/mo electricity, 8–16 GB RAM, and MQTT never leaving the LAN) is the cheaper and architecturally simpler alternative — see [`infra/home/README.md`](../home/README.md).

### Cert renewal (every ~90 days)

Certbot needs port 80, which Caddy holds. So:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop caddy && sudo certbot renew && sudo cp /etc/letsencrypt/live/mqtt.manideepreddy.com/{fullchain.pem,privkey.pem} infra/mosquitto/secrets/ && sudo chown "$USER:$USER" infra/mosquitto/secrets/*.pem && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Caddy's own cert renews itself with no intervention.

**Better long-term fix:** switch mosquitto's cert to DNS-01 validation via `certbot-dns-cloudflare` (you're already on Cloudflare). No port needed, so no downtime and it can be fully cron'd. Not required for the first deploy.

### Updating Norman

```bash
cd ~/Project-Norman && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Backups — GCS, then home to the NAS

Two hops, because the WD My Cloud Home is a locked platform: it serves SMB on the LAN but has no SSH and can't be reached from the internet, so GCP can't push to it directly.

**Hop 1 — VM → GCS (automatic).** The VM's service account has `objectAdmin` on the artifacts bucket, granted in `main.tf`, so no keys are needed. On the VM:

```bash
cd ~/Project-Norman && ./scripts/backup_postgres.sh
```

It dumps Postgres, gzips, refuses to upload a suspiciously small file, and writes to `gs://<project>-norman-artifacts/backups/`. Schedule it nightly:

```bash
(crontab -l 2>/dev/null; echo '15 3 * * * cd $HOME/Project-Norman && ./scripts/backup_postgres.sh >> $HOME/norman-backup.log 2>&1') | crontab -
```

The bucket has lifecycle rules deleting objects after 90 days, so backups can't quietly grow past the 5 GB always-free ceiling.

**Hop 2 — GCS → NAS (whenever the laptop is on).** This doesn't need to be continuous; it's a second copy, not the primary. On the Ubuntu laptop, mount the My Cloud Home's SMB share:

```bash
sudo apt-get install -y cifs-utils && sudo mkdir -p /mnt/nas
```

```bash
sudo mount -t cifs //<nas-ip>/Public /mnt/nas -o username=<wd-user>,uid=$(id -u),gid=$(id -g)
```

Then pull anything new:

```bash
mkdir -p /mnt/nas/norman-backups && gcloud storage rsync -r gs://norman-mrt-norman-artifacts/backups /mnt/nas/norman-backups
```

Run that whenever the laptop is up. Add it to the laptop's crontab if it's on often enough to matter.

**Restoring:**

```bash
gunzip -c norman-20260823T031500Z.sql.gz | docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U norman norman
```

### Tearing it all down

```bash
cd infra/terraform && terraform destroy
```

## What this actually costs

**Expect roughly $4/month, not $0.** "Always-free tier" does not mean the whole deployment is free.

Genuinely free:

| Resource | Allowance | This deployment |
|---|---|---|
| `e2-micro` instance | 744 h/mo in `us-west1`/`us-central1`/`us-east1` | 1 instance, 24×7 → $0 |
| Boot disk | 30 GB-month `pd-standard` | exactly 30 GB → $0 |
| GCS Standard | 5 GB in those same regions | ~0 GB for a long time → $0 |
| Egress | 1 GB/mo to North America | telemetry JSON, tens of MB → $0 |
| Firewall rules | unlimited | 2 → $0 |

**Not free — the external IPv4 address.** Since **February 2024** Google charges for *all* external IPv4 addresses, including in-use ones attached to a running VM, at roughly **$0.005/hour ≈ $3.65/month**. The always-free tier does not exempt it. This is the entire bill for a working Norman.

Two things that follow from that:

- **Don't try to optimise the IP away.** A VM with no external IP also has no *outbound* internet — no `apt`, no Docker pulls — unless you add **Cloud NAT**, which runs ~$0.044/hour ≈ **$32/month**. Nine times worse. On GCP the IPv4 charge is effectively unavoidable, which is why `main.tf` provisions the static address deliberately.
- **Check for trial credits.** A live $300 / 90-day free trial on the billing account would mask this entirely for three months. Look at `console.cloud.google.com/billing` → your account → **Credits**.

Other notes:

- The `e2-micro` allowance is **per billing account, not per project** — a second e2-micro anywhere on account `01CAD3-…` starts incurring charges.
- Egress only matters if Norman ever serves large payloads. It won't: camera stills stay on the hub precisely so image bytes never cross this boundary.
- GCP pricing changes and this file will drift. **The authoritative number is the billing Cost table, not this doc** — see *Verify the real cost* under Operations.

## Gotchas

- **`Permission denied (publickey)` on every SSH attempt** — check the *client* before the server. Usual cause: a passphrase-protected key not loaded in ssh-agent. `ssh-add -l`; if empty, `ssh-add --apple-use-keychain ~/.ssh/google_compute_engine`. A locked key fails identically regardless of image, OS Login, or metadata-key config — don't rebuild the VM chasing it (I did; it wasn't the VM).
- **Orange cloud on `mqtt.`** — the single most likely misconfiguration. Cloudflare returns an HTTP error instead of an MQTT handshake and the hub logs a TLS failure. Must be grey.
- **Cloudflare SSL mode left on Flexible** — Cloudflare sends plain HTTP to origin :80, Caddy redirects to HTTPS, and you get an infinite redirect loop. Set it to Full.
- **Running certbot after starting the stack** — port 80 is taken by Caddy, certbot fails with a bind error. Stop Caddy first (or do it before step 5).
- **Losing the `caddy_data` volume** — Caddy re-requests certs on every start and Let's Encrypt rate-limits you (5 failures/hour, 50 certs/week per domain). The named volume in `docker-compose.prod.yml` prevents this; don't `docker compose down -v`.
- **Postgres is not published.** By design. Reach it with `docker compose exec postgres psql -U norman`, not from your laptop.
- **8883 is open to the world.** Auth (`allow_anonymous false` + password file) is what gates it. Rotate `MQTT_PASSWORD` and regenerate the passwd file if it ever leaks.
