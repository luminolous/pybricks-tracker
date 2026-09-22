"""Trail colouring modes (ui-spec, Map): plain, color, speed, steer.

Each trail point gets a bin; the map draws one curve per bin, with each
segment coloured by the point it leads to. Binning keeps it to a handful of
curves however long the run is.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtGui import QColor

from app.core.state import Pose
from app.ui import theme

TRAIL_MODES = ("plain", "color", "speed", "steer")
GRADIENT_BINS = 8
HUE_BINS = 12
DARK_BELOW_V = 25  # hsv value under this reads as black
NEUTRAL_BELOW_S = 25  # saturation under this reads as white/grey
SCALE_PERCENTILE = 95  # gradient top: ignore rare spikes

# Black would vanish on the dark map, so "black" is drawn as a muted grey.
SENSED_DARK = "#6B7682"


def _lerp(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    ).name()


def _gradient(stops: Sequence[str], n: int) -> list[str]:
    out = []
    for i in range(n):
        t = i / (n - 1) * (len(stops) - 1)
        k = min(int(t), len(stops) - 2)
        out.append(_lerp(stops[k], stops[k + 1], t - k))
    return out


SPEED_PALETTE = _gradient(("#4C7DFF", "#B45CFF", theme.DANGER), GRADIENT_BINS)
STEER_PALETTE = _gradient((theme.TRAIL, theme.WARN, theme.DANGER), GRADIENT_BINS)
COLOR_PALETTE = [SENSED_DARK, theme.TRAIL] + [
    QColor.fromHsv(round((i + 0.5) * 360 / HUE_BINS) % 360, 200, 235).name()
    for i in range(HUE_BINS)
]


def _scale(values: np.ndarray) -> float:
    if values.size == 0:
        return 1.0
    return max(float(np.percentile(values, SCALE_PERCENTILE)), 1.0)


def _gradient_bins(values: np.ndarray, top: float) -> np.ndarray:
    return np.clip((values / top * GRADIENT_BINS).astype(int), 0, GRADIENT_BINS - 1)


def _color_bin(hsv: tuple[int, int, int] | None) -> int:
    if hsv is None:
        return 1
    h, s, v = hsv
    if v < DARK_BELOW_V:
        return 0
    if s < NEUTRAL_BELOW_S:
        return 1
    return 2 + int(h % 360 / 360 * HUE_BINS)


def trail_bins(trail: Sequence[Pose], mode: str) -> tuple[np.ndarray, list[str], str | None]:
    """Per-point bin indices, the palette they index, and a legend line.

    Plain returns a single bin and no legend.
    """
    n = len(trail)
    if mode == "speed":
        values = np.fromiter((p.speed_mm_s for p in trail), float, n)
        top = _scale(values)
        legend = f"speed 0–{top:.0f} mm/s · blue slow, red fast"
        return _gradient_bins(values, top), SPEED_PALETTE, legend
    if mode == "steer":
        values = np.fromiter((abs(p.steer) for p in trail), float, n)
        top = _scale(values)
        legend = f"|steer| 0–{top:.0f} °/s · light calm, red fighting the line"
        return _gradient_bins(values, top), STEER_PALETTE, legend
    if mode == "color":
        bins = np.fromiter((_color_bin(p.hsv) for p in trail), int, n)
        return bins, COLOR_PALETTE, "colour the sensor saw · grey = black"
    return np.zeros(n, dtype=int), [theme.TRAIL], None


def segment_masks(bins: np.ndarray, palette_size: int) -> list[np.ndarray]:
    """For each bin, pyqtgraph's `connect` array: segment i -> i+1 takes bin[i + 1]."""
    masks = []
    for b in range(palette_size):
        mask = np.zeros(len(bins), dtype=bool)
        if len(bins) > 1:
            mask[:-1] = bins[1:] == b
        masks.append(mask)
    return masks
