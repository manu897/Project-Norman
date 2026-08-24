#!/usr/bin/env bash
# Dump Norman's Postgres database and upload it to the GCS artifacts bucket.
#
# Runs ON THE VM, from the Project-Norman checkout root. The VM's service
# account has objectAdmin on the bucket (granted in infra/terraform/main.tf),
# so no key file or extra auth is needed.
#
# Usage:
#   ./scripts/backup_postgres.sh                       # bucket from terraform output
#   BUCKET=my-bucket ./scripts/backup_postgres.sh      # or set it explicitly
#
# Nightly via cron (3:15 AM):
#   15 3 * * * cd $HOME/Project-Norman && ./scripts/backup_postgres.sh >> $HOME/norman-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
PGUSER="${POSTGRES_USER:-norman}"
PGDB="${POSTGRES_DB:-norman}"

# Bucket name follows the Terraform convention <project_id>-norman-artifacts.
if [[ -z "${BUCKET:-}" ]]; then
    PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
    [[ -z "$PROJECT" || "$PROJECT" == "(unset)" ]] && {
        echo "Can't determine project; set BUCKET=<name> explicitly." >&2
        exit 1
    }
    BUCKET="${PROJECT}-norman-artifacts"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="norman-${STAMP}.sql.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Dumping ${PGDB} as ${PGUSER}"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$PGUSER" "$PGDB" | gzip >"${TMP}/${OUT}"

SIZE="$(du -h "${TMP}/${OUT}" | cut -f1)"
echo "==> Dump is ${SIZE}"

# Refuse to upload a suspiciously tiny dump — an empty/failed pg_dump still
# gzips to a couple hundred bytes, and silently shipping that over a good
# backup is worse than failing loudly.
BYTES="$(stat -c%s "${TMP}/${OUT}" 2>/dev/null || stat -f%z "${TMP}/${OUT}")"
if [[ "$BYTES" -lt 1000 ]]; then
    echo "Dump is only ${BYTES} bytes — treating as a failure, not uploading." >&2
    exit 1
fi

echo "==> Uploading to gs://${BUCKET}/backups/${OUT}"
gcloud storage cp "${TMP}/${OUT}" "gs://${BUCKET}/backups/${OUT}"

echo "==> Done. Recent backups:"
gcloud storage ls -l "gs://${BUCKET}/backups/" | tail -6
