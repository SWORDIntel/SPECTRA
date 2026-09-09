#!/usr/bin/env python3
"""Template training script for the cloud GPU training framework.

Copy this file, rename it, and adapt it for your specific model.
Implements the standard pattern used by all training scripts in this framework:

  - argparse with standard args (--data-dir, --output-dir, --epochs, etc.)
  - Device setup with CUDA detection and CPU fallback
  - Dataset loading with train/val split
  - Model building with backbone fallback chain
  - Training loop with AMP, early stopping, checkpointing
  - SIGTERM handler for preemptible VM emergency checkpoint
  - ONNX export for inference
  - Training report JSON with metrics

Usage:
  python3 scripts/train_template.py --data-dir dataset --output-dir models/my_model --epochs 50
"""
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, random_split
from PIL import Image

from rich.console import Console

console = Console()

# ── Define your classes here ──
CLASSES = ["class_a", "class_b", "class_c"]


# ── SIGTERM handler (for preemptible VM) ──
_sigterm_model = None
_sigterm_output_dir = None

def _sigterm_handler(signum, frame):
    console.print("\n[bold red]⚠ SIGTERM — preemptible VM shutdown! Saving checkpoint...[/bold red]")
    if _sigterm_model is not None:
        try:
            torch.save(_sigterm_model.state_dict(), Path(_sigterm_output_dir) / "model-sigterm.pt")
            console.print("[green]✓ Emergency checkpoint saved[/green]")
        except Exception as e:
            console.print(f"[red]Checkpoint failed: {e}[/red]")
    sys.exit(143)


# ── Dataset ──
class ImageDataset(Dataset):
    """Generic image dataset loader. Expects subdirectory-per-class layout:
        data_dir/
          class_a/
            img1.jpg
            img2.jpg
          class_b/
            img3.jpg
    """
    def __init__(self, root, transform=None):
        self.root = Path(root)
        self.transform = transform
        self.samples = []
        self.class_to_idx = {c: i for i, c in enumerate(CLASSES)}
        for cls in CLASSES:
            cls_dir = self.root / cls
            if cls_dir.is_dir():
                for img_path in cls_dir.glob("*"):
                    if img_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
                        self.samples.append((str(img_path), self.class_to_idx[cls]))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        img = Image.open(path).convert("RGB")
        if self.transform:
            img = self.transform(img)
        return img, label


