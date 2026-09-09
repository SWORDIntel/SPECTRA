#!/bin/bash
set -euo pipefail
# One-command setup for ML model training on NVIDIA GPU (CUDA 12.x/13.x)
# Installs: Python 3.12, PyTorch with CUDA, OpenCV, ONNX, OpenVINO, dev tools
exec > >(tee /var/log/training-setup.log) 2>&1

log() { echo "[SETUP] $(date -Iseconds) $*"; }

# ── Configuration (override via env vars) ──
REPO_URL="${REPO_URL:-}"                          # Git repo to clone (optional)
CLONE_DIR="${CLONE_DIR:-/opt/training-repo}"
VENV="${VENV:-/opt/training-venv}"
PYTHON="${PYTHON:-python3.12}"

log "Starting setup on $(hostname)"

# 1. System packages
log "Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q

# Core packages (required — fail if these don't install)
apt-get install -y -q \
  $PYTHON $PYTHON-venv $PYTHON-dev python3-pip \
  build-essential cmake pkg-config \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
  git curl wget tmux unzip \
  || { log "Failed to install core packages"; exit 1; }

# Optional packages (non-fatal)
apt-get install -y -q htop nvtop nodejs npm || log "Some optional packages failed, continuing"

# 2. Verify Python
$PYTHON --version

# 3. Create venv
log "Creating Python virtual environment at $VENV..."
$PYTHON -m venv "$VENV" || (rm -rf "$VENV" && $PYTHON -m venv "$VENV")
source "$VENV/bin/activate"

# 4. Upgrade base tools
pip install --upgrade pip wheel setuptools

# 5. PyTorch with CUDA (try CUDA 12.6 wheels, fall back to 12.4, then CPU)
log "Installing PyTorch for CUDA..."
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 || {
  log "PyTorch cu126 failed, trying cu124..."
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 || {
    log "PyTorch CUDA failed, installing CPU version..."
    pip install torch torchvision
  }
}

# 6. Core Python deps
log "Installing Python dependencies..."
pip install \
  opencv-python-headless pillow numpy rich tqdm pyyaml \
  openvino onnx onnxscript matplotlib seaborn scikit-learn

# 7. Dev tools (non-fatal)
log "Installing dev tools..."
npm install -g @openai/codex || log "Codex CLI install failed, continuing"
curl -LsSf https://astral.sh/uv/install.sh | sh || true
export PATH="$HOME/.cargo/bin:$PATH"
uvx google-agents-cli setup --skip-auth || pip install google-agents-cli || true

# 8. Verify GPU
log "GPU check:"
python3 -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')" || true

# 9. Clone repo if URL provided and not already present
if [ -n "$REPO_URL" ]; then
  if [ ! -d "$CLONE_DIR/.git" ]; then
    log "Cloning repo from $REPO_URL..."
    git clone "$REPO_URL" "$CLONE_DIR"
  else
    log "Repo already exists, pulling latest..."
    (cd "$CLONE_DIR" && git pull) || true
  fi
fi

# 10. Make scripts executable
chmod +x "$CLONE_DIR/scripts/"*.py "$CLONE_DIR/scripts/"*.sh 2>/dev/null || true

log "Setup complete. Run: bash $CLONE_DIR/scripts/run_pipeline.py"
