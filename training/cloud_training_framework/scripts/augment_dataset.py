#!/usr/bin/env python3
"""Smart parallel dataset augmentation using OpenCV + visual heuristics.

Generalized from the VNC-T augmentation pipeline. Applies domain-aware
transformations based on visual feature extraction:

  - Perspective warps (simulate different viewing angles)
  - JPEG compression artifacts (simulate low-bandwidth capture)
  - Scan-line / screen-capture artifacts
  - Text-aware occlusions (overlay fake window/dialog rectangles)
  - Color channel swaps (simulate different monitor calibrations)
  - Grid-line augmentation for structured UI screens
  - Region-specific blur (simulate motion / poor focus)
  - Brightness/contrast/saturation jitter
  - Elastic distortions

Usage:
  python3 scripts/augment_dataset.py --data-dir data/training_dataset --target-per-class 900
"""
import argparse
import os
import random
import shutil
import time
from pathlib import Path
from multiprocessing import Pool, cpu_count

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance


def extract_visual_features(cv_img):
    """Extract visual features for domain-aware augmentation."""
    h, w = cv_img.shape[:2]
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(cv_img, cv2.COLOR_BGR2HSV)
    brightness = float(gray.mean())
    edges = cv2.Canny(gray, 80, 180)
    edge_density = float(np.count_nonzero(edges)) / edges.size

    # Detect grid lines (structured UI indicator)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                            threshold=max(50, min(w, h) // 12),
                            minLineLength=max(40, min(w, h) // 10),
                            maxLineGap=8)
    horizontal = vertical = 0
    if lines is not None:
        for line in lines[:500]:
            x1, y1, x2, y2 = line.reshape(-1)[:4]
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dx > 3 * max(dy, 1):
                horizontal += 1
            elif dy > 3 * max(dx, 1):
                vertical += 1
    grid_score = min(1.0, (min(horizontal, vertical) + 0.25 * max(horizontal, vertical)) / 80.0)

    # Saturated color ratios
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    hue = hsv[:, :, 0]
    valid = (sat > 110) & (val > 80)
    total = float(h * w)

    red_ratio = float(np.sum(((hue < 10) | (hue > 170)) & valid)) / total
    amber_ratio = float(np.sum(((hue >= 10) & (hue < 30)) & valid)) / total
    green_ratio = float(np.sum(((hue >= 35) & (hue < 85)) & valid)) / total

    return {
        "brightness": brightness,
        "edge_density": edge_density,
        "grid_score": grid_score,
        "red_ratio": red_ratio,
        "amber_ratio": amber_ratio,
        "green_ratio": green_ratio,
        "width": w,
        "height": h,
    }