# ── Transforms ──
# If torchvision is available, use it. Otherwise, use manual PIL transforms.
try:
    from torchvision import transforms

    def get_transforms(img_size, augment=True):
        if augment:
            return transforms.Compose([
                transforms.Resize((img_size + 32, img_size + 32)),
                transforms.RandomCrop(img_size),
                transforms.RandomHorizontalFlip(p=0.3),
                transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.15),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])
        return transforms.Compose([
            transforms.Resize((img_size, img_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
except ImportError:
    # Manual transforms (no torchvision dependency)
    IMG_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    IMG_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    class ManualTransform:
        def __init__(self, img_size, augment=False):
            self.img_size = img_size
            self.augment = augment

        def __call__(self, img):
            import random
            if self.augment:
                img = img.resize((self.img_size + 32, self.img_size + 32))
                x = random.randint(0, 32)
                y = random.randint(0, 32)
                img = img.crop((x, y, x + self.img_size, y + self.img_size))
                if random.random() < 0.3:
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                brightness = 1.0 + random.uniform(-0.2, 0.2)
                img = Image.eval(img, lambda v: min(255, max(0, int(v * brightness))))
            else:
                img = img.resize((self.img_size, self.img_size))
            arr = np.array(img, dtype=np.float32) / 255.0
            arr = (arr - IMG_MEAN) / IMG_STD
            arr = arr.transpose(2, 0, 1)
            return torch.from_numpy(arr.astype(np.float32))

    def get_transforms(img_size, augment=True):
        return ManualTransform(img_size, augment=augment)


# ── Model ──
# Replace this with your actual model architecture.
# This is a simple CNN that works for small datasets.
class SimpleCNN(nn.Module):
    def __init__(self, num_classes=3, img_size=224):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, stride=2, padding=1),
            nn.BatchNorm2d(32), nn.ReLU6(inplace=True),
            nn.Conv2d(32, 64, 3, stride=2, padding=1),
            nn.BatchNorm2d(64), nn.ReLU6(inplace=True),
            nn.Conv2d(64, 128, 3, stride=2, padding=1),
            nn.BatchNorm2d(128), nn.ReLU6(inplace=True),
            nn.Conv2d(128, 256, 3, stride=2, padding=1),
            nn.BatchNorm2d(256), nn.ReLU6(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU6(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(128, num_classes),
        )

    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


def build_model(num_classes, device):
    """Build model. Replace with your architecture."""
    model = SimpleCNN(num_classes=num_classes)
    model = model.to(device)
    param_count = sum(p.numel() for p in model.parameters())
    console.print(f"[cyan]Model: SimpleCNN ({param_count:,} params)[/cyan]")
    return model


# ── ONNX Export ──
def export_onnx(model, output_dir, img_size, device):
    model.eval()
    dummy = torch.randn(1, 3, img_size, img_size).to(device)
    onnx_path = Path(output_dir) / "model.onnx"
    try:
        torch.onnx.export(model, dummy, str(onnx_path), export_params=True,
                          opset_version=18, input_names=["input"], output_names=["output"],
                          dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}})
        console.print(f"[green]✓ ONNX saved: {onnx_path}[/green]")
        return str(onnx_path)
    except Exception as e:
        console.print(f"[red]✗ ONNX export failed: {e}[/red]")
        return None


# ── Training ──
def train(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    console.print(f"[cyan]Device: {device}[/cyan]")
    if device.type == "cuda":
        console.print(f"[green]GPU: {torch.cuda.get_device_name(0)}[/green]")
        torch.cuda.empty_cache()

    # Dataset
    train_tf = get_transforms(args.img_size, augment=True)
    val_tf = get_transforms(args.img_size, augment=False)
    full_dataset = ImageDataset(args.data_dir, transform=train_tf)
    num_classes = len(CLASSES)
    console.print(f"[cyan]Dataset: {len(full_dataset)} images, {num_classes} classes: {CLASSES}[/cyan]")

    if len(full_dataset) < 10:
        console.print("[red]Not enough images to train![/red]")
        return

    total = len(full_dataset)
    val_size = max(5, int(total * 0.15))
    train_size = total - val_size
    train_ds, val_ds = random_split(full_dataset, [train_size, val_size],
                                     generator=torch.Generator().manual_seed(42))
    val_ds.dataset.transform = val_tf

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=4, pin_memory=True)

    # Model
    model = build_model(num_classes, device)

    # Class weights for imbalance
    label_counts = [0] * num_classes
    for _, label in full_dataset:
        label_counts[label] += 1
    weights = torch.tensor([total / (num_classes * max(1, c)) for c in label_counts],
                           dtype=torch.float32).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.1)
    optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2)
    scaler = torch.amp.GradScaler("cuda") if device.type == "cuda" else None

    # SIGTERM handler
    global _sigterm_model, _sigterm_output_dir
    _sigterm_model = model
    _sigterm_output_dir = output_dir

    # Save labels
    with open(output_dir / "model-labels.json", "w") as f:
        json.dump({"classes": CLASSES, "class_to_idx": {c: i for i, c in enumerate(CLASSES)}}, f, indent=2)

    best_acc = 0.0
    best_epoch = 0
    no_improve = 0
    curves = {"train_loss": [], "val_loss": [], "train_acc": [], "val_acc": []}

    for epoch in range(args.epochs):
        # Train
        model.train()
        train_loss, train_correct, train_total = 0.0, 0, 0
        for images, labels in train_loader:
            images, labels = images.to(device, non_blocking=True), labels.to(device, non_blocking=True)
            optimizer.zero_grad()
            if scaler:
                with torch.amp.autocast("cuda"):
                    outputs = model(images)
                    loss = criterion(outputs, labels)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
                outputs = model(images)
                loss = criterion(outputs, labels)
                loss.backward()
                optimizer.step()
            train_loss += loss.item() * images.size(0)
            train_correct += outputs.argmax(1).eq(labels).sum().item()
            train_total += labels.size(0)
        scheduler.step()

        # Validate
        model.eval()
        val_loss, val_correct, val_total = 0.0, 0, 0
        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device, non_blocking=True), labels.to(device, non_blocking=True)
                if scaler:
                    with torch.amp.autocast("cuda"):
                        outputs = model(images)
                        loss = criterion(outputs, labels)
                else:
                    outputs = model(images)
                    loss = criterion(outputs, labels)
                val_loss += loss.item() * images.size(0)
                val_correct += outputs.argmax(1).eq(labels).sum().item()
                val_total += labels.size(0)

        train_acc = 100. * train_correct / max(1, train_total)
        val_acc = 100. * val_correct / max(1, val_total)
        avg_train_loss = train_loss / max(1, train_total)
        avg_val_loss = val_loss / max(1, val_total)

        curves["train_loss"].append(avg_train_loss)
        curves["val_loss"].append(avg_val_loss)
        curves["train_acc"].append(train_acc)
        curves["val_acc"].append(val_acc)
        with open(output_dir / "training_curves.json", "w") as f:
            json.dump(curves, f)

        console.print(f"Epoch {epoch+1}: train_loss={avg_train_loss:.4f} train_acc={train_acc:.2f}% val_loss={avg_val_loss:.4f} val_acc={val_acc:.2f}%")

        is_best = val_acc > best_acc
        if is_best:
            best_acc = val_acc
            best_epoch = epoch + 1
            no_improve = 0
            torch.save(model.state_dict(), output_dir / "model-best.pt")
        else:
            no_improve += 1

        if no_improve >= args.patience:
            console.print(f"[yellow]Early stopping at epoch {epoch+1}[/yellow]")
            break

    # Export ONNX
    best_path = output_dir / "model-best.pt"
    if best_path.exists():
        model.load_state_dict(torch.load(best_path, map_location=device, weights_only=True))
    model.eval()
    export_onnx(model, output_dir, args.img_size, device)

    # Save report
    report = {
        "model": "template_model",
        "backbone": "simple_cnn",
        "classes": CLASSES,
        "epochs_trained": epoch + 1,
        "best_epoch": best_epoch,
        "best_val_acc": best_acc,
        "label_counts": dict(zip(CLASSES, label_counts)),
    }
    with open(output_dir / "training_report.json", "w") as f:
        json.dump(report, f, indent=2)

    console.print(f"\n[green]Training done! Best acc: {best_acc:.2f}% at epoch {best_epoch}[/green]")
    console.print(f"[cyan]Label distribution: {dict(zip(CLASSES, label_counts))}[/cyan]")


def get_args():
    p = argparse.ArgumentParser(description="Train model (template)")
    p.add_argument("--data-dir", required=True, help="Training dataset directory")
    p.add_argument("--output-dir", default="models/my_model", help="Output directory")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--img-size", type=int, default=224)
    p.add_argument("--patience", type=int, default=15)
    return p.parse_args()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sigterm_handler)
    train(get_args())
