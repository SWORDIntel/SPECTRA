#!/usr/bin/env bash
# NetFix — Launch Training on L40S
# Run this from the cloud-training-framework directory.
#
# Cost: ~$1.50-2.00 for full training run on L40S (~45 min)
# Output: models/netfix-merged/  (download via launch.py --download)

set -e
export PROJECT_ID=project-e00re3c0pr00026p9jzhq4
export SUBNET_ID=vpcsubnet-e00j50ben51r17797n
export IMAGE_ID=computeimage-e00ckjm576pedy5rwv
export SSH_KEY=~/.ssh/id_rsa
export SSH_USER=ubuntu

cd "$(dirname "$0")/.."

echo "=== NetFix Training Launcher ==="
echo ""

# Validate env
for var in PROJECT_ID SUBNET_ID IMAGE_ID; do
    if [[ -z "${!var}" ]]; then
        echo "ERROR: $var not set. Export it first."
        exit 1
    fi
done

# Set L40S platform
export PLATFORM="${PLATFORM:-gpu-l40s-a}"
export PRESET="${PRESET:-1gpu-40vcpu-160gb}"
export VM_NAME="${VM_NAME:-netfix-training}"
export DISK_SIZE_GIB=150

echo "Platform:  $PLATFORM ($PRESET)"
echo "VM name:   $VM_NAME"
echo "Dataset:   $(wc -l < netfix/data/train.jsonl) examples"
echo ""

echo "[1] Regenerating synthetic data (200 examples)..."
python3 netfix/data/generate_data.py \
    --output netfix/data/synthetic.jsonl \
    --count 200
cat netfix/data/gold.jsonl netfix/data/synthetic.jsonl > netfix/data/train.jsonl
echo "    Total: $(wc -l < netfix/data/train.jsonl) training examples"

echo ""
echo "[2] Launching cloud VM + training..."
python3 launch.py

echo ""
echo "[3] When training completes, download model:"
echo "    python3 launch.py --download"
echo ""
echo "[4] Install daemon locally after download:"
echo "    sudo cp models/netfix-merged /opt/netfix-model-merged -r"
echo "    sudo cp netfix/daemon/netfix_daemon.py /usr/local/bin/netfix-daemon.py"
echo "    sudo cp netfix/daemon/netfix.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable --now netfix"
