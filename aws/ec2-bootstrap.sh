#!/usr/bin/env bash
#
# EC2 user-data: paste this into "Advanced details → User data" when launching
# an Ubuntu 24.04 instance, and it comes up serving the product on port 80.
# Nothing to log in and do by hand.
#
# Watch it run:  sudo tail -f /var/log/cloud-init-output.log
set -euxo pipefail

REPO_URL="https://github.com/vivek1234-byte/Qfleet_Optimization.git"
APP_DIR="/opt/qfleet"

# --- swap ------------------------------------------------------------------
# A t3.micro has 1 GB of RAM. Compiling and installing scipy, scikit-learn and
# xgboost needs more than that, and the build dies with a bare "Killed" that
# looks like a broken Dockerfile rather than what it is. 2 GB of swap costs a
# few seconds of disk and makes a free-tier instance sufficient.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- docker ----------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu || true

# --- the application -------------------------------------------------------
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# Signing key for session tokens. Generated once and kept, so a restart does
# not sign everybody out.
if [ ! -f aws/.env ]; then
  echo "QGF_JWT_SECRET=$(openssl rand -hex 32)" > aws/.env
  chmod 600 aws/.env
fi

# First build pulls ~600 MB of wheels and trains the fuel model. Ten to
# fifteen minutes on a t3.micro, three or four on a t3.small.
docker compose -f aws/docker-compose.yml --env-file aws/.env up -d --build

# Survive a reboot without waiting for cloud-init to run again.
cat > /etc/systemd/system/qfleet.service <<'UNIT'
[Unit]
Description=QFleet
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/qfleet
ExecStart=/usr/bin/docker compose -f aws/docker-compose.yml --env-file aws/.env up -d
ExecStop=/usr/bin/docker compose -f aws/docker-compose.yml down

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable qfleet.service

echo "QFleet is up on port 80."
