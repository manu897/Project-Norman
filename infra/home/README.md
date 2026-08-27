# Norman on a home Ubuntu machine

Run Norman on a spare laptop or mini PC on your home network, reachable from the internet through a Cloudflare Tunnel. No port forwarding, no static IP, no inbound firewall rules, and — the real win — **no public MQTT broker at all**.

This is the recommended deployment. See [`../terraform/README.md`](../terraform/README.md) for the GCP alternative.

## Why this is simpler than the cloud deployment

The Carl hubs live on the same LAN as Norman. So MQTT never crosses the internet:

```
[Plant probe] [Room sensor] ──BTHome/BLE──▶ Carl hub
                                              │
                                              │  mqtt://<laptop-lan-ip>:1883
                                              │  (plaintext, LAN only)
                                              ▼
iPhone (at home) ──HTTP──▶ carl-hub.local   Norman  ◀── postgres · mosquitto
                                              │           api · ingest
                                              │
                                    cloudflared (outbound only)
                                              │
                                              ▼
                                    Cloudflare edge (TLS)
                                              │
iPhone (off-LAN) ──https://norman.manideepreddy.com──┘
```

Compared to the GCP deployment, this **deletes**: Caddy, certbot, the Let's Encrypt cert for the broker, the 90-day renewal dance, TLS config on mosquitto, port 8883, and every inbound firewall rule. Only plain HTTPS crosses the internet, and Cloudflare handles that.

## Cost

A laptop at 10–20 W idle is roughly **£2–3.50/month** in electricity at ~£0.25/kWh — comparable to, maybe cheaper than, GCP's ~£2.75/mo external-IP charge (the actual bill for the always-free `e2-micro` deployment; see [`infra/terraform/README.md`](../terraform/README.md#what-this-actually-costs)), but with 8–16 GB RAM instead of 1 GB.

A desktop tower at 50–100 W is ~£9–18/mo and loses to GCP on cost. Use a laptop or mini PC.

The tradeoff is uptime: your home power and ISP replace Google's 99.9%.

---

## 1 · Prepare the host

On the Ubuntu machine:

```bash
git clone https://github.com/manu897/Project-Norman.git && cd Project-Norman && git checkout pilot
```

```bash
sudo ./infra/home/setup.sh --tailscale
```

This installs Docker + the compose plugin, masks the sleep/suspend/hibernate targets, tells logind to ignore the lid switch, clears GNOME's idle-suspend settings, and optionally installs Tailscale. Idempotent — re-run it any time.

It prints the machine's **LAN IP** at the end. Note it down; the Carl hub needs it. Then **give this machine a DHCP reservation** in your router so the address doesn't change under you.

Drop `--tailscale` if you don't want it. It's worth having: `sudo tailscale up --ssh` afterwards lets you get a shell on this box from anywhere without exposing port 22 to anything.

## 2 · Cloudflare Tunnel

The tunnel dials *out* from your laptop to Cloudflare, so nothing needs to be reachable inbound.

1. Go to **[one.dash.cloudflare.com](https://one.dash.cloudflare.com)** → **Networks** → **Tunnels** → **Create a tunnel**
2. Type: **Cloudflared**. Name it `norman`.
3. Skip the install instructions — the compose file runs `cloudflared` for you. **Copy the token** from the shown command (the long string after `--token`).
4. On the **Public Hostnames** tab, add a route:

   | Field | Value |
   |---|---|
   | Subdomain | `norman` |
   | Domain | `manideepreddy.com` |
   | Service type | `HTTP` |
   | URL | `api:8000` |

5. Save.

Cloudflare creates the `norman.manideepreddy.com` DNS record itself, as a proxied CNAME to the tunnel. **If you previously created an A record for `norman` pointing at a GCP IP, delete it** — the tunnel's record replaces it.

You do **not** need an `mqtt.` record in this topology. If you made one for the cloud deploy, delete it too.

## 3 · Configure

```bash
cp .env.example .env
```

Generate values:

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)"; echo "MQTT_PASSWORD=$(openssl rand -hex 16)"; echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
```

Edit `.env` and set:

| Key | Value |
|---|---|
| `JWT_SECRET` | the generated hex |
| `POSTGRES_PASSWORD` | the generated hex |
| `DATABASE_URL`, `ALEMBIC_DATABASE_URL` | update the password segment to match |
| `MQTT_USERNAME` | `carl` |
| `MQTT_PASSWORD` | the generated hex — **the Carl hub needs this too, save it** |
| `CLOUDFLARE_TUNNEL_TOKEN` | the token from step 2 |

`NORMAN_DOMAIN` and `ACME_EMAIL` are only used by the cloud deployment's Caddy — leave them alone here.

```bash
nano .env
```

### Broker password file

Same username and password you just put in `.env`:

```bash
mkdir -p infra/mosquitto/secrets && docker run --rm -v "$(pwd)/infra/mosquitto/secrets:/out" eclipse-mosquitto:2 mosquitto_passwd -b -c /out/passwd carl '<MQTT_PASSWORD>'
```

```bash
chmod 600 infra/mosquitto/secrets/passwd
```

## 4 · Launch

```bash
docker compose -f docker-compose.yml -f docker-compose.home.yml up -d
```

Migrations run automatically in the `api` container's start command. Watch the first boot:

```bash
docker compose -f docker-compose.yml -f docker-compose.home.yml logs -f
```

Look for:
- `cloudflared` — `Registered tunnel connection` (usually 4 of them, to different Cloudflare edge locations)
- `ingest` — `subscribed to carl/+/+`, and no reconnect loop
- `api` — `Uvicorn running on http://0.0.0.0:8000`

