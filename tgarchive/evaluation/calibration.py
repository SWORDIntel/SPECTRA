"""
SPECTRA Evaluation Harness — Model Calibration Metrics & Recalibration
======================================================================
Implements calibration evaluation and recalibration algorithms:
- Brier Score: Mean squared error of probabilistic predictions
- Expected Calibration Error (ECE): Binned calibration error
- Reliability Diagrams: Binned confidence vs accuracy statistics
- Isotonic Calibration: Non-parametric probability recalibration via PAV

All routines use pure NumPy with zero scikit-learn dependencies.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Sequence, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


def brier_score(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
) -> float:
    """Calculate Brier score (mean squared error between predicted probabilities and actual outcomes).

    Brier = (1 / N) * sum((y_prob_i - y_true_i) ** 2)

    Args:
        y_true: Ground truth binary labels (0 or 1).
        y_prob: Predicted probabilities in range [0, 1].

    Returns:
        float: Brier score in range [0.0, 1.0]. Lower values indicate better
        probabilistic calibration and accuracy. Returns 0.0 if inputs are empty.

    Raises:
        ValueError: If y_true and y_prob have different lengths.
    """
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_prob, dtype=float)

    if len(y_t) == 0 or len(y_p) == 0:
        return 0.0

    if len(y_t) != len(y_p):
        raise ValueError(
            f"y_true and y_prob must have matching lengths, got {len(y_t)} and {len(y_p)}"
        )

    return float(np.mean((y_p - y_t) ** 2))


def reliability_data(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    n_bins: int = 10,
) -> List[Tuple[float, float, float, float, int]]:
    """Compute reliability diagram data partitioned into confidence bins.

    Partitions [0, 1] into n_bins equal-width intervals:
    [0, 1/B), [1/B, 2/B), ..., [(B-1)/B, 1.0].
    The final bin is inclusive of 1.0.

    Args:
        y_true: Ground truth binary labels (0 or 1).
        y_prob: Predicted probabilities in range [0, 1].
        n_bins: Number of confidence bins (default: 10).

    Returns:
        List of tuples: (bin_lower, bin_upper, mean_confidence, mean_accuracy, count)
        for each bin from 0 to n_bins - 1.

    Raises:
        ValueError: If n_bins <= 0 or if y_true and y_prob have different lengths.
    """
    if n_bins <= 0:
        raise ValueError(f"n_bins must be a positive integer, got {n_bins}")

    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_prob, dtype=float)

    if len(y_t) != len(y_p):
        raise ValueError(
            f"y_true and y_prob must have matching lengths, got {len(y_t)} and {len(y_p)}"
        )

    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    results: List[Tuple[float, float, float, float, int]] = []

    if len(y_t) == 0:
        for b in range(n_bins):
            b_low = float(bin_boundaries[b])
            b_high = float(bin_boundaries[b + 1])
            results.append((b_low, b_high, 0.0, 0.0, 0))
        return results

    # Clamp probabilities to [0, 1] for binning
    y_p_clamped = np.clip(y_p, 0.0, 1.0)

    for b in range(n_bins):
        b_low = float(bin_boundaries[b])
        b_high = float(bin_boundaries[b + 1])

        if b == n_bins - 1:
            mask = (y_p_clamped >= b_low) & (y_p_clamped <= b_high)
        else:
            mask = (y_p_clamped >= b_low) & (y_p_clamped < b_high)

        count = int(np.sum(mask))
        if count > 0:
            mean_conf = float(np.mean(y_p_clamped[mask]))
            mean_acc = float(np.mean(y_t[mask]))
        else:
            mean_conf = 0.0
            mean_acc = 0.0

        results.append((b_low, b_high, mean_conf, mean_acc, count))

    return results


def expected_calibration_error(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    n_bins: int = 10,
) -> float:
    """Calculate Expected Calibration Error (ECE).

    ECE = sum_{b=1}^{B} (|B_b| / N) * |mean_confidence(b) - mean_accuracy(b)|

    Args:
        y_true: Ground truth binary labels (0 or 1).
        y_prob: Predicted probabilities in range [0, 1].
        n_bins: Number of confidence bins (default: 10).

    Returns:
        float: Expected Calibration Error in range [0.0, 1.0]. Lower values
        indicate better calibration. Returns 0.0 if inputs are empty.

    Raises:
        ValueError: If n_bins <= 0 or if y_true and y_prob have different lengths.
    """
    if n_bins <= 0:
        raise ValueError(f"n_bins must be a positive integer, got {n_bins}")

    data = reliability_data(y_true, y_prob, n_bins=n_bins)
    total_samples = sum(item[4] for item in data)
    if total_samples == 0:
        return 0.0

    ece = 0.0
    for _, _, mean_conf, mean_acc, count in data:
        if count > 0:
            ece += (count / total_samples) * abs(mean_conf - mean_acc)

    return float(ece)


def _fit_isotonic_pav(
    x: np.ndarray,
    y: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit isotonic regression via Pool Adjacent Violators (PAV) algorithm.

    Args:
        x: 1D array of uncalibrated predicted probabilities.
        y: 1D array of true binary outcomes (0 or 1).

    Returns:
        Tuple of (unique_x, y_calibrated) representing monotonic calibration steps.
    """
    if len(x) == 0:
        return np.array([], dtype=float), np.array([], dtype=float)

    # Sort pairs by x ascending
    order = np.argsort(x)
    x_sorted = x[order]
    y_sorted = y[order]

    # Pre-aggregate points with identical x values
    unique_x: List[float] = []
    weights: List[float] = []
    sums: List[float] = []

    i = 0
    n = len(x_sorted)
    while i < n:
        curr_x = float(x_sorted[i])
        curr_w = 0.0
        curr_s = 0.0
        while i < n and x_sorted[i] == curr_x:
            curr_w += 1.0
            curr_s += float(y_sorted[i])
            i += 1
        unique_x.append(curr_x)
        weights.append(curr_w)
        sums.append(curr_s)

    # Pool Adjacent Violators (PAV)
    # Each block is [weight, sum_y, mean_y]
    blocks: List[List[float]] = []
    block_indices: List[List[int]] = []  # [start_idx, end_idx]

    for idx in range(len(unique_x)):
        w = weights[idx]
        s = sums[idx]
        m = s / w
        blocks.append([w, s, m])
        block_indices.append([idx, idx])

        # Merge adjacent blocks while monotonicity is violated (mean_{k-1} > mean_k)
        while len(blocks) >= 2 and blocks[-2][2] > blocks[-1][2]:
            b2 = blocks.pop()
            b1 = blocks.pop()
            r2 = block_indices.pop()
            r1 = block_indices.pop()

            merged_w = b1[0] + b2[0]
            merged_s = b1[1] + b2[1]
            merged_m = merged_s / merged_w

            blocks.append([merged_w, merged_s, merged_m])
            block_indices.append([r1[0], r2[1]])

    # Build fitted monotonic values array
    y_fitted = np.empty(len(unique_x), dtype=float)
    for b, r in zip(blocks, block_indices):
        y_fitted[r[0]:r[1] + 1] = b[2]

    return np.asarray(unique_x, dtype=float), y_fitted


