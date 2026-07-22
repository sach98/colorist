# SPDX-License-Identifier: MIT
"""Pinned .cube dialect writer/reader and tetrahedral applier.

Dialect (design.md section 8): LUT_3D_SIZE, DOMAIN_MIN 0 0 0, DOMAIN_MAX 1 1 1,
R fastest, 6 decimals, out-of-domain clamps. Table shape (N, N, N, 3) is
indexed [r, g, b].
"""
from pathlib import Path

import numpy as np


def write_cube(path: Path, table: np.ndarray, title: str) -> None:
    """Write a table in the project's pinned .cube dialect."""
    n = table.shape[0]
    assert table.shape == (n, n, n, 3)

    lines = [
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {n}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    # .cube data order is R fastest, then G, then B.
    flat = table.transpose(2, 1, 0, 3).reshape(-1, 3)
    lines.extend(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in flat)
    path.write_text("\n".join(lines) + "\n")


def read_cube(path: Path) -> np.ndarray:
    """Read a table written in the project's pinned .cube dialect."""
    size = None
    rows = []
    for line in path.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("TITLE"):
            continue
        if value.startswith("LUT_3D_SIZE"):
            size = int(value.split()[1])
            continue
        if value.startswith("DOMAIN"):
            continue
        rows.append([float(channel) for channel in value.split()])

    assert size is not None and len(rows) == size**3
    flat = np.array(rows, dtype=np.float64)
    return flat.reshape(size, size, size, 3).transpose(2, 1, 0, 3)


def apply_lut(table: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """Apply ``table`` to RGB values with clamped tetrahedral interpolation."""
    n = table.shape[0]
    assert table.shape == (n, n, n, 3)

    scaled = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0) * (n - 1)
    indices = np.minimum(scaled.astype(np.int64), n - 2)
    fractions = scaled - indices

    r, g, b = indices[..., 0], indices[..., 1], indices[..., 2]
    fr, fg, fb = fractions[..., 0], fractions[..., 1], fractions[..., 2]

    def vertex(dr: int, dg: int, db: int) -> np.ndarray:
        return table[r + dr, g + dg, b + db]

    c000 = vertex(0, 0, 0)
    c111 = vertex(1, 1, 1)
    out = np.empty_like(c000)

    def interpolate(
        mask: np.ndarray,
        first_fraction: np.ndarray,
        second_fraction: np.ndarray,
        third_fraction: np.ndarray,
        first_vertex: np.ndarray,
        second_vertex: np.ndarray,
    ) -> None:
        first_fraction = first_fraction[..., None]
        second_fraction = second_fraction[..., None]
        third_fraction = third_fraction[..., None]
        out[mask] = (
            (1.0 - first_fraction) * c000
            + (first_fraction - second_fraction) * first_vertex
            + (second_fraction - third_fraction) * second_vertex
            + third_fraction * c111
        )[mask]

    # Six tetrahedra, ordered by the descending fractional components.
    r_g_b = (fr >= fg) & (fg >= fb)
    r_b_g = (fr >= fg) & (fg < fb) & (fr >= fb)
    b_r_g = (fr >= fg) & (fg < fb) & (fr < fb)
    g_r_b = (fr < fg) & (fr >= fb)
    g_b_r = (fr < fg) & (fr < fb) & (fg >= fb)
    b_g_r = (fr < fg) & (fr < fb) & (fg < fb)

    interpolate(r_g_b, fr, fg, fb, vertex(1, 0, 0), vertex(1, 1, 0))
    interpolate(r_b_g, fr, fb, fg, vertex(1, 0, 0), vertex(1, 0, 1))
    interpolate(g_r_b, fg, fr, fb, vertex(0, 1, 0), vertex(1, 1, 0))
    interpolate(b_r_g, fb, fr, fg, vertex(0, 0, 1), vertex(1, 0, 1))
    interpolate(g_b_r, fg, fb, fr, vertex(0, 1, 0), vertex(0, 1, 1))
    interpolate(b_g_r, fb, fg, fr, vertex(0, 0, 1), vertex(0, 1, 1))
    return out