## 5 · Verify

On the LAN:

```bash
curl localhost:8000/health
```

From anywhere, through the tunnel:

```bash
curl https://norman.manideepreddy.com/health
```

Both should return `{"status":"ok"}`.

Register your account and hub:

```bash
curl -sX POST https://norman.manideepreddy.com/v1/auth/register -H 'Content-Type: application/json' -d '{"email":"you@example.com","password":"<strong-password>"}'
```

Save the `access_token` as `$JWT`, then:

```bash
curl -sX POST https://norman.manideepreddy.com/v1/hubs -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' -d '{"id":"hub-001","name":"Home Hub"}'
```

Push fake telemetry at the LAN broker:

```bash
python scripts/fake_hub_publish.py --host localhost --port 1883 --username carl --password '<MQTT_PASSWORD>' --site hub-001 --node aabbccddeeff --interval 3
```

`docker compose ... logs -f ingest` should print `ingested N metrics for site=hub-001 …`. Then read it back through the tunnel:

```bash
curl -s -H "Authorization: Bearer $JWT" https://norman.manideepreddy.com/v1/nodes
```

That closes the loop: LAN broker → ingest → Postgres → API → public HTTPS.

## 6 · Point Carl at it

Use the **LAN IP** from step 1 — plain `mqtt://`, no TLS, since this stays inside your network.

In `Project-Carl/firmware/hub/`:

```bash
idf.py menuconfig
```

```
Carl Hub configuration
  → [*] Stream readings to Project-Norman over MQTT
  → Norman MQTT broker URI = mqtt://192.168.1.x:1883      ← your laptop's LAN IP
  → Norman MQTT username   = carl
  → Norman MQTT password   = <MQTT_PASSWORD from .env>
  → Site / hub identifier  = hub-001        ← must match POST /v1/hubs
  → Publish interval (s)   = 30
```

```bash
idf.py build flash monitor
```

---

## Operations

### Updating

```bash
cd ~/Project-Norman && git pull && docker compose -f docker-compose.yml -f docker-compose.home.yml up -d --build
```

### Backups

Postgres lives in the `postgres_data` docker volume on the laptop's disk. Nightly dump to your home directory:

```bash
docker compose -f docker-compose.yml -f docker-compose.home.yml exec -T postgres pg_dump -U norman norman | gzip > ~/norman-backup-$(date +%F).sql.gz
```

Wrap that in a cron job and rclone it somewhere off-site — a free GCS bucket or Backblaze B2 — so a dead laptop doesn't take your history with it.

### Checking it's still alive

```bash
docker compose -f docker-compose.yml -f docker-compose.home.yml ps
```

Everything is `restart: unless-stopped`, and Docker is enabled at boot, so a power cut recovers on its own once the machine comes back.

## Gotchas

- **Laptop battery on permanent charge.** Some laptops degrade a battery held at 100%. If your model supports a charge limit (ThinkPads, many Dells, some ASUS), cap it at ~60–80% in BIOS or via `tlp`. Not urgent, but it's a two-year problem you can avoid today.
- **The LAN IP moving.** DHCP will eventually reassign it and the Carl hub will silently stop publishing. Set a DHCP reservation. This is the single most likely thing to break this setup.
- **`cloudflared` shows 4 connections, not 1.** That's normal and correct — it opens redundant connections to different Cloudflare edge PoPs.
- **Tunnel token is a credential.** It's in `.env`, which is gitignored. Anyone with it can serve traffic on your hostname. Don't paste it into an issue or a screenshot.
- **No `mqtt.` DNS record needed.** If you're migrating from the GCP deploy, delete the `mqtt.manideepreddy.com` record and the `norman` A record — the tunnel manages its own CNAME.
- **`docker compose down -v` deletes your database.** The `-v` drops named volumes. Use plain `down` unless you genuinely mean it.
