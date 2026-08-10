"""Deterministic image degradation transforms for differential analysis.

Every transform takes a BGR numpy array and returns a degraded copy.
Parameters are deterministic and reproducible.  Frame drops are handled
at the replay level, not here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# degradation parameter types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DownsampleDegradation:
    """Scale factor applied before upscaling back to the original size.

    A factor of 1.0 means no change.  0.5 means half resolution.
    """

    scale: float  # (0.0, 1.0]


@dataclass(frozen=True)
class BlurDegradation:
    """Gaussian blur with the given sigma (kernel computed as 6*sigma+1)."""

    sigma: float  # >= 0.0


@dataclass(frozen=True)
class PerspectiveDegradation:
    """Small random perspective perturbation.

    Each corner is displaced by up to ``max_shift`` pixels in x and y,
    drawn from the same seed so the transform is deterministic.
    """

    max_shift: float  # pixels
    seed: int = 42


@dataclass(frozen=True)
class BrightnessContrastDegradation:
    """Linear brightness/contrast adjustment: dst = alpha * src + beta."""

    alpha: float  # contrast multiplier (1.0 = no change)
    beta: int     # brightness delta (0 = no change)


@dataclass(frozen=True)
class GaussianNoiseDegradation:
    """Additive Gaussian noise with the given standard deviation."""

    std: float  # >= 0.0
    seed: int = 42


@dataclass(frozen=True)
class SaltPepperNoiseDegradation:
    """Salt-and-pepper noise replacing a fraction of pixels."""

    fraction: float  # [0.0, 1.0]
    seed: int = 42


@dataclass(frozen=True)
class RollingShutterDegradation:
    """Simulate partial rolling-shutter by shifting rows with timing offsets.

    Each row is displaced horizontally and vertically by an amount
    proportional to its row index and the given ``row_time_ratio``.
    A ratio of 0.0 means global shutter; 0.1 means the bottom row lags
    the top by 10 % of the frame height.
    """

    row_time_ratio: float  # >= 0.0
    seed: int = 42


DEGRADATION_TYPES = (
    DownsampleDegradation,
    BlurDegradation,
    PerspectiveDegradation,
    BrightnessContrastDegradation,
    GaussianNoiseDegradation,
    SaltPepperNoiseDegradation,
    RollingShutterDegradation,
)

DEGRADATION_NAMES = {
    DownsampleDegradation: "downsample",
    BlurDegradation: "blur",
    PerspectiveDegradation: "perspective",
    BrightnessContrastDegradation: "brightness_contrast",
    GaussianNoiseDegradation: "gaussian_noise",
    SaltPepperNoiseDegradation: "salt_pepper_noise",
    RollingShutterDegradation: "rolling_shutter",
}


# ---------------------------------------------------------------------------
# apply functions
# ---------------------------------------------------------------------------


def apply_downsample(frame: np.ndarray, degradation: DownsampleDegradation) -> np.ndarray:
    """Downsample then upsample back to the original size."""
    h, w = frame.shape[:2]
    new_w = max(1, int(w * degradation.scale))
    new_h = max(1, int(h * degradation.scale))
    small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def apply_blur(frame: np.ndarray, degradation: BlurDegradation) -> np.ndarray:
    """Apply a Gaussian blur."""
    if degradation.sigma <= 0.0:
        return frame.copy()
    ksize = int(6 * degradation.sigma + 1) | 1
    return cv2.GaussianBlur(frame, (ksize, ksize), degradation.sigma)


def apply_perspective(frame: np.ndarray, degradation: PerspectiveDegradation) -> np.ndarray:
    """Apply a small deterministic perspective perturbation."""
    h, w = frame.shape[:2]
    rng = random.Random(degradation.seed)
    src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    dst = src.copy()
    for i in range(4):
        dst[i, 0] += rng.uniform(-degradation.max_shift, degradation.max_shift)
        dst[i, 1] += rng.uniform(-degradation.max_shift, degradation.max_shift)
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, matrix, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(24, 24, 24))


def apply_brightness_contrast(frame: np.ndarray, degradation: BrightnessContrastDegradation) -> np.ndarray:
    """Adjust brightness and contrast linearly."""
    return cv2.convertScaleAbs(frame, alpha=degradation.alpha, beta=degradation.beta)


def apply_gaussian_noise(frame: np.ndarray, degradation: GaussianNoiseDegradation) -> np.ndarray:
    """Add additive Gaussian noise."""
    if degradation.std <= 0.0:
        return frame.copy()
    rng = np.random.RandomState(degradation.seed)
    noise = rng.normal(0, degradation.std, frame.shape).astype(np.float32)
    result = frame.astype(np.float32) + noise
    return np.clip(result, 0, 255).astype(np.uint8)


def apply_salt_pepper_noise(frame: np.ndarray, degradation: SaltPepperNoiseDegradation) -> np.ndarray:
    """Replace a fraction of pixels with black or white noise."""
    if degradation.fraction <= 0.0:
        return frame.copy()
    rng = random.Random(degradation.seed)
    result = frame.copy()
    total_pixels = frame.shape[0] * frame.shape[1]
    noisy_count = int(total_pixels * degradation.fraction)
    indices = rng.sample(range(total_pixels), noisy_count)
    for idx in indices:
        row = idx // frame.shape[1]
        col = idx % frame.shape[1]
        result[row, col] = (0, 0, 0) if rng.random() < 0.5 else (255, 255, 255)
    return result


def apply_rolling_shutter(frame: np.ndarray, degradation: RollingShutterDegradation) -> np.ndarray:
    """Simulate rolling shutter by shifting each row proportionally."""
    if degradation.row_time_ratio <= 0.0:
        return frame.copy()
    h, w = frame.shape[:2]
    rng = random.Random(degradation.seed)
    max_shift_x = int(w * degradation.row_time_ratio)
    max_shift_y = int(h * degradation.row_time_ratio)
    result = frame.copy()
    for row in range(h):
        fraction = row / h
        dx = int(rng.uniform(-max_shift_x, max_shift_x) * fraction)
        dy = int(rng.uniform(-max_shift_y, max_shift_y) * fraction)
        if dx == 0 and dy == 0:
            continue
        shifted = np.roll(frame[row:row + 1, :, :], dx, axis=1)
        src_y = max(0, min(h - 1, row + dy))
        result[row:row + 1, :, :] = shifted
    return result


APPLY_MAP = {
    DownsampleDegradation: apply_downsample,
    BlurDegradation: apply_blur,
    PerspectiveDegradation: apply_perspective,
    BrightnessContrastDegradation: apply_brightness_contrast,
    GaussianNoiseDegradation: apply_gaussian_noise,
    SaltPepperNoiseDegradation: apply_salt_pepper_noise,
    RollingShutterDegradation: apply_rolling_shutter,
}


def apply_degradation(frame: np.ndarray, degradation) -> np.ndarray:
    """Apply any degradation to a BGR frame."""
    fn = APPLY_MAP.get(type(degradation))
    if fn is None:
        raise TypeError(f"unknown degradation type: {type(degradation).__name__}")
    return fn(frame, degradation)


def degradation_name(degradation) -> str:
    return DEGRADATION_NAMES.get(type(degradation), "unknown")


def degradation_param(degradation) -> float:
    """Extract the primary numeric parameter for sweep ordering."""
    if isinstance(degradation, DownsampleDegradation):
        return degradation.scale
    if isinstance(degradation, BlurDegradation):
        return degradation.sigma
    if isinstance(degradation, PerspectiveDegradation):
        return degradation.max_shift
    if isinstance(degradation, BrightnessContrastDegradation):
        return abs(1.0 - degradation.alpha) + abs(degradation.beta) / 255.0
    if isinstance(degradation, GaussianNoiseDegradation):
        return degradation.std
    if isinstance(degradation, SaltPepperNoiseDegradation):
        return degradation.fraction
    if isinstance(degradation, RollingShutterDegradation):
        return degradation.row_time_ratio
    return 0.0
