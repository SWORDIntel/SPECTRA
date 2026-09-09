# SPECTRA Operator Training

This directory adapts the CNScan training framework for a SPECTRA-specific operator model. The GPU stack is optional and intended for a separate training host or cloud VM, not the normal SPECTRA workstation install.

The model target is intentionally narrow:

- Input: natural language operator request.
- Output: one strict JSON operation envelope.
- Executor: SPECTRA validates and runs the envelope through `spectra operations run` or a later remote executor.

The model should not learn raw shell command strings as its primary output. It should learn validated SPECTRA operations.

## Generate Data

```bash
python3 training/spectra_operator/generate_data.py \
  --output training/spectra_operator/data/train.jsonl \
  --count-per-template 8
```

The generated JSONL uses chat messages:

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"download media from -1002407846598 to /fast/ULPs"},{"role":"assistant","content":"{\"operation_id\":\"channel.download\",\"arguments\":{\"entity\":\"-1002407846598\",\"output_dir\":\"/fast/ULPs\",\"media_only\":true},\"dry_run\":true}"}]}
```

## Export Audited Operations

Export real operation executions from the SQLite `operation_audit` table:

```bash
python3 training/spectra_operator/export_audit_corpus.py \
  --database spectra.tasks.sqlite3 \
  --output training/spectra_operator/data/operation_audit.jsonl
```

Use repeated `--status` options to select outcomes, for example
`--status completed --status failed`. Equivalent privacy-reviewed records are
deduplicated by default; `--keep-duplicates` retains every audit row.

The exporter opens SQLite read-only and selects an explicit column allowlist.
Each JSONL record contains the redacted request, operation envelope, planned
command, actual argv, status, result, error category, provenance, redaction
version, and a stable SHA-256 deduplication hash. It excludes the audit actor and
all unknown table columns. A second versioned redaction pass removes
credential-bearing keys and flags, labeled secrets, bearer/JWT/provider tokens,
private keys, URL credentials, email addresses, and international phone
numbers. Malformed JSON fields are recorded only as `{"malformed":true}` so
their original contents cannot enter the corpus.

## Train Off-Host

The LoRA trainer mirrors the proven netfix script shape. Install these requirements only on the training machine:

```bash
pip install -r training/spectra_operator/requirements-gpu.txt
python3 training/spectra_operator/train_spectra_operator.py \
  --base-model Qwen/Qwen2.5-7B-Instruct \
  --data-path training/spectra_operator/data/train.jsonl \
  --output-dir models/spectra-operator-qwen7b \
  --epochs 3 \
  --batch-size 2 \
  --grad-accum 8 \
  --lora-r 32 \
  --max-length 2048
```

Hardware guidance for a separate training box:

- L40S: start with Qwen2.5 7B, BF16, LoRA rank 16-32, sequence length 2048.
- H100: use Qwen2.5 14B or 32B if the dataset justifies it; keep 7B as the fast iteration baseline.

## Pipeline Config

`models.yaml` is compatible with the generic cloud runner shape used by the copied framework in `training/cloud_training_framework/`.
