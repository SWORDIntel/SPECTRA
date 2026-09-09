# SPECTRA Cloud Training Framework

This directory is a native copy of the CNScan cloud training framework, pruned for public-repo safety. Its GPU dependencies are for a separate training host or cloud VM only.

Copied in:

- Nebius launcher and `cloud-init.yaml`
- generic pipeline scripts
- off-host GPU requirements
- NetFix source example and daemon/scripts
- model runner configuration templates

Excluded on purpose:

- `.env` and local launcher secrets
- `.learn` indices
- generated JSONL datasets
- trained adapters, merged models, checkpoints, tokenizer artifacts, and optimizer state
- Python bytecode caches

SPECTRA-specific operator training lives in:

```text
training/spectra_operator/
```

Recommended iteration path:

```bash
python3 training/spectra_operator/generate_data.py \
  --output training/spectra_operator/data/train.jsonl \
  --count-per-template 100

# Run these only from the training host/cloud-control machine.
python3 training/cloud_training_framework/launch.py --seed
python3 training/cloud_training_framework/launch.py --monitor
```

Before launch, point the cloud runner at `training/spectra_operator/models.yaml` or copy that model entry into `training/cloud_training_framework/scripts/models.yaml`.

The SPECTRA operator model target is strict operation-envelope JSON, not raw shell commands.

Normal SPECTRA installs should use the root `requirements.txt`. Do not install the training GPU requirements on the operator workstation unless that workstation is also the training box.

For a local machine that only creates/monitors cloud VMs:

```bash
pip install -r training/cloud_training_framework/requirements-launcher.txt
```

## Portable Index Benchmark

Use `remote_index_benchmark.py` to compare the native index path on any
explicitly selected SSH host, including L40S and H100 instances:

```bash
python3 training/cloud_training_framework/remote_index_benchmark.py \
  --target ubuntu@HOST \
  --identity-file ~/.ssh/id_ed25519 \
  --remote-dir /opt/training-repo \
  --spectra-bin /opt/training-repo/.venv/bin/spectra
```

This path is independent of Nebius VM discovery. It preflights actual QIHSE and
KEYSTONE native operations, gates the benchmark on that result, applies bounded
connection and stage timeouts, and emits one structured JSON result. Use
`--dry-run` to validate command construction without opening an SSH connection.

The launcher never prints private-key contents or the identity-file path. It
does not accept credentials as command-line options. Keep cloud tokens and API
material in the provider credential store rather than passing them through this
benchmark command.
