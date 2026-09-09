# Cloud GPU Training Framework

A reusable framework for training ML models on a separate GPU host or preemptible cloud GPU instance (Nebius).
Built from the VNC-T training pipeline and generalized for any model training workload.

## What This Does

- Spins up a preemptible GPU VM on Nebius via CLI
- Pre-seeds your repo + dataset via rsync
- Runs a multi-model training pipeline in tmux
- Live TUI dashboard showing GPU stats, pipeline progress, and logs
- Auto-resumes if the VM is preempted (SIGTERM → save checkpoint → wait for reboot → resume)
- Auto-downloads trained models when all models complete
- Generates HTML reports with confusion matrices, training curves, and benchmarks

## Quick Start

```bash
# 1. Set required env vars
export PROJECT_ID=proj-xxx
export PLATFORM=gpu-l40s-a           # nebius compute platform list
export PRESET=1gpu-40vcpu-160gb      # nebius compute preset list
export SUBNET_ID=vpcsubnet-xxx       # nebius vpc subnet list
export SSH_USER=your-username
export SSH_KEY=~/.ssh/id_rsa

# 2. Edit cloud-init.yaml to add your SSH public key

# 3. Edit scripts/models.yaml to define your training pipeline

# 4. Launch
python3 launch.py                    # create VM + pre-seed + TUI monitor
python3 launch.py --monitor           # just monitor existing VM
python3 launch.py --download          # download trained models
python3 launch.py --stop              # stop VM
python3 launch.py --delete            # delete VM
```

## Remote SPECTRA Index Benchmark

The index benchmark launcher targets an existing SSH host explicitly. It does
not discover or create a VM, and it does not require the GPU Python
requirements on the control workstation.

```bash
python3 remote_index_benchmark.py \
  --target ubuntu@203.0.113.20 \
  --identity-file ~/.ssh/id_ed25519 \
  --remote-dir /opt/training-repo \
  --spectra-bin /opt/training-repo/.venv/bin/spectra \
  --events 1000 \
  --writers 16 \
  --lookups 10 \
  --batch-size 1000
```

The launcher first runs an isolated native capability probe for QIHSE and
KEYSTONE using the Python environment beside the selected `spectra`
executable. It starts `spectra index benchmark` only when both libraries load
and complete a minimal native operation. Every stage has a local SSH timeout
and a remote command timeout. Output is one JSON object using schema
`spectra.remote-index-benchmark.v1`.

Inspect the exact, log-safe SSH argv without connecting:

```bash
python3 remote_index_benchmark.py \
  --target ubuntu@203.0.113.20 \
  --identity-file ~/.ssh/id_ed25519 \
  --dry-run
```

The private-key path is redacted from dry-run output. Command output is also
redacted for common credential fields. The launcher uses subprocess argument
lists and sends Python stages over standard input; it does not interpolate
target-controlled values into a local shell command.

Successful output contains `schema`, `target`, `parameters`, `preflight`,
`benchmark`, and per-stage `timings_seconds`. Preflight failures include the
native capability result but do not start the benchmark. Transport,
validation, timeout, and malformed-output failures are returned as JSON errors.
Exit status is `0` only for a successful dry run or benchmark, and `1` for all
controlled failures.

Host keys are verified by default. Use `--strict-host-key-checking accept-new`
only when first-use enrollment is intended. The remote host must have Python
3.10+, the SPECTRA checkout and runtime environment, and working native QIHSE
and KEYSTONE libraries.

Focused tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Architecture

```
launch.py (local laptop)
  ├─ Creates Nebius VM via `nebius compute instance create`
  ├─ rsyncs repo to VM at /opt/training-repo
  ├─ Starts pipeline via SSH → tmux
  └─ TUI dashboard polls VM every 5s for state

cloud-init.yaml (VM first boot)
  ├─ Creates user with SSH key
  ├─ /opt/setup.sh  — installs CUDA, PyTorch, Python deps
  └─ /opt/run.sh    — downloads dataset, starts training pipeline

scripts/
  ├─ models.yaml           — define your models + training commands here
  ├─ pipeline_state.py     — tracks model completion (survives reboots)
  ├─ run_pipeline.py        — reads models.yaml, runs models sequentially
  ├─ setup.sh              — VM setup (apt packages, PyTorch, pip deps)
  ├─ generate_report.py    — HTML report generator (confusion matrix, curves)
  ├─ augment_dataset.py    — Smart OpenCV augmentation with visual heuristics
  └─ train_template.py     — Template for new model training scripts
```

## Defining Your Pipeline

Edit `scripts/models.yaml` to list your models:

```yaml
models:
  - name: my_classifier
    display_name: "My Image Classifier"
    script: scripts/train_my_classifier.py
    args:
      - --data-dir
      - $DATA_DIR
      - --output-dir
      - $OUTPUT_DIR/my_classifier
      - --epochs
      - "50"
      - --batch-size
      - "256"
    output_dir: models/my_classifier
```

The pipeline runner (`run_pipeline.py`) reads this file and runs each model
sequentially, skipping completed ones (tracked in `pipeline_state.json`).

## Preemptible VM Support

The pipeline is designed for spot/preemptible VMs that can be killed at any time:

1. **SIGTERM handler** in training scripts catches the signal and saves an emergency checkpoint
2. **`pipeline_state.json`** tracks which models completed — survives reboots
3. **`cloud-init.yaml`** only runs full setup on first boot (sentinel file), then always re-runs the pipeline
4. **`run_pipeline.py`** skips completed models and resumes from the interrupted one
5. **Dataset** is only re-downloaded if missing (not every boot)

The VM can be killed and restarted multiple times — it always picks up where it left off.

## Dataset

Place your dataset as a GitHub release asset or any downloadable URL. Set `DATASET_URL`
in `scripts/run_pipeline.py` or `cloud-init.yaml`.

To package locally:
```bash
tar czf dataset.tar.gz -C /path/to/your_dataset .
```

## Outputs

After training completes, models are in `models/`:

- `model-best.pt` — best PyTorch checkpoint
- `model.onnx` — ONNX export for inference
- `model-static.xml` + `.bin` — OpenVINO IR (optional, for NCS2 deployment)
- `model-labels.json` — class labels
- `training_report.json` — training metrics
- `training_curves.json` — per-epoch loss/accuracy

Reports in `reports/`:
- `training-report.html` — full HTML report with benchmarks, confusion matrix, sample predictions

## Requirements

- **Local**: `nebius` CLI, `jq`, `ssh`, `rsync`, Python 3.10+ with `rich`
- **VM**: Ubuntu 22.04+ with NVIDIA GPU (L40s, A100, T4, etc.)

## License

Internal use.