def augment_image(img_path, output_path, target_features=None):
    """Apply a random set of augmentations to an image."""
    img = cv2.imread(str(img_path))
    if img is None:
        return False

    h, w = img.shape[:2]
    features = extract_visual_features(img)

    # Random augmentation selection
    augmentations = []

    # 1. Brightness/contrast jitter (always)
    augmentations.append(("brightness_contrast", 1.0))

    # 2. JPEG compression (simulate low-bandwidth)
    if random.random() < 0.4:
        augmentations.append(("jpeg_compress", 1.0))

    # 3. Perspective warp
    if random.random() < 0.3:
        augmentations.append(("perspective", 1.0))

    # 4. Color channel swap
    if random.random() < 0.3:
        augmentations.append(("channel_swap", 1.0))

    # 5. Region blur
    if random.random() < 0.2:
        augmentations.append(("region_blur", 1.0))

    # 6. Grid-line overlay (for structured UI screens)
    if features["grid_score"] > 0.3 and random.random() < 0.3:
        augmentations.append(("grid_overlay", 1.0))

    # 7. Occlusion rectangles
    if random.random() < 0.2:
        augmentations.append(("occlusion", 1.0))

    # Apply augmentations
    for aug_type, _ in augmentations:
        if aug_type == "brightness_contrast":
            alpha = random.uniform(0.8, 1.2)
            beta = random.randint(-20, 20)
            img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)

        elif aug_type == "jpeg_compress":
            quality = random.randint(30, 70)
            _, encoded = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            img = cv2.imdecode(encoded, cv2.IMREAD_COLOR)

        elif aug_type == "perspective":
            src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            offset = random.randint(-15, 15)
            dst = np.float32([[offset, offset], [w - offset, offset],
                              [w, h], [0, h - offset]])
            M = cv2.getPerspectiveTransform(src, dst)
            img = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)

        elif aug_type == "channel_swap":
            if random.random() < 0.5:
                img = img[:, :, [2, 1, 0]]  # BGR -> RGB -> BGR swap
            else:
                img = img[:, :, [0, 2, 1]]  # Swap R and G

        elif aug_type == "region_blur":
            rh, rw = random.randint(h // 6, h // 3), random.randint(w // 6, w // 3)
            ry, rx = random.randint(0, h - rh), random.randint(0, w - rw)
            blur_region = cv2.GaussianBlur(img[ry:ry+rh, rx:rx+rw], (15, 15), 0)
            img[ry:ry+rh, rx:rx+rw] = blur_region

        elif aug_type == "grid_overlay":
            color = (128, 128, 128)
            for y in range(0, h, h // 8):
                cv2.line(img, (0, y), (w, y), color, 1)
            for x in range(0, w, w // 8):
                cv2.line(img, (x, 0), (x, h), color, 1)

        elif aug_type == "occlusion":
            rh, rw = random.randint(h // 8, h // 4), random.randint(w // 8, w // 4)
            ry, rx = random.randint(0, h - rh), random.randint(0, w - rw)
            color = (random.randint(200, 255), random.randint(200, 255), random.randint(200, 255))
            cv2.rectangle(img, (rx, ry), (rx + rw, ry + rh), color, -1)

    cv2.imwrite(str(output_path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return True


def process_class(args_tuple):
    """Process a single class directory (for parallel execution)."""
    src_dir, dst_dir, target_count, class_name = args_tuple
    src_images = list(Path(src_dir).glob("*"))
    if not src_images:
        return class_name, 0

    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Copy originals
    count = 0
    for img_path in src_images:
        if img_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
            shutil.copy2(img_path, dst_dir / f"orig_{count}_{img_path.name}")
            count += 1

    # Augment until we reach target
    while count < target_count:
        src_path = random.choice(src_images)
        out_path = dst_dir / f"aug_{count}_{src_path.name}"
        if augment_image(src_path, out_path):
            count += 1

    return class_name, count


def main():
    parser = argparse.ArgumentParser(description="Augment dataset to target per-class count")
    parser.add_argument("--data-dir", required=True, help="Source dataset directory")
    parser.add_argument("--output-dir", default="dataset_augmented", help="Output directory")
    parser.add_argument("--target-per-class", type=int, default=900, help="Target images per class")
    parser.add_argument("--workers", type=int, default=cpu_count(), help="Parallel workers")
    args = parser.parse_args()

    src_dir = Path(args.data_dir)
    dst_dir = Path(args.output_dir)

    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)

    # Find class directories
    class_dirs = [d for d in sorted(src_dir.iterdir()) if d.is_dir()]
    if not class_dirs:
        print(f"No class directories found in {src_dir}")
        return

    print(f"Augmenting {len(class_dirs)} classes to {args.target_per_class} images each...")

    # Parallel processing
    tasks = [(d, dst_dir / d.name, args.target_per_class, d.name) for d in class_dirs]
    with Pool(args.workers) as pool:
        results = pool.map(process_class, tasks)

    print("\nAugmentation complete:")
    for name, count in results:
        print(f"  {name}: {count} images")
    print(f"\nOutput: {dst_dir}")


if __name__ == "__main__":
    main()
