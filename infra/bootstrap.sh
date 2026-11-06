#!/usr/bin/env bash
# System-level bootstrap for the market-mapping VM.
# SCP'd to the VM and run as root by provision.sh.

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== System update ==="
# Hold google-cloud-cli to avoid the slow (3+ min) upgrade
apt-mark hold google-cloud-cli
apt-get update -y
apt-get upgrade -y
apt-mark unhold google-cloud-cli

echo "=== Installing system packages ==="
apt-get install -y htop git curl bzip2 cloud-guest-utils

echo "=== Installing mise ==="
install -dm 755 /etc/apt/keyrings
curl -fsSL https://mise.jdx.dev/gpg-key.pub \
    | tee /etc/apt/keyrings/mise-archive-keyring.asc > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/mise-archive-keyring.asc] https://mise.jdx.dev/deb stable main" \
    | tee /etc/apt/sources.list.d/mise.list
apt-get update -y
apt-get install -y mise

# Activate mise for all users on login
echo 'eval "$(mise activate bash)"' > /etc/profile.d/mise.sh

echo "=== Configuring unattended-upgrades ==="
apt-get install -y unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APTCONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APTCONF

echo "=== Installing Ops Agent (GCP logging) ==="
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
bash add-google-cloud-ops-agent-repo.sh --also-install
rm add-google-cloud-ops-agent-repo.sh

# Ship pipeline logs to Cloud Logging
# View: gcloud logging read 'logName:"pipeline_log"' --project=rs-marketmaking --limit=20
cat > /etc/google-cloud-ops-agent/config.yaml <<'OPSCONF'
logging:
  receivers:
    pipeline_log:
      type: files
      include_paths:
        - /home/gtod/mmmapper/logs/pipeline.log
  service:
    pipelines:
      pipeline:
        receivers:
          - pipeline_log
OPSCONF
systemctl restart google-cloud-ops-agent

echo ""
echo "=== Bootstrap complete ==="
echo "  Installed: htop git curl bzip2 mise unattended-upgrades google-cloud-ops-agent"
echo "  mise activation: /etc/profile.d/mise.sh (applies on next login)"
echo "  Ops Agent: tailing logs/pipeline.log to Cloud Logging"
