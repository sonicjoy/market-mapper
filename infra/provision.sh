#!/usr/bin/env bash
# Provision a GCP VM for market-mapping and run the bootstrap script.
# Run from your local machine:  ./infra/provision.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.env"

echo "Creating VM: $VM_NAME"
echo "  Project:  $PROJECT_ID"
echo "  Zone:     $ZONE"
echo "  Type:     e2-standard-2 (2 vCPU, 8GB)"
echo "  Disk:     160GB pd-balanced"
echo ""

gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$ZONE" \
    --machine-type=e2-standard-2 \
    --image-family=debian-13 \
    --image-project=debian-cloud \
    --boot-disk-size=160GB \
    --boot-disk-type=pd-balanced \
    --scopes=cloud-platform \
    --shielded-secure-boot \
    --shielded-vtpm \
    --shielded-integrity-monitoring

echo ""
echo "Waiting for SSH..."
for i in $(seq 1 30); do
    if gcloud compute ssh "$VM_NAME" \
        --zone="$ZONE" \
        --command="true" 2>/dev/null; then
        echo "  SSH ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: SSH not ready after 60 seconds" >&2
        exit 1
    fi
    sleep 2
done

echo ""
echo "Running bootstrap..."
gcloud compute scp "$SCRIPT_DIR/bootstrap.sh" "$VM_NAME:/tmp/bootstrap.sh" --zone="$ZONE"
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="sudo bash /tmp/bootstrap.sh"

echo ""
echo "=========================================="
echo "VM provisioned and bootstrapped."
echo ""
echo "Next steps:"
echo "  1. SSH in with agent forwarding:"
echo "     gcloud compute ssh $VM_NAME --zone=$ZONE -- -A"
echo ""
echo "  2. Clone the repo:"
echo "     git clone git@gitlab.com:whiteswandata/marketmaking/mmmapper.git"
echo "     cd mmmapper"
echo ""
echo "  3. Install Python and deps:"
echo "     mise install"
echo "     pip install -r requirements.txt"
echo ""
echo "  4. Test the pipeline:"
echo "     python -m fetch --league nba ncaab --out-dir data --minimal"
echo ""
echo "  5. Cron is installed automatically on deploy from infra/crontab"
echo "     (see infra/deploy.sh -> ensure_crontab).  No manual crontab -e"
echo "     needed; edit infra/crontab and deploy to change the schedule."
echo "=========================================="
