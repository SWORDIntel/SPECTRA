#!/usr/bin/env python3
"""LoRA fine-tuner for the SPECTRA operator planner."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer


_TRAINER = None
_OUTPUT_DIR: Path | None = None


def _sigterm_handler(signum, frame) -> None:
    if _TRAINER is not None and _OUTPUT_DIR is not None:
        checkpoint_dir = _OUTPUT_DIR / "checkpoint-sigterm"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        _TRAINER.save_model(str(checkpoint_dir))
    raise SystemExit(143)


def load_jsonl(path: Path) -> Dataset:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(payload.get("messages"), list):
                raise ValueError(f"Training row missing messages list at {path}:{line_number}")
            rows.append(payload)
    if len(rows) < 2:
        raise ValueError("Training data must contain at least two rows for train/eval split")
    return Dataset.from_list(rows)


def format_messages(example, tokenizer) -> dict[str, str]:
    text = tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune a SPECTRA operator LoRA")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--data-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora-r", type=int, default=32)
    parser.add_argument("--lora-alpha", type=int, default=64)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--no-merge", action="store_true", help="Skip merged-model output.")
    args = parser.parse_args()

    global _OUTPUT_DIR
    _OUTPUT_DIR = args.output_dir
    args.output_dir.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model.enable_input_require_grads()

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        target_modules=[
            "q_proj",
            "v_proj",
            "k_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    dataset = load_jsonl(args.data_path)
    dataset = dataset.map(
        lambda example: format_messages(example, tokenizer),
        remove_columns=dataset.column_names,
    )
    split = dataset.train_test_split(test_size=0.1, seed=42)

    sft_config = SFTConfig(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        weight_decay=0.01,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        bf16=True,
        tf32=True,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        report_to="none",
        dataset_text_field="text",
        packing=True,
        max_length=args.max_length,
    )

    global _TRAINER
    _TRAINER = SFTTrainer(
        model=model,
        args=sft_config,
        processing_class=tokenizer,
        train_dataset=split["train"],
        eval_dataset=split["test"],
    )
    _TRAINER.train()
    _TRAINER.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    if not args.no_merge:
        merged = _TRAINER.model.merge_and_unload()
        merged_dir = args.output_dir.with_name(f"{args.output_dir.name}-merged")
        merged.save_pretrained(merged_dir, safe_serialization=True)
        tokenizer.save_pretrained(merged_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
