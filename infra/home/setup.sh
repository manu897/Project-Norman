#!/usr/bin/env bash
# Prepare an Ubuntu machine to host Norman on the home network.
#
# Idempotent — safe to re-run. Does NOT start Norman; see infra/home/README.md
# for the deploy steps after this.
#
# Usage:
#   sudo ./infra/home/setup.sh              # Docker + always-on tweaks
#   sudo ./infra/home/setup.sh --tailscale  # ...plus Tailscale for admin SSH
set -euo pipefail

WITH_TAILSCALE=0
[[ "${1:-}" == "--tailscale" ]] && WITH_TAILSCALE=1

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

log() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- Docker
if command -v docker >/dev/null 2>&1; then
    log "Docker already installed ($(docker --version))"
else
    log "Installing Docker"
    apt-get update
    apt-get install -y ca-certificates curl gnupg git

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg |
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        >/etc/apt/sources.list.d/docker.list

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker

# Let the invoking user run docker without sudo (takes effect next login).
REAL_USER="${SUDO_USER:-}"
if [[ -n "$REAL_USER" ]] && ! id -nG "$REAL_USER" | grep -qw docker; then
    log "Adding $REAL_USER to the docker group (re-login to take effect)"
    usermod -aG docker "$REAL_USER"
fi

# ------------------------------------------------------- Stay awake 24/7
# A laptop is the ideal Norman host on power draw, but Ubuntu will suspend it
# on lid close and idle by default — which takes Norman offline and loses
# telemetry. Disable both.
log "Disabling sleep / suspend / hibernate"
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

log "Ignoring the lid switch"
install -d /etc/systemd/logind.conf.d
cat >/etc/systemd/logind.conf.d/99-norman-stay-awake.conf <<'EOF'
# Norman host: keep running with the lid shut.
[Login]
HandleLidSwitch=ignore
HandleLidSwitchDocked=ignore
HandleLidSwitchExternalPower=ignore
EOF

# GNOME's own idle settings sit outside logind; neutralise them if present.
if command -v gsettings >/dev/null 2>&1 && [[ -n "$REAL_USER" ]]; then
    log "Clearing GNOME automatic-suspend settings"
    sudo -u "$REAL_USER" dbus-launch gsettings set \
        org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null || true
    sudo -u "$REAL_USER" dbus-launch gsettings set \
        org.gnome.desktop.session idle-delay 0 2>/dev/null || true
fi

systemctl restart systemd-logind

# ------------------------------------------------------------- Tailscale
if [[ $WITH_TAILSCALE -eq 1 ]]; then
    if command -v tailscale >/dev/null 2>&1; then
        log "Tailscale already installed"
    else
        log "Installing Tailscale"
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    echo
    echo "Tailscale installed but not connected. Finish with:"
    echo "    sudo tailscale up --ssh"
    echo "Then you can reach this box from anywhere as its tailnet name,"
    echo "without exposing port 22 to your LAN or the internet."
fi

# ---------------------------------------------------------------- Summary
cat <<EOF

$(log "Host prepared")

  Docker      $(docker --version 2>/dev/null || echo 'not found')
  Compose     $(docker compose version --short 2>/dev/null || echo 'not found')
  Sleep       masked (sleep, suspend, hibernate, hybrid-sleep)
  Lid switch  ignored
  LAN IP      $(hostname -I | awk '{print $1}')

Note that LAN IP — the Carl hub needs it to publish MQTT. Give this machine a
DHCP reservation on your router so it doesn't move.

Next: infra/home/README.md, from "Cloudflare Tunnel".
EOF