def calibration_map(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
) -> Callable[[Union[float, Sequence[float], np.ndarray]], Union[float, List[float], np.ndarray]]:
    """Build a probability recalibration mapping function using Isotonic Regression.

    Fits a non-parametric isotonic regression curve via the Pool Adjacent Violators (PAV)
    algorithm without relying on scikit-learn.

    Args:
        y_true: Ground truth binary outcomes (0 or 1).
        y_prob: Uncalibrated predicted probabilities in range [0, 1].

    Returns:
        Callable function `calibrated_fn(prob)` which takes an uncalibrated probability
        (scalar float, list of floats, or numpy array) and returns the recalibrated
        probability in [0.0, 1.0].
    """
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_prob, dtype=float)

    if len(y_t) != len(y_p):
        raise ValueError(
            f"y_true and y_prob must have matching lengths, got {len(y_t)} and {len(y_p)}"
        )

    # Clamp training probabilities
    y_p_clamped = np.clip(y_p, 0.0, 1.0)
    unique_x, y_fitted = _fit_isotonic_pav(y_p_clamped, y_t)

    logger.debug(
        "Fitted isotonic calibration map on %d samples (%d unique knots)",
        len(y_t),
        len(unique_x),
    )

    def calibrated_fn(
        prob: Union[float, Sequence[float], np.ndarray],
    ) -> Union[float, List[float], np.ndarray]:
        is_scalar = isinstance(prob, (int, float, np.floating, np.integer))
        p_arr = np.asarray(prob, dtype=float)

        if len(unique_x) == 0:
            res = np.clip(p_arr, 0.0, 1.0)
        elif len(unique_x) == 1 or unique_x[0] == unique_x[-1]:
            res = np.full_like(p_arr, np.clip(y_fitted[0], 0.0, 1.0))
        else:
            res = np.interp(
                p_arr,
                unique_x,
                y_fitted,
                left=float(y_fitted[0]),
                right=float(y_fitted[-1]),
            )
            res = np.clip(res, 0.0, 1.0)

        if is_scalar:
            return float(res.item()) if hasattr(res, "item") else float(res)
        if isinstance(prob, list):
            return res.tolist()
        return res

    return calibrated_fn


__all__ = [
    "brier_score",
    "expected_calibration_error",
    "reliability_data",
    "calibration_map",
]
