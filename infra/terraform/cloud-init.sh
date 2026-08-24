#!/usr/bin/env bash
# Bootstraps the Norman VM: SSH access, swap, Docker.
#
# Rendered by Terraform via templatefile(). A dollar-sign followed by a brace
# is a TERRAFORM interpolation here, not bash — including inside comments.
# So keep every bash variable reference brace-free ("$FOO", never the braced
# form) or Terraform will try to evaluate it at plan time and fail.
#
# The app stack itself is deployed separately — see infra/terraform/README.md.
set -euo pipefail

SSH_USER='${ssh_user}'
SSH_KEY='${ssh_key}'

# ------------------------------------------------------------------ SSH
# Provisioned here rather than relying solely on the Google guest agent. The
# first build of this VM ran Ubuntu 24.04, where the agent fails to wire up
# SSH at all (it tries to reload `sshd.service`, which is `ssh.service` on
# Debian/Ubuntu) and locked us out entirely. Instance metadata should handle
# this on Debian, but doing it explicitly means access never depends on the
# agent behaving.
if ! id -u "$SSH_USER" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$SSH_USER"
fi
usermod -aG sudo "$SSH_USER"

install -d -m 700 -o "$SSH_USER" -g "$SSH_USER" "/home/$SSH_USER/.ssh"
printf '%s\n' "$SSH_KEY" >"/home/$SSH_USER/.ssh/authorized_keys"
chmod 600 "/home/$SSH_USER/.ssh/authorized_keys"
chown "$SSH_USER:$SSH_USER" "/home/$SSH_USER/.ssh/authorized_keys"

# Passwordless sudo — there's no password on this account to type.
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$SSH_USER" >"/etc/sudoers.d/90-$SSH_USER"
chmod 440 "/etc/sudoers.d/90-$SSH_USER"

# ----------------------------------------------------------------- Swap
# e2-micro has 1 GB of RAM and the stack is postgres + mosquitto + api +
# ingest + caddy. That fits, but with little headroom — a build or a big
# query can push it over and the OOM killer picks a victim at random.
# 2 GB of swap on the 30 GB disk turns "container died mysteriously" into
# "briefly slow".
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >>/etc/fstab
    # Prefer reclaiming page cache over swapping; only swap under real pressure.
    echo 'vm.swappiness=10' >/etc/sysctl.d/99-norman-swappiness.conf
    sysctl -p /etc/sysctl.d/99-norman-swappiness.conf
fi

# --------------------------------------------------------------- Docker
apt-get update
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    >/etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

# Let the SSH user drive docker without sudo.
usermod -aG docker "$SSH_USER"

echo "norman bootstrap complete"
