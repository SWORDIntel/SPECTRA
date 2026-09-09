#!/usr/bin/env python3
"""
NetFix LoRA fine-tuning script.
Fine-tunes Phi-3.5-mini-instruct on network repair examples.
Runs on L40S (48GB) - completes in ~45 min for 3.8B model.

Usage on cloud VM:
    source /opt/training-venv/bin/activate
    python3 train_netfix.py \
        --base-model Qwen/Qwen2.5-1.5B-Instruct \
        --data-path /opt/training-repo/netfix/data/train.jsonl \
        --output-dir /opt/training-repo/models/netfix \
        --epochs 4
"""
import argparse
import json
import os
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
)
from trl import SFTConfig, SFTTrainer


def load_jsonl(path: str) -> Dataset:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return Dataset.from_list(rows)


def format_messages(example, tokenizer):
    """Apply chat template to messages list."""
    text = tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}


def main():
    parser = argparse.ArgumentParser(description="NetFix LoRA fine-tuner")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--data-path",  required=True, help="Path to train.jsonl")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--epochs",     type=int,   default=4)
    parser.add_argument("--batch-size", type=int,   default=2)
    parser.add_argument("--grad-accum", type=int,   default=4)
    parser.add_argument("--lr",         type=float, default=2e-4)
    parser.add_argument("--lora-r",     type=int,   default=16)
    parser.add_argument("--lora-alpha", type=int,   default=32)
    parser.add_argument("--max-length", type=int,   default=1024)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"[*] Loading tokenizer: {args.base_model}")
    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"[*] Loading model: {args.base_model}")
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
            "q_proj", "v_proj", "k_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    print(f"[*] Loading dataset: {args.data_path}")
    dataset = load_jsonl(args.data_path)
    dataset = dataset.map(
        lambda ex: format_messages(ex, tokenizer),
        remove_columns=dataset.column_names,
    )

    # 90/10 train/eval split
    split = dataset.train_test_split(test_size=0.1, seed=42)
    train_ds = split["train"]
    eval_ds  = split["test"]
    print(f"[*] Train: {len(train_ds)} | Eval: {len(eval_ds)}")

    sft_config = SFTConfig(
        output_dir=args.output_dir,
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

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        processing_class=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
    )

    print("[*] Starting training...")
    trainer.train()

    print(f"[*] Saving adapter to {args.output_dir}")
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    # Save merged model for easy inference (no PEFT dependency at runtime)
    print("[*] Merging LoRA weights for inference...")
    merged = trainer.model.merge_and_unload()
    merged_dir = str(args.output_dir) + "-merged"
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    print(f"[*] Merged model saved to {merged_dir}")
    print("[✓] Training complete.")


if __name__ == "__main__":
    main()
